"""核心场景检测和视频分割逻辑。

使用 PySceneDetect 检测视频场景，使用 FFmpeg 分割视频。
"""

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
    logger.info(f"正在将视频分割为 {len(scenes)} 个片段")
    try:
        # 使用 PySceneDetect 的 split_video_ffmpeg
        result = split_video_ffmpeg(
            str(input_path),
            scene_list if scene_list else None,
            output_dir=str(output_directory),
            output_file_template="segment-$SCENE_NUMBER.mp4",
            show_progress=False,
        )

        # 检查返回码
        if result is not None and hasattr(result, "returncode") and result.returncode != 0:
            raise_video_split_failed(
                f"FFmpeg 分割失败，返回码 {result.returncode}"
            )

    except (OSError, RuntimeError) as e:
        logger.error(f"视频分割失败：{e}")
        raise_video_split_failed(f"分割视频失败：{e!s}")

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
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        return False


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