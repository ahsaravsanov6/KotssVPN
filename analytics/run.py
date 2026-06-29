"""
analytics/run.py — запускает коллектор и веб-панель ВМЕСТЕ, одним процессом.

Удобно для простого деплоя (один systemd-юнит, один `python -m analytics.run`).
Если хотите запускать их раздельно (например, чтобы веб не падал при
проблемах с коллектором) — используйте `python -m analytics.collector`
и `python -m analytics.web` в двух отдельных процессах/юнитах, см. README.md.
"""

import asyncio
import logging

import uvicorn

from collector import main as collector_main
from config import settings
from web import app

logger = logging.getLogger("analytics.run")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")


async def run_web() -> None:
    config = uvicorn.Config(app, host=settings.WEB_HOST, port=settings.WEB_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    await asyncio.gather(
        collector_main(),
        run_web(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
