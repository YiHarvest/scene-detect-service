# Scene Detection Service

Video scene detection and splitting service using PySceneDetect and FFmpeg.

[中文文档](README_CN.md)

## Features

- Upload MP4 videos and detect natural scene changes
- Split videos into segments based on detected scenes
- Download individual segments
- Task-based processing with manifest tracking
- Automatic cleanup of expired tasks

## Requirements

- Python 3.10+
- uv
- FFmpeg
- ffprobe

### Installing FFmpeg

**Arch Linux:**
```bash
sudo pacman -S ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

## Installation

```bash
cd /home/yqy/Projects/scene-detect-service
uv sync
cp .env.example .env
```

## Running the Service

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy
uv run main.py --reload
```

Or with custom options:
```bash
uv run main.py --host 0.0.0.0 --port 28200 --reload
```

Or with uvicorn directly:
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 28200 --reload
```

The service will be available at `http://127.0.0.1:28200`

## API Documentation

Interactive API documentation is available at:
- Swagger UI: `http://127.0.0.1:28200/docs`
- ReDoc: `http://127.0.0.1:28200/redoc`

## API Endpoints

### Health Check

```bash
curl http://127.0.0.1:28200/health
```

### Split Video

```bash
curl -X POST \
  http://127.0.0.1:28200/api/v1/videos/split \
  -F "file=@/absolute/path/to/video.mp4"
```

Response:
```json
{
  "taskId": "6fc24bee8df44ff8a67047d69c61be01",
  "originalFilename": "video.mp4",
  "durationSeconds": 60.2,
  "sceneCount": 3,
  "segments": [
    {
      "index": 1,
      "startSeconds": 0.0,
      "endSeconds": 8.42,
      "durationSeconds": 8.42,
      "startFrame": 0,
      "endFrame": 252,
      "sizeBytes": 4562132,
      "filename": "segment-001.mp4",
      "downloadUrl": "/api/v1/videos/split/6fc24bee8df44ff8a67047d69c61be01/segments/1",
      "directVideoUrl": "https://video.example.com/api/v1/videos/split/6fc24bee8df44ff8a67047d69c61be01/segments/1"
    }
  ]
}
```

### Download Segment

```bash
curl -L \
  http://127.0.0.1:28200/api/v1/videos/split/{taskId}/segments/1 \
  -o segment-001.mp4
```

### Get Task Information

```bash
curl http://127.0.0.1:28200/api/v1/videos/split/{taskId}
```

### Delete Task

```bash
curl -X DELETE \
  http://127.0.0.1:28200/api/v1/videos/split/{taskId}
```

## Testing

Run tests:
```bash
uv run pytest
```

Run with coverage:
```bash
uv run pytest --cov=app
```

## Code Quality

Run linter:
```bash
uv run ruff check .
```

Format code:
```bash
uv run ruff format .
```

## Configuration

Environment variables can be set in `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server host address |
| `PORT` | `28200` | Server port |
| `PUBLIC_BASE_URL` | unset | Public HTTP(S) origin and optional base path used for absolute segment URLs |
| `WORKSPACE_ROOT` | `./workspace` | Directory for task storage |
| `MAX_UPLOAD_BYTES` | `209715200` | Maximum upload size (200 MB) |
| `TASK_TTL_SECONDS` | `3600` | Task expiration time (1 hour) |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg executable path |
| `FFPROBE_PATH` | `ffprobe` | FFprobe executable path |
| `SCENE_ADAPTIVE_THRESHOLD` | `3.0` | Scene detection threshold |
| `SCENE_MIN_LENGTH_SECONDS` | `0.8` | Minimum scene length |
| `SCENE_WINDOW_WIDTH` | `2` | Detection window width |
| `SCENE_MIN_CONTENT_VALUE` | `15.0` | Minimum content value |

## Project Structure

```
scene-detect-service/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration management
│   ├── errors.py            # Error handling
│   ├── schemas.py           # Pydantic models
│   ├── api/
│   │   ├── __init__.py
│   │   └── videos.py        # Video API routes
│   └── services/
│       ├── __init__.py
│       ├── scene_splitter.py    # Scene detection logic
│       ├── task_storage.py      # Task management
│       └── video_validator.py   # Video validation
├── tests/
│   ├── __init__.py
│   ├── test_health.py
│   └── test_scene_splitter.py
├── pyproject.toml
├── .env.example
└── README.md
```

## Error Handling

All errors follow a unified format:

```json
{
  "error": {
    "code": "invalid_video",
    "message": "Unable to read video file",
    "details": null
  }
}
```

Error codes:
- `invalid_request` - Invalid request parameters
- `unsupported_media_type` - Unsupported file type
- `file_too_large` - File exceeds size limit
- `invalid_video` - Invalid or corrupted video
- `ffmpeg_unavailable` - FFmpeg not found
- `ffprobe_unavailable` - FFprobe not found
- `scene_detection_failed` - Scene detection error
- `video_split_failed` - Video splitting error
- `segment_missing` - Segment not found
- `task_not_found` - Task not found
- `internal_error` - Internal server error

## License

MIT
