#!/usr/bin/env python3
"""场景检测服务入口点。"""

import argparse
import logging

import uvicorn

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """主入口点。"""
    parser = argparse.ArgumentParser(description="场景检测服务")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="绑定地址（默认：0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=28200,
        help="绑定端口（默认：28200）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用开发模式自动重载",
    )
    # 并发由进程内任务队列（QUEUE_WORKER_COUNT）控制，uvicorn 必须单进程。
    # 多进程会导致每个进程各有一个队列、重复处理同一任务。
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="工作进程数（必须为 1；并发由任务队列 QUEUE_WORKER_COUNT 控制）",
    )

    args = parser.parse_args()

    logger.info(f"正在启动场景检测服务，地址：{args.host}:{args.port}")
    if args.reload:
        logger.info("已启用自动重载")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,  # 自动重载与多工作进程不兼容
    )


if __name__ == "__main__":
    main()
