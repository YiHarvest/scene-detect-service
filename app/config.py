"""应用程序配置模块。

使用 pydantic-settings 管理环境变量和配置参数。
支持 .env 文件和环境变量覆盖。
"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量加载的应用程序配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 服务器配置
    host: str = Field(default="0.0.0.0", description="服务器主机地址")
    port: int = Field(default=28200, ge=1, le=65535, description="服务器端口")

    # 工作目录配置
    workspace_root: Path = Field(
        default=Path("./workspace"), description="任务存储的根目录"
    )
    max_upload_bytes: int = Field(
        default=209_715_200,  # 200 MB
        ge=1,
        description="最大上传文件大小（字节）",
    )
    task_ttl_seconds: int = Field(
        default=3600, ge=0, description="任务生存时间（秒）"
    )

    # FFmpeg 配置
    ffmpeg_path: str = Field(default="ffmpeg", description="FFmpeg 可执行文件路径")
    ffprobe_path: str = Field(default="ffprobe", description="FFprobe 可执行文件路径")

    # 场景检测参数
    scene_adaptive_threshold: float = Field(
        default=3.0, ge=0.0, description="场景检测自适应阈值"
    )
    scene_min_length_seconds: float = Field(
        default=0.8, ge=0.0, description="最小场景长度（秒）"
    )
    scene_window_width: int = Field(
        default=2, ge=1, description="自适应检测窗口宽度"
    )
    scene_min_content_value: float = Field(
        default=15.0, ge=0.0, description="场景检测最小内容值"
    )

    # 任务队列配置
    # 并发 worker 数：同时处理的视频数。每个视频占用 1 路 NVENC + 1 个 CPU 线程，
    # 建议不超过可用 GPU 编码路数；默认 4 在单张 4090（8 路 NVENC 上限）下安全。
    queue_worker_count: int = Field(
        default=4, ge=1, le=64, description="队列 worker 协程数（并发视频数上限）"
    )
    # 失败任务最大重试次数（0 = 不重试）。排队/处理中进程崩溃重启后由 recover 重置入队，
    # 不占用此配额。
    queue_max_retries: int = Field(
        default=1, ge=0, le=5, description="失败任务最大重试次数"
    )
    queue_max_size: int = Field(
        default=20, ge=1, le=1000, description="等待队列最大任务数"
    )
    queue_shutdown_grace_seconds: float = Field(
        default=30.0, ge=0.0, le=600.0, description="关停时等待任务完成的秒数"
    )

    # GPU / 编码配置
    # none: 纯 CPU（libx264）；cuda: 使用 NVIDIA NVENC（auto 探测，失败回退 libx264）
    ffmpeg_hw_accel: str = Field(
        default="auto", description="FFmpeg 硬件加速：auto | cuda | none"
    )
    # NVENC 画质（CRF 等价物，0-51，越小越好）；CPU 模式忽略，使用 crf
    ffmpeg_encoder_quality: int = Field(
        default=23, ge=0, le=51, description="编码质量（NVENC 用 -cq，libx264 用 -crf）"
    )
    # NVENC 预设（p1 最快 ~ p7 最好）；CPU 模式忽略，使用 veryfast
    ffmpeg_encoder_preset: str = Field(
        default="p4", description="NVENC 预设 p1-p7"
    )

    @field_validator("ffmpeg_hw_accel")
    @classmethod
    def validate_ffmpeg_hw_accel(cls, value: str) -> str:
        """只接受明确的硬件加速模式，避免拼写错误静默降级。"""
        normalized = value.strip().lower()
        if normalized not in {"auto", "cuda", "none"}:
            raise ValueError("FFMPEG_HW_ACCEL 必须是 auto、cuda 或 none")
        return normalized

    @field_validator("workspace_root", mode="before")
    @classmethod
    def resolve_workspace_path(cls, v: str | Path) -> Path:
        """将工作目录路径解析为绝对路径。"""
        path = Path(v)
        if not path.is_absolute():
            # 将相对路径转换为相对于项目根目录的绝对路径
            path = Path.cwd() / path
        return path.resolve()

    def ensure_workspace(self) -> None:
        """如果工作目录不存在则创建。"""
        self.workspace_root.mkdir(parents=True, exist_ok=True)


# 全局配置实例
_settings: Settings | None = None


def get_settings() -> Settings:
    """获取或创建全局配置实例。"""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_workspace()
    return _settings
