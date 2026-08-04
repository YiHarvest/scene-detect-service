"""场景检测服务的业务逻辑层。

提供任务存储、视频验证、场景分割等核心功能。
"""

from app.services.scene_splitter import (
    SceneInfo,
    SplitResult,
    split_video_by_scenes,
)
from app.services.task_storage import TaskStorage, get_task_storage
from app.services.video_validator import (
    VideoMetadata,
    check_ffmpeg_available,
    check_ffprobe_available,
    validate_video_and_extract_metadata,
)

__all__ = [
    "SceneInfo",
    "SplitResult",
    "TaskStorage",
    "VideoMetadata",
    "check_ffmpeg_available",
    "check_ffprobe_available",
    "get_task_storage",
    "split_video_by_scenes",
    "validate_video_and_extract_metadata",
]