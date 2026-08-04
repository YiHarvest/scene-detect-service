"""视频场景检测和分割的 API 路由。

提供视频上传、分割、查询和下载的 REST API 端点。
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
    raise_file_too_large,
    raise_invalid_video,
    raise_segment_missing,
    raise_task_not_found,
    raise_unsupported_media_type,
)
from app.schemas import ManifestSegment, SegmentResponse, SplitVideoResponse
from app.services.scene_splitter import SplitResult, split_video_by_scenes
from app.services.task_storage import get_task_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/videos", tags=["videos"])


@router.post(
    "/split",
    response_model=SplitVideoResponse,
    status_code=status.HTTP_200_OK,
    summary="按场景分割视频",
    description="上传视频文件，检测场景并分割成片段",
)
async def split_video(
    file: Annotated[UploadFile, File(description="要分割的 MP4 视频文件")],
) -> SplitVideoResponse:
    """基于场景检测将视频分割成片段。

    Args:
        file: 上传的视频文件

    Returns:
        SplitVideoResponse：包含任务 ID 和分片信息

    Raises:
        AppException: 如果验证、检测或分割失败
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
            # 重新抛出 AppException（如 file_too_large）
            raise
        except OSError as e:
            logger.error(f"保存上传文件失败：{e}")
            raise_invalid_video(f"保存上传文件失败：{e!s}")

        # 按场景分割视频
        segments_dir = task_storage.get_segments_dir(task_id)
        result = await split_video_by_scenes(source_path, segments_dir, settings)

        # 构建分片响应
        segments = _build_segment_responses(task_id, result)

        # 保存清单
        task_storage.save_manifest(
            task_id=task_id,
            original_filename=file.filename,
            duration_seconds=result.duration_seconds,
            segments=segments,
        )

        logger.info(f"任务 {task_id} 完成，共 {len(segments)} 个分片")

        return SplitVideoResponse(
            task_id=task_id,
            original_filename=file.filename,
            duration_seconds=result.duration_seconds,
            scene_count=len(segments),
            segments=segments,
        )

    except AppException:
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
    response_model=SplitVideoResponse,
    summary="获取任务信息",
    description="获取已完成分割任务的信息",
)
async def get_task(
    task_id: Annotated[str, PathParam(description="任务 ID（UUID4 hex）")],
) -> SplitVideoResponse:
    """获取任务信息。

    Args:
        task_id: 任务标识符

    Returns:
        SplitVideoResponse：包含任务信息

    Raises:
        AppException: 如果任务未找到
    """
    task_storage = get_task_storage()

    # 验证 task_id 格式
    try:
        uuid.UUID(task_id, version=4)
    except ValueError:
        raise_task_not_found(task_id)

    # 加载清单
    manifest = task_storage.load_manifest(task_id)
    segments = _build_manifest_segment_responses(task_id, manifest.segments)

    return SplitVideoResponse(
        task_id=manifest.task_id,
        original_filename=manifest.original_filename,
        duration_seconds=manifest.duration_seconds,
        scene_count=manifest.scene_count,
        segments=segments,
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
    description="删除任务及其所有文件",
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

    # 删除任务（幂等）
    task_storage.delete_task(task_id)


def _build_segment_responses(task_id: str, result: SplitResult) -> list[SegmentResponse]:
    """构建分片响应对象。

    Args:
        task_id: 任务标识符
        result: 场景分割器的分割结果

    Returns:
        SegmentResponse 对象列表
    """
    segments = []

    for scene, segment_path in zip(result.scenes, result.segment_files):
        # 获取实际文件大小
        size_bytes = segment_path.stat().st_size

        segment = SegmentResponse(
            index=scene.index,
            start_seconds=scene.start_seconds,
            end_seconds=scene.end_seconds,
            duration_seconds=scene.end_seconds - scene.start_seconds,
            start_frame=scene.start_frame,
            end_frame=scene.end_frame,
            size_bytes=size_bytes,
            filename=segment_path.name,
            download_url=f"/api/v1/videos/split/{task_id}/segments/{scene.index}",
        )
        segments.append(segment)

    return segments


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
