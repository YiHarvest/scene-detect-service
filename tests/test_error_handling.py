"""全局异常响应测试。"""

import json

import pytest
from fastapi import Request, status

from app.main import general_exception_handler


@pytest.mark.asyncio
async def test_general_exception_includes_details():
    """未预期异常应返回异常类型和消息。"""
    request = Request({"type": "http", "method": "GET", "path": "/"})
    exception = AttributeError("missing scene_count")

    response = await general_exception_handler(request, exception)
    data = json.loads(response.body)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert data["error"]["details"] == {
        "type": "AttributeError",
        "message": "missing scene_count",
    }
