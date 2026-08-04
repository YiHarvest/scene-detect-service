"""API 请求和响应的 Pydantic 模型定义。

定义了视频分割、分片、清单和健康检查等 API 的数据模型。
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """使用 camelCase 作为 API 响应的基类。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SegmentResponse(ApiModel):
    """视频分片的公开元数据。"""

    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    size_bytes: int = Field(gt=0)
    download_url: str

    @model_validator(mode="after")
    def validate_time_range(self) -> "SegmentResponse":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds 必须大于 start_seconds")
        return self


class SplitVideoResponse(ApiModel):
    """视频分割后返回的结果。"""

    task_id: str
    duration_seconds: float = Field(gt=0)
    segments: list[SegmentResponse]


class ManifestSegment(BaseModel):
    """持久化到磁盘的分片元数据。"""

    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    size_bytes: int = Field(gt=0)
    filename: str


class Manifest(BaseModel):
    """持久化到磁盘的内部任务清单。"""

    version: Literal[1] = 1
    task_id: str
    original_filename: str
    duration_seconds: float = Field(gt=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    segments: list[ManifestSegment]


class HealthResponse(ApiModel):
    """服务依赖状态。"""

    status: Literal["ok", "degraded"]
    ffmpeg_available: bool
    ffprobe_available: bool
    scene_detect_available: bool