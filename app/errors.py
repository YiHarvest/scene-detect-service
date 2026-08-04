"""统一错误处理模块。

定义应用程序的错误码、异常类和错误响应格式。
"""

from enum import Enum
from typing import Any

from fastapi import status
from pydantic import BaseModel


class ErrorCode(str, Enum):
    """API 响应的错误码枚举。
    
    Attributes:
        INVALID_REQUEST: 无效请求
        UNSUPPORTED_MEDIA_TYPE: 不支持的媒体类型
        FILE_TOO_LARGE: 文件过大
        INVALID_VIDEO: 无效视频
        FFMPEG_UNAVAILABLE: FFmpeg 不可用
        FFPROBE_UNAVAILABLE: FFprobe 不可用
        SCENE_DETECTION_FAILED: 场景检测失败
        VIDEO_SPLIT_FAILED: 视频分割失败
        SEGMENT_MISSING: 分片缺失
        TASK_NOT_FOUND: 任务未找到
        INTERNAL_ERROR: 内部错误
    """

    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    FILE_TOO_LARGE = "file_too_large"
    INVALID_VIDEO = "invalid_video"
    FFMPEG_UNAVAILABLE = "ffmpeg_unavailable"
    FFPROBE_UNAVAILABLE = "ffprobe_unavailable"
    SCENE_DETECTION_FAILED = "scene_detection_failed"
    VIDEO_SPLIT_FAILED = "video_split_failed"
    SEGMENT_MISSING = "segment_missing"
    TASK_NOT_FOUND = "task_not_found"
    INTERNAL_ERROR = "internal_error"


class ErrorDetail(BaseModel):
    """错误详情结构。
    
    Attributes:
        code: 错误码
        message: 错误消息
        details: 详细信息（可选）
    """

    code: ErrorCode
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """标准错误响应格式。
    
    Attributes:
        error: 错误详情
    """

    error: ErrorDetail


class AppException(Exception):
    """应用程序特定异常类。
    
    用于在应用程序中抛出统一的异常格式。
    
    Attributes:
        code: 错误码
        message: 错误消息
        status_code: HTTP 状态码
        details: 详细信息（可选）
    
    Example:
        >>> raise AppException(
        ...     code=ErrorCode.INVALID_VIDEO,
        ...     message="视频格式不支持",
        ...     status_code=400
        ... )
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ) -> None:
        """初始化应用程序异常。
        
        Args:
            code: 错误码
            message: 错误消息
            status_code: HTTP 状态码，默认为 400
            details: 详细信息，默认为 None
        """
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def create_error_response(
    code: ErrorCode,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    """创建标准化的错误响应。
    
    Args:
        code: 错误码
        message: 错误消息
        details: 详细信息（可选）
    
    Returns:
        标准化的错误响应字典
    
    Example:
        >>> response = create_error_response(
        ...     code=ErrorCode.INVALID_VIDEO,
        ...     message="视频格式不支持"
        ... )
        >>> response
        {'error': {'code': 'invalid_video', 'message': '视频格式不支持', 'details': None}}
    """
    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
        )
    ).model_dump()


# Convenience functions for common errors
def raise_invalid_video(message: str, details: Any = None) -> None:
    """抛出无效视频错误。
    
    Args:
        message: 错误消息
        details: 详细信息（可选）
    
    Raises:
        AppException: 带有 INVALID_VIDEO 错误码的异常
    """
    raise AppException(
        code=ErrorCode.INVALID_VIDEO,
        message=message,
        status_code=status.HTTP_400_BAD_REQUEST,
        details=details,
    )


def raise_task_not_found(task_id: str) -> None:
    """抛出任务未找到错误。
    
    Args:
        task_id: 任务 ID
    
    Raises:
        AppException: 带有 TASK_NOT_FOUND 错误码的异常
    """
    raise AppException(
        code=ErrorCode.TASK_NOT_FOUND,
        message=f"Task {task_id} not found",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def raise_segment_missing(task_id: str, segment_index: int) -> None:
    """抛出分片缺失错误。
    
    Args:
        task_id: 任务 ID
        segment_index: 分片索引
    
    Raises:
        AppException: 带有 SEGMENT_MISSING 错误码的异常
    """
    raise AppException(
        code=ErrorCode.SEGMENT_MISSING,
        message=f"Segment {segment_index} not found in task {task_id}",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def raise_file_too_large(size_bytes: int, max_bytes: int) -> None:
    """抛出文件过大错误。
    
    Args:
        size_bytes: 文件大小（字节）
        max_bytes: 最大允许大小（字节）
    
    Raises:
        AppException: 带有 FILE_TOO_LARGE 错误码的异常
    """
    raise AppException(
        code=ErrorCode.FILE_TOO_LARGE,
        message=f"File size {size_bytes} bytes exceeds maximum {max_bytes} bytes",
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    )


def raise_unsupported_media_type(content_type: str) -> None:
    """Raise an unsupported media type error."""
    raise AppException(
        code=ErrorCode.UNSUPPORTED_MEDIA_TYPE,
        message=f"Unsupported media type: {content_type}",
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    )


def raise_ffmpeg_unavailable() -> None:
    """Raise an FFmpeg unavailable error."""
    raise AppException(
        code=ErrorCode.FFMPEG_UNAVAILABLE,
        message="FFmpeg is not available",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def raise_ffprobe_unavailable() -> None:
    """Raise an FFprobe unavailable error."""
    raise AppException(
        code=ErrorCode.FFPROBE_UNAVAILABLE,
        message="FFprobe is not available",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def raise_scene_detection_failed(message: str, details: Any = None) -> None:
    """Raise a scene detection failed error."""
    raise AppException(
        code=ErrorCode.SCENE_DETECTION_FAILED,
        message=message,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details=details,
    )


def raise_video_split_failed(message: str, details: Any = None) -> None:
    """Raise a video split failed error."""
    raise AppException(
        code=ErrorCode.VIDEO_SPLIT_FAILED,
        message=message,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details=details,
    )