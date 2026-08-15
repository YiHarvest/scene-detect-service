"""测试配置。

在导入 app 之前把 WORKSPACE_ROOT 指向临时目录，避免测试污染真实工作区；
降低 worker 数让测试环境更轻。
"""

import os
import tempfile

import pytest

os.environ["WORKSPACE_ROOT"] = tempfile.mkdtemp(prefix="scene-test-")
os.environ["QUEUE_WORKER_COUNT"] = "2"


@pytest.fixture(autouse=True)
def reset_job_queue():
    """每个测试前重置全局 JobQueue 单例。

    asyncio.Queue 会绑定创建它的第一个事件循环，而每个 TestClient 启动
    自己的 portal 循环；单例跨测试复用会导致 worker 报 "bound to a
    different event loop" 并死循环。生产环境单进程单 lifespan 无此问题。
    """
    import app.services.job_queue as job_queue_module

    job_queue_module._job_queue = None
    yield
    job_queue_module._job_queue = None

