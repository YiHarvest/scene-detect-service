# 场景检测服务 API 接口文档

## 概述

场景检测服务是一个基于 PySceneDetect 和 FFmpeg 的视频场景检测与分割服务。该服务可以自动检测视频中的场景变化，并将视频分割成多个片段。

- **服务名称**: Scene Detection Service
- **版本**: 1.0.0
- **基础路径**: `http://localhost:28200`
- **交互式文档**: `http://localhost:28200/docs` (Swagger UI)
- **替代文档**: `http://localhost:28200/redoc` (ReDoc)

---

## 目录

- [健康检查接口](#健康检查接口)
  - [健康检查](#健康检查)
- [视频分割接口](#视频分割接口)
  - [上传并分割视频](#上传并分割视频)
  - [获取任务信息](#获取任务信息)
  - [下载分片](#下载分片)
  - [删除任务](#删除任务)
- [数据模型](#数据模型)
- [错误响应](#错误响应)
- [错误码说明](#错误码说明)

---

## 健康检查接口

### 健康检查

检查服务健康状态和依赖项可用性。

**请求**

```http
GET /health
```

**响应**

```json
{
  "status": "ok",
  "ffmpegAvailable": true,
  "ffprobeAvailable": true,
  "sceneDetectAvailable": true
}
```

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 服务状态，可选值：`ok`、`degraded` |
| `ffmpegAvailable` | boolean | FFmpeg 是否可用 |
| `ffprobeAvailable` | boolean | FFprobe 是否可用 |
| `sceneDetectAvailable` | boolean | PySceneDetect 是否可用 |

**状态码**

| 状态码 | 说明 |
|--------|------|
| 200 | 服务正常 |
| 503 | 关键依赖项不可用 |

---

## 视频分割接口

### 上传并分割视频

上传视频文件，检测场景并分割成片段。

**请求**

```http
POST /api/v1/videos/split
Content-Type: multipart/form-data
```

**请求参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 要分割的 MP4 视频文件 |

**请求示例**

```bash
curl -X POST "http://localhost:28200/api/v1/videos/split" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@video.mp4"
```

**响应示例**

```json
{
  "taskId": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "originalFilename": "video.mp4",
  "durationSeconds": 120.5,
  "sceneCount": 5,
  "segments": [
    {
      "index": 1,
      "startSeconds": 0.0,
      "endSeconds": 25.3,
      "durationSeconds": 25.3,
      "startFrame": 0,
      "endFrame": 759,
      "sizeBytes": 5242880,
      "filename": "segment-001.mp4",
      "downloadUrl": "/api/v1/videos/split/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6/segments/1"
    },
    {
      "index": 2,
      "startSeconds": 25.3,
      "endSeconds": 48.7,
      "durationSeconds": 23.4,
      "startFrame": 759,
      "endFrame": 1461,
      "sizeBytes": 4194304,
      "filename": "segment-002.mp4",
      "downloadUrl": "/api/v1/videos/split/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6/segments/2"
    }
  ]
}
```

**响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `taskId` | string | 任务 ID（32 位 UUID4 hex） |
| `originalFilename` | string | 原始文件名 |
| `durationSeconds` | number | 视频总时长（秒） |
| `sceneCount` | integer | 检测到的场景数量 |
| `segments` | array | 分片列表 |

**分片字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `index` | integer | 分片索引（从 1 开始） |
| `startSeconds` | number | 开始时间（秒） |
| `endSeconds` | number | 结束时间（秒） |
| `durationSeconds` | number | 分片时长（秒） |
| `startFrame` | integer | 开始帧号 |
| `endFrame` | integer | 结束帧号 |
| `sizeBytes` | integer | 文件大小（字节） |
| `filename` | string | 文件名 |
| `downloadUrl` | string | 下载路径 |

**状态码**

| 状态码 | 说明 |
|--------|------|
| 200 | 分割成功 |
| 400 | 请求验证失败 |
| 413 | 文件过大 |
| 415 | 不支持的媒体类型 |
| 500 | 场景检测或分割失败 |

---

### 获取任务信息

获取已完成分割任务的信息。

**请求**

```http
GET /api/v1/videos/split/{task_id}
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID（32 位 UUID4 hex） |

**请求示例**

```bash
curl -X GET "http://localhost:28200/api/v1/videos/split/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

**响应示例**

```json
{
  "taskId": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "originalFilename": "video.mp4",
  "durationSeconds": 120.5,
  "sceneCount": 5,
  "segments": [
    {
      "index": 1,
      "startSeconds": 0.0,
      "endSeconds": 25.3,
      "durationSeconds": 25.3,
      "startFrame": 0,
      "endFrame": 759,
      "sizeBytes": 5242880,
      "filename": "segment-001.mp4",
      "downloadUrl": "/api/v1/videos/split/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6/segments/1"
    }
  ]
}
```

**状态码**

| 状态码 | 说明 |
|--------|------|
| 200 | 获取成功 |
| 404 | 任务未找到 |

---

### 下载分片

下载指定的视频分片。

**请求**

```http
GET /api/v1/videos/split/{task_id}/segments/{segment_index}
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID（32 位 UUID4 hex） |
| `segment_index` | integer | 分片索引（从 1 开始） |

**请求示例**

```bash
curl -X GET "http://localhost:28200/api/v1/videos/split/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6/segments/1" \
  -o segment-001.mp4
```

**响应**

- Content-Type: `video/mp4`
- 响应体为视频文件二进制内容

**状态码**

| 状态码 | 说明 |
|--------|------|
| 200 | 下载成功 |
| 404 | 任务或分片未找到 |

---

### 删除任务

删除任务及其所有文件。

**请求**

```http
DELETE /api/v1/videos/split/{task_id}
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID（32 位 UUID4 hex） |

**请求示例**

```bash
curl -X DELETE "http://localhost:28200/api/v1/videos/split/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

**状态码**

| 状态码 | 说明 |
|--------|------|
| 204 | 删除成功（无内容） |

> **注意**: 此接口是幂等的，即使任务不存在也返回 204。

---

## 数据模型

### SplitVideoResponse

视频分割响应模型。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `taskId` | string | 是 | 任务 ID |
| `originalFilename` | string | 是 | 原始文件名 |
| `durationSeconds` | number | 是 | 视频总时长 |
| `sceneCount` | integer | 是 | 场景数量 |
| `segments` | SegmentResponse[] | 是 | 分片列表 |

### SegmentResponse

分片响应模型。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `index` | integer | 是 | 分片索引（≥1） |
| `startSeconds` | number | 是 | 开始时间（≥0） |
| `endSeconds` | number | 是 | 结束时间（>0） |
| `durationSeconds` | number | 是 | 分片时长 |
| `startFrame` | integer | 是 | 开始帧号 |
| `endFrame` | integer | 是 | 结束帧号 |
| `sizeBytes` | integer | 是 | 文件大小 |
| `filename` | string | 是 | 文件名 |
| `downloadUrl` | string | 是 | 下载路径 |

### HealthResponse

健康检查响应模型。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `status` | string | 是 | 服务状态 |
| `ffmpegAvailable` | boolean | 是 | FFmpeg 可用性 |
| `ffprobeAvailable` | boolean | 是 | FFprobe 可用性 |
| `sceneDetectAvailable` | boolean | 是 | PySceneDetect 可用性 |

---

## 错误响应

所有错误响应遵循统一格式：

```json
{
  "error": {
    "code": "error_code",
    "message": "错误描述信息",
    "details": null
  }
}
```

**错误响应字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `error.code` | string | 错误码 |
| `error.message` | string | 错误消息 |
| `error.details` | any | 详细信息（可选） |

---

## 错误码说明

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| `invalid_request` | 400 | 请求验证失败 |
| `unsupported_media_type` | 415 | 不支持的媒体类型（仅支持 MP4） |
| `file_too_large` | 413 | 文件大小超过限制（默认 200MB） |
| `invalid_video` | 400 | 无效的视频文件 |
| `ffmpeg_unavailable` | 503 | FFmpeg 不可用 |
| `ffprobe_unavailable` | 503 | FFprobe 不可用 |
| `scene_detection_failed` | 500 | 场景检测失败 |
| `video_split_failed` | 500 | 视频分割失败 |
| `segment_missing` | 404 | 分片文件缺失 |
| `task_not_found` | 404 | 任务未找到 |
| `internal_error` | 500 | 内部错误 |

---

## 配置参数

服务支持以下环境变量配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `HOST` | `0.0.0.0` | 服务监听地址 |
| `PORT` | `28200` | 服务监听端口 |
| `WORKSPACE_ROOT` | `./workspace` | 任务存储目录 |
| `MAX_UPLOAD_BYTES` | `209715200` | 最大上传大小（200MB） |
| `TASK_TTL_SECONDS` | `3600` | 任务过期时间（1小时） |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg 可执行文件路径 |
| `FFPROBE_PATH` | `ffprobe` | FFprobe 可执行文件路径 |

场景检测参数：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `SCENE_ADAPTIVE_THRESHOLD` | `3.0` | 自适应检测阈值 |
| `SCENE_MIN_LENGTH_SECONDS` | `0.8` | 最小场景长度（秒） |
| `SCENE_WINDOW_WIDTH` | `2` | 检测窗口宽度 |
| `SCENE_MIN_CONTENT_VALUE` | `15.0` | 最小内容值 |

---

## 使用示例

### Python 示例

```python
import requests

# 上传视频
with open("video.mp4", "rb") as f:
    response = requests.post(
        "http://localhost:28200/api/v1/videos/split",
        files={"file": f}
    )

result = response.json()
task_id = result["taskId"]
print(f"任务 ID: {task_id}")
print(f"检测到 {result['sceneCount']} 个场景")

# 下载第一个分片
segment_url = f"http://localhost:28200{result['segments'][0]['downloadUrl']}"
segment_response = requests.get(segment_url)
with open("segment-001.mp4", "wb") as f:
    f.write(segment_response.content)

# 删除任务
requests.delete(f"http://localhost:28200/api/v1/videos/split/{task_id}")
```

### JavaScript 示例

```javascript
const FormData = require('form-data');
const fs = require('fs');
const axios = require('axios');

async function splitVideo() {
  // 上传视频
  const form = new FormData();
  form.append('file', fs.createReadStream('video.mp4'));

  const response = await axios.post(
    'http://localhost:28200/api/v1/videos/split',
    form,
    { headers: form.getHeaders() }
  );

  const { taskId, sceneCount, segments } = response.data;
  console.log(`任务 ID: ${taskId}`);
  console.log(`检测到 ${sceneCount} 个场景`);

  // 下载分片
  for (const segment of segments) {
    const segmentUrl = `http://localhost:28200${segment.downloadUrl}`;
    const segmentData = await axios.get(segmentUrl, { responseType: 'stream' });
    segmentData.data.pipe(fs.createWriteStream(segment.filename));
  }

  // 删除任务
  await axios.delete(`http://localhost:28200/api/v1/videos/split/${taskId}`);
}

splitVideo();
```

---

## CORS 配置

服务默认允许所有来源的跨域请求：

- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods: *`
- `Access-Control-Allow-Headers: *`

---

## 版本信息

- **API 版本**: v1
- **服务版本**: 1.0.0
- **更新日期**: 2026-08-04