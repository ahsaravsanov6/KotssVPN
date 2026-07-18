"""
app/api/main.py — точка входа платформы (API).

Запуск (dev):  uvicorn app.api.main:app --host 0.0.0.0 --port 8090
Запуск (prod): за nginx/systemd, см. docs/DEPLOY.md (добавьте по вкусу).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routers import admin_servers, internal, subscription
from app.config import settings
from app.providers.registry import get_provider
from app.servers_config import PanelType

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger("vpn_platform.api")

app = FastAPI(title="VPN Platform API", docs_url=None, redoc_url=None, openapi_url=None)

app.include_router(subscription.router)
app.include_router(internal.router)
app.include_router(admin_servers.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Единая точка логирования непойманных исключений. Раньше в разных
    хендлерах бота/бэкенда это делалось россыпью try/except с одинаковым
    "⚠️ Произошла ошибка" — здесь это гарантированно попадает в лог с
    полным traceback независимо от того, где именно упал запрос.
    """
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Аккуратно закрываем постоянные httpx-сессии до всех известных панелей,
    чтобы не оставлять висящие соединения при перезапуске/деплое."""
    xui = get_provider(PanelType.XUI.value)
    aclose_all = getattr(xui, "aclose_all", None)
    if aclose_all:
        await aclose_all()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
