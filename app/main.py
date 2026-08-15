"""场景检测服务的主 FastAPI 应用程序。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.videos import router as videos_router
from app.config import get_settings
from app.errors import (
    AppException,
    ErrorCode,
    create_error_response,
)
from app.schemas import HealthResponse
from app.services.job_queue import get_job_queue
from app.services.task_storage import get_task_storage
from app.services.video_validator import (
    check_ffmpeg_available,
    check_ffprobe_available,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用程序生命周期管理器。"""
    # 启动
    settings = get_settings()
    logger.info(f"正在启动场景检测服务，地址：{settings.host}:{settings.port}")
    logger.info(f"工作目录：{settings.workspace_root}")

    # 清理过期任务
    task_storage = get_task_storage()
    deleted = task_storage.cleanup_expired_tasks()
    if deleted > 0:
        logger.info(f"启动时清理了 {deleted} 个过期任务")

    # 启动任务队列：先启动 worker，再恢复中断任务；恢复量超过队列容量时
    # worker 可同步消费，保证任务不会因容量限制丢失。
    job_queue = get_job_queue()
    job_queue.start()
    await job_queue.recover_pending()

    yield

    # 关闭
    await job_queue.shutdown()
    logger.info("正在关闭场景检测服务")


# 创建 FastAPI 应用
app = FastAPI(
    title="Scene Detection Service",
    description="Video scene detection and splitting service using PySceneDetect",
    version="1.0.0",
    lifespan=lifespan,
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(videos_router)


# 异常处理器
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """处理应用程序异常。"""
    logger.error(f"AppException: {exc.code} - {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        ),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """处理 HTTP 异常。"""
    logger.error(f"HTTPException: {exc.status_code} - {exc.detail}")

    # 状态码到错误码的映射
    code_map = {
        status.HTTP_400_BAD_REQUEST: ErrorCode.INVALID_REQUEST,
        status.HTTP_404_NOT_FOUND: ErrorCode.TASK_NOT_FOUND,
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: ErrorCode.FILE_TOO_LARGE,
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
        status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorCode.INTERNAL_ERROR,
        status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.INTERNAL_ERROR,
    }

    code = code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR)

    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            code=code,
            message=str(exc.detail),
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """处理请求验证错误。"""
    logger.error(f"ValidationError: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=create_error_response(
            code=ErrorCode.INVALID_REQUEST,
            message="请求验证失败",
            details=exc.errors(),
        ),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """处理未预期的异常。"""
    logger.exception(f"未预期的错误：{exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=create_error_response(
            code=ErrorCode.INTERNAL_ERROR,
            message="发生未预期的错误",
            details={
                "type": type(exc).__name__,
                "message": str(exc),
            },
        ),
    )


# 健康检查端点
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="健康检查",
    description="检查服务健康状态和依赖项可用性",
)
async def health_check() -> HealthResponse:
    """检查服务健康状态。

    Returns:
        HealthResponse：包含可用性状态

    Note:
        如果 FFmpeg 或 FFprobe 不可用，返回 503
    """
    ffmpeg_ok = await check_ffmpeg_available()
    ffprobe_ok = await check_ffprobe_available()

    # 检查 PySceneDetect 是否可导入
    try:
        import scenedetect  # noqa: F401

        scene_detect_ok = True
    except ImportError:
        scene_detect_ok = False

    # 如果关键依赖缺失，返回 503
    if not ffmpeg_ok or not ffprobe_ok or not scene_detect_ok:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=create_error_response(
                code=ErrorCode.FFMPEG_UNAVAILABLE
                if not ffmpeg_ok
                else ErrorCode.FFPROBE_UNAVAILABLE
                if not ffprobe_ok
                else ErrorCode.INTERNAL_ERROR,
                message="必需的依赖项不可用",
            ),
        )

    return HealthResponse(
        status="ok",
        ffmpeg_available=ffmpeg_ok,
        ffprobe_available=ffprobe_ok,
        scene_detect_available=scene_detect_ok,
    )


def main() -> None:
    """使用 uvicorn 运行应用程序。"""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
