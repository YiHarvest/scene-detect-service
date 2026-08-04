"""场景检测服务的 API 路由。

提供视频上传、分割、查询和下载的 REST API 端点。
"""

from app.api.videos import router

__all__ = ["router"]