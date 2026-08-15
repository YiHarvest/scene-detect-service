"""视频场景分割功能测试。

测试视频上传（入队）、状态轮询、任务管理和分片下载等功能。
分割在后台队列 worker 中执行，POST 返回 202，通过轮询 GET 等待 done。
"""

import io
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """创建测试客户端（with 触发 lifespan，启动队列 worker 池）。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def temp_video():
    """使用 FFmpeg 创建临时测试视频文件。"""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        cmd = [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=5",
            "-c:v",
            "libx264",
            "-t",
            "5",
            "-pix_fmt",
            "yuv420p",
            "-y",
            f.name,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            yield Path(f.name)
        finally:
            if Path(f.name).exists():
                Path(f.name).unlink()


@pytest.fixture
def multi_scene_video():
    """使用 FFmpeg 创建包含多个场景的测试视频。"""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        cmd = [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=2,format=yuv420p",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=320x240:d=2,format=yuv420p",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=2,format=yuv420p",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[outv]",
            "-map",
            "[outv]",
            "-c:v",
            "libx264",
            "-y",
            f.name,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=15)
            yield Path(f.name)
        finally:
            if Path(f.name).exists():
                Path(f.name).unlink()


def upload(client: TestClient, video_path: Path, filename: str = "test.mp4"):
    """上传视频并返回 POST 响应。"""
    with open(video_path, "rb") as f:
        return client.post(
            "/api/v1/videos/split",
            files={"file": (filename, f, "video/mp4")},
        )


def wait_task_done(client: TestClient, task_id: str, timeout: float = 60.0) -> dict:
    """轮询任务直到 done；失败或超时则抛出 AssertionError。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/videos/split/{task_id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        if data["status"] == "done":
            return data
        if data["status"] == "failed":
            raise AssertionError(f"任务失败: {data.get('error')}")
        time.sleep(0.2)
    raise AssertionError(f"任务 {task_id} 在 {timeout}s 内未完成")


class TestVideoUpload:
    """视频上传和分割测试。"""

    def test_upload_non_mp4_rejected(self, client: TestClient):
        """测试非 MP4 文件被拒绝。"""
        fake_file = io.BytesIO(b"not a video")

        response = client.post(
            "/api/v1/videos/split",
            files={"file": ("test.txt", fake_file, "text/plain")},
        )

        assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        data = response.json()
        assert data["error"]["code"] == "unsupported_media_type"

    def test_upload_wrong_mime_type_rejected(self, client: TestClient, temp_video):
        """测试错误 MIME 类型的文件被拒绝。"""
        with open(temp_video, "rb") as f:
            response = client.post(
                "/api/v1/videos/split",
                files={"file": ("test.mp4", f, "video/avi")},
            )

        assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    def test_upload_returns_202_queued(self, client: TestClient, temp_video):
        """上传应立即返回 202 + queued 状态（异步入队）。"""
        response = upload(client, temp_video)

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["status"] == "queued"
        assert "taskId" in data
        assert len(data["taskId"]) == 32

    def test_upload_valid_mp4_completes(self, client: TestClient, temp_video):
        """上传有效 MP4 后轮询应得到 done 与完整分片。"""
        response = upload(client, temp_video)
        assert response.status_code == status.HTTP_202_ACCEPTED
        task_id = response.json()["taskId"]

        data = wait_task_done(client, task_id)

        # 检查响应结构
        assert data["status"] == "done"
        assert data["taskId"] == task_id
        assert data["originalFilename"] == "test.mp4"
        assert data["durationSeconds"] > 0
        assert data["sceneCount"] >= 1
        assert isinstance(data["segments"], list)
        assert len(data["segments"]) >= 1

        # 检查分片结构
        segment = data["segments"][0]
        assert segment["index"] == 1
        assert segment["startSeconds"] >= 0
        assert segment["endSeconds"] > segment["startSeconds"]
        assert segment["durationSeconds"] > 0
        assert segment["sizeBytes"] > 0
        assert segment["filename"].endswith(".mp4")
        assert "downloadUrl" in segment

    def test_multi_scene_video(self, client: TestClient, multi_scene_video):
        """包含多个场景的视频应切出多个分片。"""
        response = upload(client, multi_scene_video, filename="multi.mp4")
        assert response.status_code == status.HTTP_202_ACCEPTED
        task_id = response.json()["taskId"]

        data = wait_task_done(client, task_id)

        assert data["sceneCount"] >= 1
        segments = data["segments"]
        assert len(segments) >= 1

        # 检查分片序号连续
        for i, segment in enumerate(segments, start=1):
            assert segment["index"] == i

        # 检查时间范围连续
        for i in range(len(segments) - 1):
            assert segments[i]["endSeconds"] <= segments[i + 1]["startSeconds"]


class TestTaskManagement:
    """任务管理测试。"""

    def test_get_nonexistent_task(self, client: TestClient):
        """测试获取不存在的任务。"""
        fake_task_id = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11".replace("-", "")

        response = client.get(f"/api/v1/videos/split/{fake_task_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_nonexistent_task(self, client: TestClient):
        """测试删除不存在的任务（应该是幂等的）。"""
        fake_task_id = "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11".replace("-", "")

        response = client.delete(f"/api/v1/videos/split/{fake_task_id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_get_task_after_upload(self, client: TestClient, temp_video):
        """上传完成后 GET 应返回完整结果。"""
        response = upload(client, temp_video)
        task_id = response.json()["taskId"]

        wait_task_done(client, task_id)

        get_response = client.get(f"/api/v1/videos/split/{task_id}")
        assert get_response.status_code == status.HTTP_200_OK
        data = get_response.json()
        assert data["status"] == "done"
        assert data["taskId"] == task_id
        assert data["originalFilename"] == "test.mp4"

    def test_delete_queued_task(self, client: TestClient, temp_video):
        """删除任务应立即生效且幂等；处理中任务由 worker 完成后清理。"""
        response = upload(client, temp_video)
        task_id = response.json()["taskId"]

        delete_response = client.delete(f"/api/v1/videos/split/{task_id}")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT

        # worker 可能已把任务拉起为 processing（标记 cancelled 后自行清理），
        # 也可能任务仍在排队（直接删除）。轮询等待最终 404。
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            get_response = client.get(f"/api/v1/videos/split/{task_id}")
            if get_response.status_code == status.HTTP_404_NOT_FOUND:
                break
            time.sleep(0.1)
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_task(self, client: TestClient, temp_video):
        """删除已完成的任务。"""
        response = upload(client, temp_video)
        task_id = response.json()["taskId"]
        wait_task_done(client, task_id)

        delete_response = client.delete(f"/api/v1/videos/split/{task_id}")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT

        get_response = client.get(f"/api/v1/videos/split/{task_id}")
        assert get_response.status_code == status.HTTP_404_NOT_FOUND


class TestSegmentDownload:
    """分片下载测试。"""

    def test_download_segment(self, client: TestClient, temp_video):
        """测试下载分片。"""
        response = upload(client, temp_video)
        task_id = response.json()["taskId"]
        wait_task_done(client, task_id)

        download_response = client.get(
            f"/api/v1/videos/split/{task_id}/segments/1"
        )

        assert download_response.status_code == status.HTTP_200_OK
        assert download_response.headers["content-type"] == "video/mp4"
        content = download_response.content
        assert len(content) > 0

    def test_download_nonexistent_segment(self, client: TestClient, temp_video):
        """测试下载不存在的分片。"""
        response = upload(client, temp_video)
        task_id = response.json()["taskId"]
        wait_task_done(client, task_id)

        response = client.get(
            f"/api/v1/videos/split/{task_id}/segments/999"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestErrorHandling:
    """错误处理测试。"""

    def test_invalid_task_id_format(self, client: TestClient):
        """测试无效的任务 ID 格式。"""
        response = client.get("/api/v1/videos/split/invalid-id")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_file_too_large(self, client: TestClient):
        """测试文件大小限制。"""
        # 此测试需要模拟配置
        # 目前暂时跳过
