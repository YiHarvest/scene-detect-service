"""任务存储和管理服务。

提供任务目录创建、清单保存和加载、过期任务清理等功能。
"""

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import Settings, get_settings
from app.errors import raise_task_not_found
from app.schemas import Manifest, ManifestSegment, SegmentResponse

logger = logging.getLogger(__name__)

# 任务状态机:queued → processing → done | failed | cancelled
TASK_QUEUED = "queued"
TASK_PROCESSING = "processing"
TASK_DONE = "done"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"
TASK_STATUSES = frozenset(
    {TASK_QUEUED, TASK_PROCESSING, TASK_DONE, TASK_FAILED, TASK_CANCELLED}
)


class TaskStorage:
    """管理任务目录和元数据。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化任务存储。"""
        self.settings = settings or get_settings()
        self.workspace_root = self.settings.workspace_root

    def create_task(self, original_filename: str) -> str:
        """创建新的任务目录结构。

        Args:
            original_filename: 原始上传文件名

        Returns:
            任务 ID（UUID4 hex）
        """
        task_id = uuid4().hex
        task_dir = self._get_task_dir(task_id)

        # 创建目录结构
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "source").mkdir(exist_ok=True)
        (task_dir / "segments").mkdir(exist_ok=True)

        logger.info(f"为文件 {original_filename} 创建任务 {task_id}")
        return task_id

    def get_source_path(self, task_id: str) -> Path:
        """获取源视频文件路径。

        Args:
            task_id: 任务标识符

        Returns:
            任务源目录中 original.mp4 的路径
        """
        self._validate_task_id(task_id)
        return self._get_task_dir(task_id) / "source" / "original.mp4"

    def get_segments_dir(self, task_id: str) -> Path:
        """获取分片目录路径。

        Args:
            task_id: 任务标识符

        Returns:
            分片目录路径
        """
        self._validate_task_id(task_id)
        return self._get_task_dir(task_id) / "segments"

    def get_manifest_path(self, task_id: str) -> Path:
        """获取清单文件路径。

        Args:
            task_id: 任务标识符

        Returns:
            manifest.json 的路径
        """
        self._validate_task_id(task_id)
        return self._get_task_dir(task_id) / "manifest.json"

    def get_status_path(self, task_id: str) -> Path:
        """获取任务状态文件路径。

        Args:
            task_id: 任务标识符

        Returns:
            status.json 的路径
        """
        self._validate_task_id(task_id)
        return self._get_task_dir(task_id) / "status.json"

    def read_status(self, task_id: str) -> dict | None:
        """读取任务状态；无状态文件时返回 None。"""
        status_path = self.get_status_path(task_id)
        if not status_path.exists():
            return None
        try:
            with open(status_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"读取任务 {task_id} 状态失败：{e}")
            return None

    def write_status(
        self,
        task_id: str,
        status: str,
        *,
        error: dict | None = None,
        original_filename: str | None = None,
        started_at: float | None = None,
        finished_at: float | None = None,
        attempt: int | None = None,
    ) -> dict:
        """原子地写入任务状态并返回。"""
        self._validate_task_id(task_id)
        if status not in TASK_STATUSES:
            raise ValueError(f"非法任务状态：{status}")

        status_path = self.get_status_path(task_id)
        previous = self.read_status(task_id) or {}
        payload = {
            "task_id": task_id,
            "status": status,
            "error": error,
            "original_filename": original_filename
            if original_filename is not None
            else previous.get("original_filename"),
            "started_at": started_at
            if started_at is not None
            else previous.get("started_at"),
            "finished_at": finished_at,
            "attempt": attempt if attempt is not None else previous.get("attempt", 0),
            "updated_at": time.time(),
        }
        temp_path = status_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, status_path)
        except OSError:
            if temp_path.exists():
                temp_path.unlink()
            raise
        return payload

    def save_manifest(
        self,
        task_id: str,
        original_filename: str,
        duration_seconds: float,
        segments: list[SegmentResponse],
    ) -> Manifest:
        """原子性地保存任务清单。

        Args:
            task_id: 任务标识符
            original_filename: 原始上传文件名
            duration_seconds: 视频总时长
            segments: 视频分片列表（SegmentResponse 对象）

        Returns:
            创建的清单对象
        """
        self._validate_task_id(task_id)

        # 将 SegmentResponse 转换为 ManifestSegment
        manifest_segments = [
            ManifestSegment(
                index=seg.index,
                start_seconds=seg.start_seconds,
                end_seconds=seg.end_seconds,
                start_frame=seg.start_frame,
                end_frame=seg.end_frame,
                size_bytes=seg.size_bytes,
                filename=seg.filename,
            )
            for seg in segments
        ]

        manifest = Manifest(
            version=1,
            task_id=task_id,
            original_filename=original_filename,
            duration_seconds=duration_seconds,
            scene_count=len(manifest_segments),
            created_at=datetime.now(timezone.utc),
            segments=manifest_segments,
        )

        manifest_path = self.get_manifest_path(task_id)
        temp_path = manifest_path.with_suffix(".tmp")

        try:
            # 写入临时文件
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    manifest.model_dump(mode="json"),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
                f.flush()
                os.fsync(f.fileno())

            # 原子性重命名
            os.replace(temp_path, manifest_path)

            logger.info(f"已保存任务 {task_id} 的清单，共 {len(segments)} 个分片")
            return manifest

        except OSError:
            # 出错时清理临时文件
            if temp_path.exists():
                temp_path.unlink()
            raise

    def load_manifest(self, task_id: str) -> Manifest:
        """加载任务清单。

        Args:
            task_id: 任务标识符

        Returns:
            清单对象

        Raises:
            AppException: 如果任务未找到
        """
        self._validate_task_id(task_id)
        manifest_path = self.get_manifest_path(task_id)

        if not manifest_path.exists():
            raise_task_not_found(task_id)

        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
            return Manifest(**data)

    def task_exists(self, task_id: str) -> bool:
        """检查任务是否存在。

        Args:
            task_id: 任务标识符

        Returns:
            如果任务目录存在则返回 True
        """
        try:
            self._validate_task_id(task_id)
            return self._get_task_dir(task_id).exists()
        except ValueError:
            return False

    def delete_task(self, task_id: str) -> bool:
        """删除任务目录。

        Args:
            task_id: 任务标识符

        Returns:
            如果任务被删除返回 True，如果不存在返回 False
        """
        self._validate_task_id(task_id)
        task_dir = self._get_task_dir(task_id)

        if not task_dir.exists():
            return False

        # 安全检查：确保不会删除工作目录外的内容
        if not self._is_safe_path(task_dir):
            logger.error(f"尝试删除不安全的路径：{task_dir}")
            return False

        try:
            shutil.rmtree(task_dir)
            logger.info(f"已删除任务 {task_id}")
            return True
        except OSError as e:
            logger.error(f"删除任务 {task_id} 失败：{e}")
            return False

    def cleanup_expired_tasks(self) -> int:
        """基于 TTL 清理过期任务。

        Returns:
            删除的任务数量
        """
        ttl_seconds = self.settings.task_ttl_seconds
        if ttl_seconds <= 0:
            logger.debug("TTL 为 0 或负数，跳过清理")
            return 0

        current_time = time.time()
        deleted_count = 0

        try:
            for task_dir in self.workspace_root.iterdir():
                if not task_dir.is_dir():
                    continue

                # 检查目录是否为有效任务（32字符十六进制名称）
                if len(task_dir.name) != 32:
                    continue

                try:
                    int(task_dir.name, 16)
                except ValueError:
                    continue

                # 状态以 status.json 为准（异步队列），缺失时回退到清单 mtime。
                # 仅清理终态任务；queued/processing 由 recover 接管，不受 TTL 影响，
                # 避免排队中/处理中的任务被误删。
                status = self.read_status(task_dir.name)
                task_status = status.get("status") if status else None
                if task_status in {TASK_QUEUED, TASK_PROCESSING}:
                    continue

                # 用 status.json 的 updated_at 作为年龄依据；无状态文件时回退 manifest mtime
                if status is not None:
                    mtime = status.get("updated_at") or status.get("finished_at") or 0.0
                else:
                    manifest_path = task_dir / "manifest.json"
                    if not manifest_path.exists():
                        # 无状态也无清单：半成品任务目录，直接清理
                        if self.delete_task(task_dir.name):
                            deleted_count += 1
                        continue
                    mtime = manifest_path.stat().st_mtime

                age_seconds = current_time - mtime
                if age_seconds > ttl_seconds and self.delete_task(task_dir.name):
                    deleted_count += 1

        except OSError as e:
            logger.error(f"清理任务时出错：{e}")

        if deleted_count > 0:
            logger.info(f"已清理 {deleted_count} 个过期任务")

        return deleted_count

    def _get_task_dir(self, task_id: str) -> Path:
        """获取任务目录路径。

        Args:
            task_id: 任务标识符

        Returns:
            任务目录路径
        """
        return self.workspace_root / task_id

    def _validate_task_id(self, task_id: str) -> None:
        """验证 task_id 是否为有效的 UUID4 hex 字符串。

        Args:
            task_id: 要验证的任务标识符

        Raises:
            ValueError: 如果 task_id 无效
        """
        if not isinstance(task_id, str) or len(task_id) != 32:
            raise ValueError(f"无效的 task_id：{task_id}（必须是32字符的十六进制字符串）")

        # 验证是否为有效的十六进制字符串
        try:
            int(task_id, 16)
        except ValueError as e:
            raise ValueError(f"无效的 task_id：{task_id}（必须是十六进制字符串）") from e

    def _is_safe_path(self, path: Path) -> bool:
        """检查路径是否安全（在工作目录内）。

        Args:
            path: 要检查的路径

        Returns:
            如果路径在工作目录内则返回 True
        """
        try:
            # 将两个路径都解析为绝对路径
            resolved_path = path.resolve()
            resolved_workspace = self.workspace_root.resolve()

            # 检查路径是否在工作目录内
            return str(resolved_path).startswith(str(resolved_workspace))
        except (OSError, ValueError):
            return False


# 全局任务存储实例
_task_storage: TaskStorage | None = None


def get_task_storage() -> TaskStorage:
    """获取或创建全局任务存储实例。"""
    global _task_storage
    if _task_storage is None:
        _task_storage = TaskStorage()
    return _task_storage
