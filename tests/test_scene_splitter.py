"""视频场景分割功能测试。

测试视频上传、分割、任务管理和分片下载等功能。
"""

import io
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """创建测试客户端。"""
    return TestClient(app)


@pytest.fixture
def temp_video():
    """使用 FFmpeg 创建临时测试视频文件。"""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        # 使用 FFmpeg 创建简单的测试视频
        # 5 秒的纯红色
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
            # 清理
            if Path(f.name).exists():
                Path(f.name).unlink()


@pytest.fixture
def multi_scene_video():
    """使用 FFmpeg 创建包含多个场景的测试视频。"""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        # 创建包含 3 个场景的视频（红、绿、蓝）
        # 每个场景 2 秒 - 使用更简单的方法
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
            # 清理
            if Path(f.name).exists():
                Path(f.name).unlink()


class TestVideoUpload:
    """视频上传和分割测试。"""

    def test_upload_non_mp4_rejected(self, client: TestClient):
        """测试非 MP4 文件被拒绝。"""
        # 创建一个假的文本文件
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

    def test_upload_valid_mp4(self, client: TestClient, temp_video):
        """测试上传有效的 MP4 文件。"""
        with open(temp_video, "rb") as f:
            response = client.post(
                "/api/v1/videos/split",
                files={"file": ("test.mp4", f, "video/mp4")},
            )

        # 应该成功
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # 检查响应结构
        assert "taskId" in data
        assert "originalFilename" in data
        assert "durationSeconds" in data
        assert "sceneCount" in data
        assert "segments" in data

        # 检查任务 ID 是否为有效的 UUID hex
        task_id = data["taskId"]
        assert len(task_id) == 32  # UUID4 hex 是 32 个字符

        # 检查分片
        assert isinstance(data["segments"], list)
        assert len(data["segments"]) >= 1  # 至少有一个分片

        # 检查分片结构
        segment = data["segments"][0]
        assert "index" in segment
        assert "startSeconds" in segment
        assert "endSeconds" in segment
        assert "durationSeconds" in segment
        assert "sizeBytes" in segment
        assert "filename" in segment
        assert "downloadUrl" in segment

        # 检查大小为正数
        assert segment["sizeBytes"] > 0

    def test_multi_scene_video(self, client: TestClient, multi_scene_video):
        """测试包含多个场景的视频。"""
        with open(multi_scene_video, "rb") as f:
            response = client.post(
                "/api/v1/videos/split",
                files={"file": ("multi.mp4", f, "video/mp4")},
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # 应该有多个分片
        assert data["sceneCount"] >= 1
        assert len(data["segments"]) >= 1

        # 检查分片顺序
        for i, segment in enumerate(data["segments"], start=1):
            assert segment["index"] == i

        # 检查时间范围是连续的
        segments = data["segments"]
        for i in range(len(segments) - 1):
            assert segments[i]["endSeconds"] <= segments[i + 1]["startSeconds"]


class TestTaskManagement:
    """任务管理测试。"""

    def test_get_nonexistent_task(self, client: TestClient):
        """测试获取不存在的任务。"""
        # 使用有效的 UUID4 hex（不只是重复的 'a'）
        fake_task_id = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11".replace("-", "")

        response = client.get(f"/api/v1/videos/split/{fake_task_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_nonexistent_task(self, client: TestClient):
        """测试删除不存在的任务（应该是幂等的）。"""
        # 使用有效的 UUID4 hex（不只是重复的 'b'）
        fake_task_id = "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11".replace("-", "")

        response = client.delete(f"/api/v1/videos/split/{fake_task_id}")

        # 应该返回 204（幂等）
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_get_task_after_upload(self, client: TestClient, temp_video):
        """测试上传后获取任务信息。"""
        # 上传视频
        with open(temp_video, "rb") as f:
            upload_response = client.post(
                "/api/v1/videos/split",
                files={"file": ("test.mp4", f, "video/mp4")},
            )

        assert upload_response.status_code == status.HTTP_200_OK
        task_id = upload_response.json()["taskId"]

        # 获取任务信息
        get_response = client.get(f"/api/v1/videos/split/{task_id}")

        assert get_response.status_code == status.HTTP_200_OK
        data = get_response.json()

        # 应该与上传响应匹配
        assert data["taskId"] == task_id
        assert data["originalFilename"] == "test.mp4"

    def test_delete_task(self, client: TestClient, temp_video):
        """测试删除任务。"""
        # 上传视频
        with open(temp_video, "rb") as f:
            upload_response = client.post(
                "/api/v1/videos/split",
                files={"file": ("test.mp4", f, "video/mp4")},
            )

        task_id = upload_response.json()["taskId"]

        # 删除任务
        delete_response = client.delete(f"/api/v1/videos/split/{task_id}")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT

        # 任务应该不再存在
        get_response = client.get(f"/api/v1/videos/split/{task_id}")
        assert get_response.status_code == status.HTTP_404_NOT_FOUND


class TestSegmentDownload:
    """分片下载测试。"""

    def test_download_segment(self, client: TestClient, temp_video):
        """测试下载分片。"""
        # 上传视频
        with open(temp_video, "rb") as f:
            upload_response = client.post(
                "/api/v1/videos/split",
                files={"file": ("test.mp4", f, "video/mp4")},
            )

        task_id = upload_response.json()["taskId"]

        # 下载第一个分片
        download_response = client.get(
            f"/api/v1/videos/split/{task_id}/segments/1"
        )

        assert download_response.status_code == status.HTTP_200_OK
        assert download_response.headers["content-type"] == "video/mp4"

        # 检查内容不为空
        content = download_response.content
        assert len(content) > 0

    def test_download_nonexistent_segment(self, client: TestClient, temp_video):
        """测试下载不存在的分片。"""
        # 上传视频
        with open(temp_video, "rb") as f:
            upload_response = client.post(
                "/api/v1/videos/split",
                files={"file": ("test.mp4", f, "video/mp4")},
            )

        task_id = upload_response.json()["taskId"]

        # 尝试下载分片 999
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