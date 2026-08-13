"""应用程序配置模块。

使用 pydantic-settings 管理环境变量和配置参数。
支持 .env 文件和环境变量覆盖。
"""

from pathlib import Path

from pydantic import AnyHttpUrl, Field, field_validator
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
    public_base_url: AnyHttpUrl | None = Field(
        default=None,
        description="用于生成可公开访问链接的 HTTP(S) 基础 URL",
    )

    # 工作目录配置
    workspace_root: Path = Field(
        default=Path("./workspace"), description="任务存储的根目录"
    )
    max_upload_bytes: int = Field(
        default=209_715_200,  # 200 MB
        ge=1,
        description="最大上传文件大小（字节）",
    )
    task_ttl_seconds: int = Field(default=3600, ge=0, description="任务生存时间（秒）")

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
    scene_window_width: int = Field(default=2, ge=1, description="自适应检测窗口宽度")
    scene_min_content_value: float = Field(
        default=15.0, ge=0.0, description="场景检测最小内容值"
    )

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
