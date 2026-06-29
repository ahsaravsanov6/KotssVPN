"""
analytics/web.py — веб-панель аналитики (FastAPI).

import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings, _GENERATED_TOKEN_WARNING
from storage import db, init_db, utcnow_naive

logger = logging.getLogger("analytics.web")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="VPN Bot Analytics", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

basic_auth = HTTPBasic(auto_error=False)


# ── Слой 1: секретный токен в URL ────────────────────────────────────────────

def require_token(token: Optional[str] = Query(default=None)) -> None:
    if not settings.ADMIN_PASSWORD:
        # Если пароль вообще не настроен — не пускаем никого и явно
        # объясняем это только в логах сервера (не в ответе), чтобы
        # не выдавать конфигурацию случайному запросу.
        logger.error("ADMIN_PASSWORD не задан в .env — панель заблокирована для всех запросов")
        raise HTTPException(status_code=404)

    if not token or not secrets.compare_digest(token, settings.SECRET_TOKEN):
        # 404, а не 401/403 — намеренно не подтверждаем существование ресурса.
        raise HTTPException(status_code=404)


# ── Слой 2: HTTP Basic Auth ──────────────────────────────────────────────────

def require_login(credentials: Optional[HTTPBasicCredentials] = Depends(basic_auth)) -> str:
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    user_ok = secrets.compare_digest(credentials.username, settings.ADMIN_USERNAME)
    pass_ok = secrets.compare_digest(credentials.password, settings.ADMIN_PASSWORD)

    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


def guarded(_: None = Depends(require_token), user: str = Depends(require_login)) -> str:
    return user


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    logger.info("=" * 60)
    logger.info("Analytics web panel starting on %s:%d", settings.WEB_HOST, settings.WEB_PORT)
    if _GENERATED_TOKEN_WARNING:
        logger.warning(
            "SECRET_TOKEN не задан в .env! Временный токен на эту сессию: %s",
            settings.SECRET_TOKEN,
        )
    if not settings.ADMIN_PASSWORD:
        logger.error("ADMIN_PASSWORD не задан — панель НЕДОСТУПНА, пока вы не зададите его в .env")
    logger.info("URL: http://<host>:%d/?token=%s", settings.WEB_PORT, settings.SECRET_TOKEN)
    logger.info("=" * 60)


# ── Страница дашборда ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(guarded)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"token": settings.SECRET_TOKEN},
    )


# ── JSON API для графиков ────────────────────────────────────────────────────

def _parse_range(range_key: str) -> datetime:
    now = utcnow_naive()
    return {
        "24h": now - timedelta(hours=24),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }.get(range_key, now - timedelta(days=7))


@app.get("/api/overview")
async def api_overview(_: str = Depends(guarded)) -> JSONResponse:
    """Текущие ключевые цифры (последний снапшот каждого типа)."""
    with db() as conn:
        latest_users = conn.execute(
            "SELECT * FROM snapshot_users ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        latest_server = conn.execute(
            "SELECT * FROM snapshot_server ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        online_now = conn.execute(
            "SELECT COUNT(*) c FROM snapshot_client_traffic "
            "WHERE ts = (SELECT MAX(ts) FROM snapshot_client_traffic) AND online = 1"
        ).fetchone()

    return JSONResponse({
        "users": dict(latest_users) if latest_users else None,
        "server": dict(latest_server) if latest_server else None,
        "online_now": online_now["c"] if online_now else 0,
    })


@app.get("/api/users-timeseries")
async def api_users_timeseries(range: str = "7d", _: str = Depends(guarded)) -> JSONResponse:
    since = _parse_range(range).isoformat()
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, total_users, active_subscriptions, expired_subscriptions, "
            "no_subscription, total_devices FROM snapshot_users "
            "WHERE ts >= ? ORDER BY ts ASC",
            (since,),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/server-timeseries")
async def api_server_timeseries(range: str = "24h", _: str = Depends(guarded)) -> JSONResponse:
    since = _parse_range(range).isoformat()
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, cpu_percent, mem_current, mem_total, disk_current, disk_total, "
            "load1, net_io_up, net_io_down, online_clients, tcp_count, udp_count "
            "FROM snapshot_server WHERE ts >= ? ORDER BY ts ASC",
            (since,),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/traffic-top-clients")
async def api_traffic_top_clients(range: str = "7d", limit: int = 10, _: str = Depends(guarded)) -> JSONResponse:
    """
    Топ клиентов по трафику за период: разность (последний снапшот в периоде
    минус первый снапшот в периоде) для каждого email, т.к. up/down в 3X-UI
    накопительные счётчики.
    """
    since = _parse_range(range).isoformat()
    with db() as conn:
        rows = conn.execute(
            """
            WITH bounds AS (
                SELECT email, telegram_id,
                       MIN(ts) as first_ts, MAX(ts) as last_ts
                FROM snapshot_client_traffic
                WHERE ts >= ?
                GROUP BY email
            )
            SELECT b.email, b.telegram_id,
                   (last.up - first.up) as delta_up,
                   (last.down - first.down) as delta_down
            FROM bounds b
            JOIN snapshot_client_traffic first ON first.email = b.email AND first.ts = b.first_ts
            JOIN snapshot_client_traffic last ON last.email = b.email AND last.ts = b.last_ts
            ORDER BY (delta_up + delta_down) DESC
            LIMIT ?
            """,
            (since, limit),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/traffic-total-timeseries")
async def api_traffic_total_timeseries(range: str = "7d", _: str = Depends(guarded)) -> JSONResponse:
    """Суммарный трафик всех клиентов по снапшотам (для графика общей нагрузки)."""
    since = _parse_range(range).isoformat()
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, SUM(up) as total_up, SUM(down) as total_down, "
            "SUM(online) as online_count FROM snapshot_client_traffic "
            "WHERE ts >= ? GROUP BY ts ORDER BY ts ASC",
            (since,),
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/referrals")
async def api_referrals(_: str = Depends(guarded)) -> JSONResponse:
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, total_referrals, bonus_granted_referrals FROM snapshot_users "
            "ORDER BY ts ASC"
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


@app.get("/api/payments")
async def api_payments(range: str = "30d", _: str = Depends(guarded)) -> JSONResponse:
    """
    Платежи за период, сгруппированные по дню — для графика "выручка по дням"
    и итоговой сводки (всего оплат, сумма, разбивка по способу/типу).
    Если таблица payment_events пуста (бот ещё не обновлён) — отдаёт
    пустые списки, дашборд покажет "нет данных" без ошибок.
    """
    since = _parse_range(range).isoformat()
    with db() as conn:
        by_day = conn.execute(
            """
            SELECT substr(ts, 1, 10) as day,
                   COUNT(*) as count,
                   SUM(price) as total_price
            FROM payment_events
            WHERE ts >= ?
            GROUP BY day
            ORDER BY day ASC
            """,
            (since,),
        ).fetchall()

        by_method = conn.execute(
            """
            SELECT method, COUNT(*) as count, SUM(price) as total_price
            FROM payment_events
            WHERE ts >= ?
            GROUP BY method
            ORDER BY total_price DESC
            """,
            (since,),
        ).fetchall()

        totals = conn.execute(
            "SELECT COUNT(*) as count, SUM(price) as total_price FROM payment_events WHERE ts >= ?",
            (since,),
        ).fetchone()

    return JSONResponse({
        "by_day": [dict(r) for r in by_day],
        "by_method": [dict(r) for r in by_method],
        "total_count": totals["count"] or 0,
        "total_price": totals["total_price"] or 0,
    })


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Без авторизации — для мониторинга процесса (не отдаёт никаких данных)."""
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.WEB_HOST, port=settings.WEB_PORT)
