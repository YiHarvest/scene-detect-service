"""场景检测服务 - 视频场景检测和分割服务。

提供基于 PySceneDetect 和 FFmpeg 的视频场景检测与分割功能。
"""

from app.config import Settings, get_settings
from app.errors import AppException, ErrorCode
from app.main import app
from app.schemas import (
    HealthResponse,
    Manifest,
    SegmentResponse,
    SplitVideoResponse,
)

__all__ = [
    "AppException",
    "ErrorCode",
    "HealthResponse",
    "Manifest",
    "SegmentResponse",
    "Settings",
    "SplitVideoResponse",
    "app",
    "get_settings",
]