"""视频场景检测和分割的 API 路由。

提供视频上传（入队）、状态查询、分片下载和任务删除的 REST API 端点。
分割在后台队列中执行，POST 立即返回任务状态，客户端轮询 GET 获取结果。
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from app.config import get_settings
from app.errors import (
    AppException,
    ErrorDetail,
    raise_file_too_large,
    raise_invalid_video,
    raise_segment_missing,
    raise_task_not_found,
    raise_unsupported_media_type,
)
from app.schemas import JobStatusResponse, ManifestSegment, SegmentResponse
from app.services.job_queue import get_job_queue
from app.services.task_storage import (
    TASK_CANCELLED,
    TASK_QUEUED,
    get_task_storage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


@router.post(
    "/split",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交视频分割任务",
    description="上传视频文件，创建分割任务并入队；通过 GET 查询处理状态与结果",
)
async def split_video(
    file: Annotated[UploadFile, File(description="要分割的 MP4 视频文件")],
) -> JobStatusResponse:
    """上传视频并入队分割任务。

    Args:
        file: 上传的视频文件

    Returns:
        JobStatusResponse：任务 ID 与 queued 状态
    """
    settings = get_settings()
    task_storage = get_task_storage()

    # 验证文件扩展名
    if not file.filename or not file.filename.lower().endswith(".mp4"):
        raise_unsupported_media_type("仅支持 MP4 文件")

    # 验证内容类型
    content_type = file.content_type or ""
    if content_type and content_type != "video/mp4":
        raise_unsupported_media_type(f"期望 video/mp4，实际为 {content_type}")

    # 创建任务
    task_id = task_storage.create_task(file.filename)
    logger.info(f"为 {file.filename} 创建任务 {task_id}")

    try:
        # 以流式方式保存上传的文件
        source_path = task_storage.get_source_path(task_id)
        total_size = 0

        try:
            import aiofiles

            async with aiofiles.open(source_path, "wb") as f:
                while chunk := await file.read(1024 * 1024):  # 1 MB 分块
                    total_size += len(chunk)

                    # 检查大小限制
                    if total_size > settings.max_upload_bytes:
                        raise_file_too_large(total_size, settings.max_upload_bytes)

                    await f.write(chunk)

            logger.info(f"已保存 {total_size} 字节到 {source_path}")

        except AppException:
            raise
        except OSError as e:
            logger.error(f"保存上传文件失败：{e}")
            raise_invalid_video(f"保存上传文件失败：{e!s}")

        # 入队：状态落盘后交给 worker 池处理
        task_storage.write_status(task_id, TASK_QUEUED, original_filename=file.filename)
        if not get_job_queue().enqueue(task_id):
            task_storage.delete_task(task_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="视频处理队列已满，请稍后重试",
            )

        logger.info(f"任务 {task_id} 已入队（{total_size} 字节）")
        return JobStatusResponse(
            task_id=task_id,
            status="queued",
            original_filename=file.filename,
        )

    except (AppException, HTTPException):
        # 出错时清理任务
        task_storage.delete_task(task_id)
        raise
    except OSError as e:
        # 未预期错误时清理任务
        logger.error(f"任务 {task_id} 发生未预期错误：{e}")
        task_storage.delete_task(task_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/split/{task_id}",
    response_model=JobStatusResponse,
    summary="获取任务状态与结果",
    description="查询任务状态；done 时附带完整的切片清单，failed 时附带错误详情",
)
async def get_task(
    task_id: Annotated[str, PathParam(description="任务 ID（UUID4 hex）")],
) -> JobStatusResponse:
    """获取任务状态与结果。

    Args:
        task_id: 任务标识符

    Returns:
        JobStatusResponse：包含任务状态；done 时包含切片清单
    """
    task_storage = get_task_storage()

    # 验证 task_id 格式
    try:
        uuid.UUID(task_id, version=4)
    except ValueError:
        raise_task_not_found(task_id)

    status_data = task_storage.read_status(task_id)
    if status_data is None:
        # 兼容旧版任务：无 status.json 但 manifest 存在视为 done
        if task_storage.get_manifest_path(task_id).exists():
            status_data = {"status": "done", "original_filename": None}
        else:
            raise_task_not_found(task_id)

    task_status = status_data.get("status")

    # done：加载清单返回完整结果
    if task_status == "done":
        manifest = task_storage.load_manifest(task_id)
        segments = _build_manifest_segment_responses(task_id, manifest.segments)
        return JobStatusResponse(
            task_id=manifest.task_id,
            status="done",
            original_filename=manifest.original_filename,
            duration_seconds=manifest.duration_seconds,
            scene_count=manifest.scene_count,
            segments=segments,
        )

    # 非终态：只返回状态与错误
    error_data = status_data.get("error")
    error = ErrorDetail(**error_data) if error_data else None
    return JobStatusResponse(
        task_id=task_id,
        status=task_status or "queued",
        original_filename=status_data.get("original_filename"),
        error=error,
    )


@router.get(
    "/split/{task_id}/segments/{segment_index}",
    response_class=FileResponse,
    summary="下载分片",
    description="下载指定的视频分片",
)
async def download_segment(
    task_id: Annotated[str, PathParam(description="任务 ID（UUID4 hex）")],
    segment_index: Annotated[int, PathParam(description="分片索引（从 1 开始）")],
) -> FileResponse:
    """下载视频分片。

    Args:
        task_id: 任务标识符
        segment_index: 分片索引（从 1 开始）

    Returns:
        FileResponse：包含分片文件

    Raises:
        AppException: 如果任务或分片未找到
    """
    task_storage = get_task_storage()

    # 验证 task_id 格式
    try:
        uuid.UUID(task_id, version=4)
    except ValueError:
        raise_task_not_found(task_id)

    # 加载清单以获取分片信息
    manifest = task_storage.load_manifest(task_id)

    # 查找分片
    segment = None
    for seg in manifest.segments:
        if seg.index == segment_index:
            segment = seg
            break

    if not segment:
        raise_segment_missing(task_id, segment_index)

    # 获取分片文件路径
    segments_dir = task_storage.get_segments_dir(task_id)
    segment_path = segments_dir / segment.filename

    if not segment_path.exists():
        raise_segment_missing(task_id, segment_index)

    return FileResponse(
        path=segment_path,
        media_type="video/mp4",
        filename=segment.filename,
    )


@router.delete(
    "/split/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除任务",
    description="删除任务及其所有文件；处理中的任务标记取消，由 worker 完成后清理",
)
async def delete_task(
    task_id: Annotated[str, PathParam(description="任务 ID（UUID4 hex）")],
) -> None:
    """删除任务。

    Args:
        task_id: 任务标识符

    Note:
        此端点是幂等的 - 即使任务不存在也返回 204
    """
    task_storage = get_task_storage()

    # 验证 task_id 格式
    try:
        uuid.UUID(task_id, version=4)
    except ValueError:
        # 对无效 ID 返回 204（幂等）
        return

    status_data = task_storage.read_status(task_id)

    # 无状态（旧任务或不存在）：幂等删除目录
    if status_data is None:
        task_storage.delete_task(task_id)
        return

    task_status = status_data.get("status")
    if task_status == TASK_QUEUED:
        # 排队中：标记取消并立即删除；worker 取到后看到已取消/目录不存在会跳过
        task_storage.write_status(task_id, TASK_CANCELLED)
        task_storage.delete_task(task_id)
    elif task_status == TASK_CANCELLED:
        # 已取消但 worker 尚未完成清理：保持现状，worker 或重启恢复会清理
        return
    elif task_status == "processing":
        # 处理中：标记取消，worker 完成后自行清理整批
        task_storage.write_status(task_id, TASK_CANCELLED)
    else:
        # done / failed：直接删除
        task_storage.delete_task(task_id)


def _build_manifest_segment_responses(
    task_id: str, manifest_segments: list[ManifestSegment],
) -> list[SegmentResponse]:
    """从持久化清单构建公开分片响应。"""
    segments = []

    for segment in manifest_segments:
        # 旧版清单未保存帧号；沿用分割器的 30 FPS 近似策略。
        start_frame = segment.start_frame
        end_frame = segment.end_frame
        if start_frame is None or end_frame is None:
            start_frame = int(segment.start_seconds * 30)
            end_frame = max(start_frame + 1, int(segment.end_seconds * 30))

        segments.append(
            SegmentResponse(
                index=segment.index,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                duration_seconds=segment.end_seconds - segment.start_seconds,
                start_frame=start_frame,
                end_frame=end_frame,
                size_bytes=segment.size_bytes,
                filename=segment.filename,
                download_url=(
                    f"/api/v1/videos/split/{task_id}/segments/{segment.index}"
                ),
            )
        )

    return segments
