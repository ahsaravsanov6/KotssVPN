"""
analytics/collector.py — фоновый сборщик метрик.

Раз в settings.COLLECT_INTERVAL_SECONDS (по умолчанию 15 минут):
  1. читает БД бота (read-only) — пользователи/подписки/устройства/рефералка;
  2. дёргает 3X-UI — статус сервера (CPU/RAM/диск/сеть) и трафик по клиентам;
  3. матчит трафик клиентов с telegram_id через email (формат
     user_{telegram_id}_dev{device_id}, см. xui_service.py бота);
  4. пишет снапшоты в analytics.db.

Любая ошибка на любом из шагов логируется и НЕ прерывает цикл — следующий
тик просто попробует снова. Если 3X-UI недоступна, снапшот пользователей
из БД бота всё равно сохраняется.

Запуск:
    python -m analytics.collector
"""

import asyncio
import logging
import logging.config

from bot_db_reader import read_bot_snapshot
from config import settings, _GENERATED_TOKEN_WARNING
from storage import db, init_db, purge_old_data, utcnow_naive
from xui_client import xui_analytics_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("analytics.collector")


async def collect_once() -> None:
    ts = utcnow_naive().isoformat()

    # ── 1. Снимок БД бота ────────────────────────────────────────────────────
    email_to_user: dict = {}
    try:
        bot_data = read_bot_snapshot()
        email_to_user = bot_data.pop("email_to_user")

        with db() as conn:
            conn.execute(
                """
                INSERT INTO snapshot_users
                    (ts, total_users, active_subscriptions, expired_subscriptions,
                     no_subscription, total_devices, devices_with_vpn_key,
                     total_referrals, bonus_granted_referrals)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_data["ts"],
                    bot_data["total_users"],
                    bot_data["active_subscriptions"],
                    bot_data["expired_subscriptions"],
                    bot_data["no_subscription"],
                    bot_data["total_devices"],
                    bot_data["devices_with_vpn_key"],
                    bot_data["total_referrals"],
                    bot_data["bonus_granted_referrals"],
                ),
            )
        logger.info(
            "users snapshot: total=%d active=%d expired=%d devices=%d",
            bot_data["total_users"], bot_data["active_subscriptions"],
            bot_data["expired_subscriptions"], bot_data["total_devices"],
        )
    except Exception as exc:
        logger.error("Не удалось снять снапшот БД бота: %s", exc, exc_info=True)

    # ── 2. Статус сервера 3X-UI ──────────────────────────────────────────────
    try:
        status = await xui_analytics_client.get_server_status()
        if status:
            mem = status.get("mem") or {}
            disk = status.get("disk") or {}
            net_io = status.get("netIO") or {}
            # У этой панели netTraffic (накопительный счётчик с момента старта)
            # не отдаётся — есть только netIO (мгновенная скорость). Поля
            # net_traffic_sent/recv в БД останутся NULL, это ожидаемо.
            net_traffic = status.get("netTraffic") or {}
            # load — объект {load1, load5, load15}, а не массив [l1, l5, l15]
            # (отличается от схемы, которую отдают другие форки 3X-UI).
            load = status.get("load") or {}
            xray = status.get("xray") or {}

            online_count = 0
            try:
                clients_now = await xui_analytics_client.list_clients_traffic()
                online_count = sum(1 for c in clients_now if c["online"])
            except Exception:
                pass

            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO snapshot_server
                        (ts, cpu_percent, cpu_cores, mem_current, mem_total,
                         disk_current, disk_total, load1, load5, load15,
                         tcp_count, udp_count, net_io_up, net_io_down,
                         net_traffic_sent, net_traffic_recv, uptime_seconds,
                         xray_state, xray_version, online_clients)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ts,
                        status.get("cpu"),
                        status.get("cpuCores"),  # отсутствует у этой панели -> NULL, это ОК
                        mem.get("current"),
                        mem.get("total"),
                        disk.get("current"),
                        disk.get("total"),
                        load.get("load1"),
                        load.get("load5"),
                        load.get("load15"),
                        status.get("tcpCount"),
                        status.get("udpCount"),  # отсутствует у этой панели -> NULL, это ОК
                        net_io.get("up"),
                        net_io.get("down"),
                        net_traffic.get("sent"),  # отсутствует у этой панели -> NULL, это ОК
                        net_traffic.get("recv"),
                        status.get("uptime"),     # отсутствует у этой панели -> NULL, это ОК
                        xray.get("state"),
                        xray.get("version"),
                        online_count,
                    ),
                )
            logger.info(
                "server snapshot: cpu=%.1f%% mem=%s/%s online_clients=%d",
                status.get("cpu") or 0.0, mem.get("current"), mem.get("total"), online_count,
            )
        else:
            logger.warning("3X-UI server status не вернул данных — снапшот сервера пропущен")
    except Exception as exc:
        logger.error("Ошибка сбора статуса сервера 3X-UI: %s", exc, exc_info=True)

    # ── 3. Трафик клиентов 3X-UI (с матчингом telegram_id через email) ──────
    try:
        clients = await xui_analytics_client.list_clients_traffic()
        if clients:
            with db() as conn:
                for c in clients:
                    user_info = email_to_user.get(c["email"], {})
                    conn.execute(
                        """
                        INSERT INTO snapshot_client_traffic
                            (ts, email, telegram_id, up, down, enable, online)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ts,
                            c["email"],
                            user_info.get("telegram_id"),
                            c["up"],
                            c["down"],
                            int(c["enable"]),
                            int(c["online"]),
                        ),
                    )
            logger.info("client traffic snapshot: %d клиентов", len(clients))
        else:
            logger.warning("3X-UI не вернула ни одного клиента — снапшот трафика пропущен")
    except Exception as exc:
        logger.error("Ошибка сбора трафика клиентов 3X-UI: %s", exc, exc_info=True)

    # ── 4. Чистка старых данных ──────────────────────────────────────────────
    try:
        purge_old_data(settings.RETENTION_DAYS)
    except Exception as exc:
        logger.error("Ошибка очистки старых снапшотов: %s", exc)


async def main() -> None:
    init_db()
    logger.info("=" * 60)
    logger.info("Analytics collector starting...")
    logger.info("Bot DB (read-only): %s", settings.BOT_DB_PATH)
    logger.info("Analytics DB:       %s", settings.ANALYTICS_DB_PATH)
    logger.info("Interval:           %d сек", settings.COLLECT_INTERVAL_SECONDS)
    if _GENERATED_TOKEN_WARNING:
        logger.warning(
            "SECRET_TOKEN не задан в .env — сгенерирован временный токен: %s "
            "(добавьте его в .env как SECRET_TOKEN=..., иначе он изменится при перезапуске)",
            settings.SECRET_TOKEN,
        )
    logger.info("=" * 60)

    while True:
        started = utcnow_naive()
        await collect_once()
        elapsed = (utcnow_naive() - started).total_seconds()
        sleep_for = max(5.0, settings.COLLECT_INTERVAL_SECONDS - elapsed)
        logger.info("Цикл сбора занял %.1f сек, следующий через %.0f сек", elapsed, sleep_for)
        await asyncio.sleep(sleep_for)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Collector stopped by user")
