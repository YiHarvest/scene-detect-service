"""应用程序配置测试。"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_public_base_url_accepts_https_base_path(tmp_path):
    """公开基础地址允许包含部署路径。"""
    settings = Settings(
        _env_file=None,
        workspace_root=tmp_path,
        public_base_url="https://video.example.com/media/",
    )

    assert str(settings.public_base_url) == "https://video.example.com/media/"


def test_public_base_url_rejects_non_http_scheme(tmp_path):
    """公开基础地址只接受 HTTP(S) URL。"""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            workspace_root=tmp_path,
            public_base_url="ftp://video.example.com/media/",
        )
