"""Pydantic 模型测试。"""

from app.schemas import Manifest


def test_manifest_populates_scene_count_for_legacy_data():
    """旧清单缺少 scene_count 时，应从 segments 计算。"""
    manifest = Manifest.model_validate(
        {
            "version": 1,
            "task_id": "a0eebc999c0b4ef8bb6d6bb9bd380a11",
            "original_filename": "test.mp4",
            "duration_seconds": 2.0,
            "segments": [
                {
                    "index": 1,
                    "start_seconds": 0.0,
                    "end_seconds": 2.0,
                    "size_bytes": 1024,
                    "filename": "segment_001.mp4",
                }
            ],
        }
    )

    assert manifest.scene_count == 1
    assert manifest.model_dump()["scene_count"] == 1
