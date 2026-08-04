"""健康检查端点测试。

测试服务的健康检查功能。
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """创建测试客户端。"""
    return TestClient(app)


def test_health_check_success(client: TestClient):
    """测试成功的健康检查。"""
    response = client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["status"] == "ok"
    assert "ffmpegAvailable" in data
    assert "ffprobeAvailable" in data
    assert "sceneDetectAvailable" in data