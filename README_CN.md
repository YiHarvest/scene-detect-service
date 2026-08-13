# 视频场景检测服务

基于 PySceneDetect 和 FFmpeg 的视频场景检测与分割服务。

## 功能特性

- 上传 MP4 视频并检测自然场景变化
- 基于检测到的场景分割视频
- 下载单个分片文件
- 基于任务的处理流程，带有清单跟踪
- 自动清理过期任务

## 系统要求

- Python 3.10+
- uv
- FFmpeg
- ffprobe

### 安装 FFmpeg

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

## 安装步骤

```bash
cd /home/yqy/Projects/scene-detect-service
uv sync
cp .env.example .env
```

## 运行服务

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy
uv run main.py --reload
```

或使用自定义选项：
```bash
uv run main.py --host 0.0.0.0 --port 28200 --reload
```

或直接使用 uvicorn：
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 28200 --reload
```

服务将在 `http://127.0.0.1:28200` 启动

## API 文档

交互式 API 文档可通过以下地址访问：
- Swagger UI: `http://127.0.0.1:28200/docs`
- ReDoc: `http://127.0.0.1:28200/redoc`

## API 端点

### 健康检查

```bash
curl http://127.0.0.1:28200/health
```

### 分割视频

```bash
curl -X POST \
  http://127.0.0.1:28200/api/v1/videos/split \
  -F "file=@/absolute/path/to/video.mp4"
```

响应示例：
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

### 查询任务状态

```bash
curl http://127.0.0.1:28200/api/v1/videos/split/{task_id}
```

### 下载分片

```bash
curl -O http://127.0.0.1:28200/api/v1/videos/split/{task_id}/segments/{index}
```

### 删除任务

```bash
curl -X DELETE http://127.0.0.1:28200/api/v1/videos/split/{task_id}
```

## 配置

通过环境变量或 `.env` 文件配置：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| HOST | 0.0.0.0 | 服务绑定地址 |
| PORT | 28200 | 服务端口 |
| PUBLIC_BASE_URL | 未设置 | 用于生成切片绝对地址的公开 HTTP(S) 域名及可选基础路径 |
| WORKSPACE_ROOT | ./workspace | 工作目录 |
| FFMPEG_PATH | ffmpeg | FFmpeg 可执行文件路径 |
| FFPROBE_PATH | ffprobe | FFprobe 可执行文件路径 |
| MAX_UPLOAD_BYTES | 1073741824 | 最大上传文件大小（1GB） |
| TASK_TTL_SECONDS | 86400 | 任务保留时间（24小时） |
| DETECTOR_THRESHOLD | 27.0 | 场景检测阈值 |
| MIN_SCENE_SECONDS | 0.5 | 最小场景时长 |

## 项目结构

```
scene-detect-service/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # 配置管理
│   ├── errors.py            # 统一错误处理
│   ├── schemas.py           # Pydantic 模型
│   ├── api/
│   │   └── videos.py        # API 路由
│   └── services/
│       ├── task_storage.py      # 任务存储
│       ├── video_validator.py   # 视频验证
│       └── scene_splitter.py    # 场景分割
├── tests/
│   ├── test_health.py
│   └── test_scene_splitter.py
├── .env.example
├── pyproject.toml
├── README.md
└── README_CN.md
```

## 开发

### 运行测试

```bash
uv run pytest -v
```

### 代码质量检查

```bash
uv run ruff check .
```

## 许可证

MIT License
