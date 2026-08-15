"""核心场景检测和视频分割逻辑。

使用 PySceneDetect 检测视频场景，使用 FFmpeg 分割视频。
支持 NVIDIA NVENC 硬件编码（通过 arg_override 注入 ffmpeg 参数），
auto 模式探测不可用时自动回退 libx264。
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenedetect import AdaptiveDetector, detect, split_video_ffmpeg

from app.config import Settings, get_settings
from app.errors import raise_scene_detection_failed, raise_video_split_failed
from app.services.video_validator import validate_video_and_extract_metadata

logger = logging.getLogger(__name__)

# NVENC 探测结果缓存：None=未探测，True/False=是否可用
_nvenc_available_cache: bool | None = None


@dataclass
class SceneInfo:
    """检测到的场景信息。"""

    index: int
    start_frame: int
    end_frame: int
    start_seconds: float
    end_seconds: float


@dataclass
class SplitResult:
    """视频分割操作的结果。"""

    scenes: list[SceneInfo]
    segment_files: list[Path]
    duration_seconds: float


async def split_video_by_scenes(
    input_path: Path,
    output_directory: Path,
    settings: Settings | None = None,
) -> SplitResult:
    """基于场景检测分割视频。

    Args:
        input_path: 输入视频文件路径
        output_directory: 保存分片文件的目录
        settings: 应用程序配置（未提供时使用全局配置）

    Returns:
        SplitResult：包含场景信息和分片路径

    Raises:
        AppException: 如果场景检测或分割失败
    """
    if settings is None:
        settings = get_settings()

    # 首先验证视频
    logger.info(f"正在验证视频：{input_path}")
    metadata = await validate_video_and_extract_metadata(input_path)
    logger.info(
        f"视频验证通过：{metadata.duration_seconds}s, "
        f"{metadata.width}x{metadata.height}, {metadata.video_codec}"
    )

    # 检查 FFmpeg 可用性
    if not await _check_ffmpeg_executable(settings.ffmpeg_path):
        raise_video_split_failed("FFmpeg 不可用")

    # 创建输出目录
    output_directory.mkdir(parents=True, exist_ok=True)

    # 检测场景
    logger.info(f"正在检测 {input_path} 中的场景")
    try:
        scene_list = detect(
            str(input_path),
            AdaptiveDetector(
                adaptive_threshold=settings.scene_adaptive_threshold,
                min_scene_len=int(settings.scene_min_length_seconds * 30),  # 近似帧数
                window_width=settings.scene_window_width,
                min_content_val=settings.scene_min_content_value,
            ),
            start_in_scene=True,
        )
    except (OSError, RuntimeError) as e:
        logger.error(f"场景检测失败：{e}")
        raise_scene_detection_failed(f"检测场景失败：{e!s}")

    # 将场景列表转换为 SceneInfo 对象
    scenes = _convert_scene_list(scene_list, metadata.duration_seconds)

    # 如果没有检测到场景，将整个视频视为一个场景
    if not scenes:
        logger.warning("未检测到场景，将整个视频视为一个场景")
        scenes = [
            SceneInfo(
                index=1,
                start_frame=0,
                end_frame=int(metadata.duration_seconds * 30),  # 近似值
                start_seconds=0.0,
                end_seconds=metadata.duration_seconds,
            )
        ]

    logger.info(f"检测到 {len(scenes)} 个场景")

    # 使用 FFmpeg 分割视频
    encode_args = _build_encode_args(settings)
    logger.info(
        f"正在将视频分割为 {len(scenes)} 个片段（编码："
        + ("NVENC" if "nvenc" in encode_args else "libx264 CPU")
        + "）"
    )
    def run_split(arguments: str) -> None:
        """运行一次分割并正确检查 PySceneDetect 返回的整数退出码。"""
        return_code = split_video_ffmpeg(
            str(input_path),
            scene_list,
            output_dir=str(output_directory),
            output_file_template="segment-$SCENE_NUMBER.mp4",
            show_progress=False,
            arg_override=arguments,
        )
        if return_code != 0:
            raise RuntimeError(f"FFmpeg 返回码 {return_code}")

    try:
        run_split(encode_args)
    except (OSError, RuntimeError) as error:
        # 探测帧成功不代表每种输入都能由 NVENC 编码。auto 模式下实际任务
        # 失败时清掉半成品并重试 CPU，cuda 模式则按显式配置直接报错。
        if settings.ffmpeg_hw_accel == "auto" and "h264_nvenc" in encode_args:
            logger.warning(f"NVENC 实际分割失败（{error}），改用 libx264 重试")
            for partial in output_directory.glob("segment-*.mp4"):
                partial.unlink(missing_ok=True)
            try:
                run_split(_build_cpu_encode_args(settings))
            except (OSError, RuntimeError) as fallback_error:
                logger.error(f"CPU 视频分割重试失败：{fallback_error}")
                raise_video_split_failed(f"分割视频失败：{fallback_error!s}")
        else:
            logger.error(f"视频分割失败：{error}")
            raise_video_split_failed(f"分割视频失败：{error!s}")

    # 验证分片是否已创建
    segment_files = _verify_segments(output_directory, len(scenes))

    logger.info(f"成功创建 {len(segment_files)} 个分片")
    return SplitResult(
        scenes=scenes,
        segment_files=segment_files,
        duration_seconds=metadata.duration_seconds,
    )


async def _check_ffmpeg_executable(ffmpeg_path: str) -> bool:
    """检查 FFmpeg 可执行文件是否可用。

    Args:
        ffmpeg_path: FFmpeg 可执行文件路径

    Returns:
        如果 FFmpeg 可用则返回 True
    """
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg_path,
            "-version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(process.wait(), timeout=5) == 0
    except TimeoutError:
        if process is not None:
            process.kill()
            await process.wait()
        return False
    except (FileNotFoundError, PermissionError):
        return False


def _nvenc_available(settings: Settings) -> bool:
    """探测 NVIDIA NVENC 编码器是否真正可用（结果缓存）。

    只查 `ffmpeg -encoders` 不够：ffmpeg 编译进 h264_nvenc 不代表驱动支持
    （驱动版本过低会在打开编码器时报 "Driver does not support the required
    nvenc API version"）。这里用 lavfi 源实际编码 1 帧，退出码 0 才算可用。

    任一条件不满足返回 False，调用方回退 libx264。
    """
    global _nvenc_available_cache
    if _nvenc_available_cache is not None:
        return _nvenc_available_cache

    try:
        result = subprocess.run(
            [
                settings.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                # 部分 NVENC 驱动拒绝 16x16（低于编码器最小尺寸），会造成误判。
                "color=black:size=128x128:rate=1",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            check=False,
            timeout=15,
        )
        nvenc_ok = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        nvenc_ok = False

    if not nvenc_ok:
        stderr = result.stderr.decode("utf-8", errors="replace") if "result" in locals() else ""
        detail = stderr.strip().splitlines()[0] if stderr.strip() else "未知原因"
        _nvenc_available_cache = False
        logger.warning(f"NVENC 编码器不可用（{detail}），回退 libx264 CPU 编码")
        return False

    _nvenc_available_cache = True
    logger.info("检测到 NVIDIA NVENC，视频分割将使用 GPU 编码")
    return True


def _build_encode_args(settings: Settings) -> str:
    """构建 split_video_ffmpeg 的 arg_override。

    - cuda/auto：NVENC 可用时使用 GPU 编码（精确切点 + 硬件加速）
    - none 或探测失败：libx264 CPU 编码

    注意：不能注入 `-hwaccel`（ffmpeg 输入选项必须位于 -i 之前，而
    arg_override 被 scenedetect 追加在 -i 之后，会解析报错），因此解码
    始终走 CPU；NVENC 只加速编码部分，这已是分割耗时的大头。

    保留 scenedetect 默认的 map/音频参数，只替换视频编码器部分。
    """
    base = "-map 0:v:0 -map 0:a? -map 0:s? -c:a aac"

    use_nvenc = (
        settings.ffmpeg_hw_accel in ("cuda", "auto")
        and _nvenc_available(settings)
    )
    if use_nvenc:
        quality = max(0, min(51, settings.ffmpeg_encoder_quality))
        preset = settings.ffmpeg_encoder_preset.strip() or "p4"
        return (
            f"{base} -c:v h264_nvenc -preset {preset} "
            f"-rc vbr -cq {quality} -b:v 0"
        )

    return _build_cpu_encode_args(settings)


def _build_cpu_encode_args(settings: Settings) -> str:
    """构建稳定的 CPU 编码参数，供常规路径和 auto 失败回退共用。"""
    quality = max(0, min(51, settings.ffmpeg_encoder_quality))
    return (
        "-map 0:v:0 -map 0:a? -map 0:s? -c:a aac "
        f"-c:v libx264 -preset veryfast -crf {quality}"
    )


def _convert_scene_list(scene_list: list[Any], total_duration: float) -> list[SceneInfo]:
    """将 PySceneDetect 场景列表转换为 SceneInfo 对象。

    Args:
        scene_list: detect() 返回的场景列表
        total_duration: 视频总时长（秒）

    Returns:
        SceneInfo 对象列表
    """
    scenes = []

    for i, scene in enumerate(scene_list, start=1):
        # 使用新属性访问方式（PySceneDetect 0.6+）
        start_time = getattr(scene[0], 'seconds', 0.0)
        end_time = getattr(scene[1], 'seconds', total_duration)

        start_frame = getattr(scene[0], 'frame_num', 0)
        end_frame = getattr(scene[1], 'frame_num', 0)

        scenes.append(
            SceneInfo(
                index=i,
                start_frame=start_frame,
                end_frame=end_frame,
                start_seconds=start_time,
                end_seconds=end_time,
            )
        )

    return scenes


def _verify_segments(output_directory: Path, expected_count: int) -> list[Path]:
    """验证分片文件是否成功创建。

    Args:
        output_directory: 包含分片文件的目录
        expected_count: 预期的分片数量

    Returns:
        分片文件路径列表

    Raises:
        AppException: 如果分片缺失或无效
    """
    segment_files = []

    for i in range(1, expected_count + 1):
        segment_name = f"segment-{i:03d}.mp4"
        segment_path = output_directory / segment_name

        if not segment_path.exists():
            raise_video_split_failed(f"分片文件未创建：{segment_name}")

        file_size = segment_path.stat().st_size
        if file_size == 0:
            raise_video_split_failed(f"分片文件为空：{segment_name}")

        segment_files.append(segment_path)
        logger.debug(f"已验证分片 {segment_name}：{file_size} 字节")

    return segment_files
