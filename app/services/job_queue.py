"""异步任务队列。

基于 asyncio.Queue + 固定 worker 协程池控制视频分割并发度：
无论入队多少任务，同时处理的视频数恒等于 queue_worker_count，
从而把 NVENC 编码路数与 ffmpeg 子进程数封顶。

任务状态通过 status.json 落盘（queued → processing → done|failed|cancelled），
进程重启后由 recover_pending 把残留任务重新入队。
"""

import asyncio
import logging
import time
from typing import Any

from app.config import Settings, get_settings
from app.errors import AppException, ErrorCode
from app.schemas import SegmentResponse
from app.services.scene_splitter import split_video_by_scenes
from app.services.task_storage import (
    TASK_CANCELLED,
    TASK_DONE,
    TASK_FAILED,
    TASK_PROCESSING,
    TASK_QUEUED,
    get_task_storage,
)

logger = logging.getLogger(__name__)


def _run_split_sync(
    source_path: Any,
    segments_dir: Any,
    settings: Settings,
) -> Any:
    """在独立线程中运行 async 分割管线（to_thread 只接受同步 callable）。"""
    return asyncio.run(split_video_by_scenes(source_path, segments_dir, settings))


def _error_payload(error: Exception) -> dict[str, Any]:
    """把异常转成 status.json 的 error 字段（与 ErrorDetail 对齐）。"""
    if isinstance(error, AppException):
        return {
            "code": error.code.value if hasattr(error.code, "value") else str(error.code),
            "message": error.message,
            "details": error.details,
        }
    return {
        "code": ErrorCode.INTERNAL_ERROR.value,
        "message": str(error) or "发生未预期的错误",
        "details": {"type": type(error).__name__},
    }


def _build_segment_responses(task_id: str, result: Any) -> list[SegmentResponse]:
    """从分割结果构建公开分片响应（含实际文件大小与下载地址）。"""
    segments = []
    for scene, segment_path in zip(result.scenes, result.segment_files):
        segments.append(
            SegmentResponse(
                index=scene.index,
                start_seconds=scene.start_seconds,
                end_seconds=scene.end_seconds,
                duration_seconds=scene.end_seconds - scene.start_seconds,
                start_frame=scene.start_frame,
                end_frame=scene.end_frame,
                size_bytes=segment_path.stat().st_size,
                filename=segment_path.name,
                download_url=f"/api/v1/videos/split/{task_id}/segments/{scene.index}",
            )
        )
    return segments


class JobQueue:
    """进程内任务队列 + worker 协程池。

    单进程模型：uvicorn 必须以 workers=1 启动，并发完全由本队列控制。
    事件循环不跑 CPU 重活——detect/split 通过 asyncio.to_thread 卸到线程池，
    健康检查与状态轮询始终可响应。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.storage = get_task_storage()
        self.queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=self.settings.queue_max_size
        )
        self._workers: list[asyncio.Task[None]] = []
        self._accepting = False

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动 worker 协程池。"""
        self._accepting = True
        for worker_id in range(1, self.settings.queue_worker_count + 1):
            self._workers.append(asyncio.create_task(self._worker(worker_id)))
        logger.info(f"任务队列已启动，worker 数 {self.settings.queue_worker_count}")

    async def shutdown(self) -> None:
        """停止接收新任务，限时等待队列排空后再取消 worker。"""
        self._accepting = False
        try:
            await asyncio.wait_for(
                self.queue.join(),
                timeout=self.settings.queue_shutdown_grace_seconds,
            )
        except TimeoutError:
            logger.warning(
                "队列未能在 %.1fs 内排空；处理中任务将在下次启动时恢复",
                self.settings.queue_shutdown_grace_seconds,
            )
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("任务队列已停止")

    def enqueue(self, task_id: str) -> bool:
        """尝试入队；服务关停或队列已满时返回 False。"""
        if not self._accepting:
            return False
        try:
            self.queue.put_nowait(task_id)
            return True
        except asyncio.QueueFull:
            return False

    async def recover_pending(self) -> int:
        """进程重启后扫描 workspace，恢复中断的任务。

        - queued/processing：重置为 queued 并重新入队（重跑是幂等的，ffmpeg -y 覆盖）
        - cancelled：删除残留目录
        - 无状态且无清单：半成品（如上传中断），删除
        """
        recovered = 0
        for task_dir in self.settings.workspace_root.iterdir():
            if not task_dir.is_dir() or len(task_dir.name) != 32:
                continue
            try:
                int(task_dir.name, 16)
            except ValueError:
                continue

            task_id = task_dir.name
            status = self.storage.read_status(task_id)
            task_status = status.get("status") if status else None
            manifest_exists = (task_dir / "manifest.json").exists()

            if task_status in (TASK_QUEUED, TASK_PROCESSING):
                # 保留原文件名（manifest 需要），重置后重新入队
                self.storage.write_status(
                    task_id,
                    TASK_QUEUED,
                    original_filename=status.get("original_filename"),
                )
                # 启动恢复不能丢任务；队列满时等待已启动的 worker 腾出空间。
                await self.queue.put(task_id)
                recovered += 1
                logger.info(f"恢复任务 {task_id}（上次状态 {task_status}）")
            elif task_status == TASK_CANCELLED or (
                task_status is None and not manifest_exists
            ):
                self.storage.delete_task(task_id)
        if recovered:
            logger.info(f"已恢复 {recovered} 个中断任务")
        return recovered

    # ---------- worker ----------

    async def _worker(self, worker_id: int) -> None:
        logger.info(f"队列 worker {worker_id} 已启动")
        while True:
            task_id = await self.queue.get()
            try:
                await self._process_task(task_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(f"worker {worker_id} 处理任务 {task_id} 时发生未预期错误")
            finally:
                self.queue.task_done()

    async def _process_task(self, task_id: str) -> None:
        """处理单个任务。"""
        # 检查 + 标记 processing 在同一同步块内完成：事件循环单线程，
        # 中间不会插入 DELETE 的取消/删除，保证与 HTTP 层的原子性。
        status = self.storage.read_status(task_id)
        if status is None or status.get("status") == TASK_CANCELLED:
            return
        attempt = int(status.get("attempt") or 0) + 1
        self.storage.write_status(
            task_id,
            TASK_PROCESSING,
            original_filename=status.get("original_filename"),
            started_at=time.time(),
            attempt=attempt,
        )

        try:
            source_path = self.storage.get_source_path(task_id)
            segments_dir = self.storage.get_segments_dir(task_id)
            # detect/split 是 CPU 重活：卸到线程池，事件循环不被阻塞
            result = await asyncio.to_thread(
                _run_split_sync, source_path, segments_dir, self.settings
            )

            original_filename = status.get("original_filename") or "video.mp4"
            segments = _build_segment_responses(task_id, result)
            self.storage.save_manifest(
                task_id=task_id,
                original_filename=original_filename,
                duration_seconds=result.duration_seconds,
                segments=segments,
            )

            # 完成后复查取消：处理期间被取消则清理整批，不写 done
            final = self.storage.read_status(task_id)
            if final and final.get("status") == TASK_CANCELLED:
                self.storage.delete_task(task_id)
                logger.info(f"任务 {task_id} 处理完成但已被取消，已清理")
                return

            self.storage.write_status(task_id, TASK_DONE, finished_at=time.time())
            logger.info(f"任务 {task_id} 完成，共 {len(segments)} 个分片")
        except Exception as error:  # noqa: BLE001 - worker 必须把任务错误持久化后继续服务
            error_payload = _error_payload(error)
            try:
                current = self.storage.read_status(task_id)
                if current and current.get("status") == TASK_CANCELLED:
                    self.storage.delete_task(task_id)
                    return
                if attempt <= self.settings.queue_max_retries and self._accepting:
                    self.storage.write_status(
                        task_id,
                        TASK_QUEUED,
                        error=error_payload,
                        original_filename=status.get("original_filename"),
                        attempt=attempt,
                    )
                    if self.enqueue(task_id):
                        logger.warning(
                            f"任务 {task_id} 第 {attempt} 次处理失败，已重新入队"
                        )
                        return
                    logger.warning(
                        f"任务 {task_id} 可重试，但等待队列已满，将任务标记为失败"
                    )
                self.storage.write_status(
                    task_id,
                    TASK_FAILED,
                    error=error_payload,
                    finished_at=time.time(),
                    attempt=attempt,
                )
            except OSError:
                # 任务目录已被删除（取消竞态）：无需标记失败
                logger.warning(f"任务 {task_id} 标记失败时目录已不存在")
            logger.error(f"任务 {task_id} 失败：{error_payload['message']}")


# 全局任务队列实例
_job_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    """获取或创建全局任务队列实例。"""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue
