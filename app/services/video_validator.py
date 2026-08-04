"""视频验证和元数据提取服务。

使用 ffprobe 验证视频格式并提取时长、分辨率等元数据。
"""

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.errors import raise_invalid_video

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    """ffprobe 提取的视频元数据。"""

    duration_seconds: float
    video_codec: str
    width: int
    height: int
    fps: float | None


async def check_ffmpeg_available() -> bool:
    """检查系统中 FFmpeg 是否可用。

    Returns:
        如果 FFmpeg 可用则返回 True
    """
    settings = get_settings()
    try:
        result = await asyncio.create_subprocess_exec(
            settings.ffmpeg_path,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await result.communicate()
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f"FFmpeg 检查失败：{e}")
        return False


async def check_ffprobe_available() -> bool:
    """检查系统中 FFprobe 是否可用。

    Returns:
        如果 FFprobe 可用则返回 True
    """
    settings = get_settings()
    try:
        result = await asyncio.create_subprocess_exec(
            settings.ffprobe_path,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await result.communicate()
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f"FFprobe 检查失败：{e}")
        return False


async def validate_video_and_extract_metadata(video_path: Path) -> VideoMetadata:
    """使用 ffprobe 验证视频文件并提取元数据。

    Args:
        video_path: 视频文件路径

    Returns:
        VideoMetadata 对象

    Raises:
        AppException: 如果视频无效或 ffprobe 失败
    """
    settings = get_settings()

    # 检查文件是否存在
    if not video_path.exists():
        raise_invalid_video(f"视频文件未找到：{video_path}")

    if video_path.stat().st_size == 0:
        raise_invalid_video("视频文件为空")

    # 运行 ffprobe
    try:
        result = await asyncio.create_subprocess_exec(
            settings.ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await result.communicate()

        if result.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.error(f"FFprobe 对 {video_path} 执行失败：{error_msg}")
            raise_invalid_video(f"FFprobe 读取视频失败：{error_msg}")

        # 解析 JSON 输出
        try:
            probe_data = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"解析 ffprobe 输出失败：{e}")
            raise_invalid_video("解析 ffprobe 输出失败")

        # 提取元数据
        return _extract_metadata_from_probe(probe_data, video_path)

    except FileNotFoundError:
        logger.error(f"FFprobe 未找到：{settings.ffprobe_path}")
        raise_invalid_video("FFprobe 不可用")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        logger.error(f"视频验证过程中发生未预期错误：{e}")
        raise_invalid_video(f"视频验证失败：{e!s}")


def _extract_metadata_from_probe(probe_data: dict[str, Any], video_path: Path) -> VideoMetadata:
    """从 ffprobe JSON 输出中提取视频元数据。

    Args:
        probe_data: 解析后的 ffprobe JSON 输出
        video_path: 视频文件路径（用于错误消息）

    Returns:
        VideoMetadata 对象

    Raises:
        AppException: 如果视频无效
    """
    # 检查格式部分
    format_info = probe_data.get("format", {})
    if not format_info:
        raise_invalid_video("视频中未找到格式信息")

    # 检查容器格式
    format_name = format_info.get("format_name", "")
    if "mp4" not in format_name.lower() and "mov" not in format_name.lower():
        raise_invalid_video(f"无效的容器格式：{format_name}，期望 MP4")

    # 获取时长
    duration_str = format_info.get("duration")
    if not duration_str:
        raise_invalid_video("无法确定视频时长")

    try:
        duration_seconds = float(duration_str)
    except (ValueError, TypeError):
        raise_invalid_video(f"无效的时长值：{duration_str}")

    if duration_seconds <= 0:
        raise_invalid_video(f"视频时长必须为正数：{duration_seconds}")

    # 查找视频流
    streams = probe_data.get("streams", [])
    video_stream = None
    for stream in streams:
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if not video_stream:
        raise_invalid_video("文件中未找到视频流")

    # 提取视频元数据
    video_codec = video_stream.get("codec_name", "unknown")

    width = video_stream.get("width")
    height = video_stream.get("height")

    if not width or not height:
        raise_invalid_video("无法确定视频尺寸")

    # 提取帧率
    fps: float | None = None
    fps_str = video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate")
    if fps_str:
        try:
            # 处理分数格式，如 "30/1" 或 "30000/1001"
            if "/" in fps_str:
                num, denom = fps_str.split("/")
                fps = float(num) / float(denom)
            else:
                fps = float(fps_str)
        except (ValueError, ZeroDivisionError):
            logger.warning(f"无法解析帧率值：{fps_str}")

    return VideoMetadata(
        duration_seconds=duration_seconds,
        video_codec=video_codec,
        width=int(width),
        height=int(height),
        fps=fps,
    )