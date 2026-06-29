"""
analytics/storage.py — собственная БД аналитики (analytics.db).

Это ВРЕМЕННЫЕ РЯДЫ (time-series): каждый запуск коллектора добавляет
новую строку-снапшот, старые строки не перезаписываются. На основе
этого веб-панель строит графики "как менялось со временем".

Важно: эта БД полностью отдельная от vpn_bot.db бота. Коллектор
читает vpn_bot.db только на SELECT, никогда не пишет в неё.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from config import settings

SCHEMA = """
-- Снапшот общей картины по пользователям/подпискам/устройствам.
-- Один снапшот = один тик коллектора (~раз в 15 минут).
CREATE TABLE IF NOT EXISTS snapshot_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                  -- ISO timestamp снапшота
    total_users INTEGER NOT NULL,
    active_subscriptions INTEGER NOT NULL,
    expired_subscriptions INTEGER NOT NULL,
    no_subscription INTEGER NOT NULL,
    total_devices INTEGER NOT NULL,
    devices_with_vpn_key INTEGER NOT NULL,
    total_referrals INTEGER NOT NULL,
    bonus_granted_referrals INTEGER NOT NULL
);

-- Снапшот сервера (CPU/RAM/диск/сеть), как отдаёт 3X-UI /server/status.
CREATE TABLE IF NOT EXISTS snapshot_server (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    cpu_percent REAL,
    cpu_cores INTEGER,
    mem_current INTEGER,               -- байты
    mem_total INTEGER,
    disk_current INTEGER,
    disk_total INTEGER,
    load1 REAL,
    load5 REAL,
    load15 REAL,
    tcp_count INTEGER,
    udp_count INTEGER,
    net_io_up INTEGER,                 -- байт/сек (instant rate, как отдаёт панель)
    net_io_down INTEGER,
    net_traffic_sent INTEGER,          -- байт, накопительно с момента старта xray/системы
    net_traffic_recv INTEGER,
    uptime_seconds INTEGER,
    xray_state TEXT,
    xray_version TEXT,
    online_clients INTEGER             -- кол-во онлайн-клиентов на момент снапшота
);

-- Снапшот трафика по каждому VPN-клиенту (email в 3X-UI = устройство пользователя).
-- up/down — НАКОПИТЕЛЬНЫЕ счётчики с момента создания клиента (как в 3X-UI),
-- поэтому графики "трафик за период" считаются как разность между снапшотами.
CREATE TABLE IF NOT EXISTS snapshot_client_traffic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    email TEXT NOT NULL,
    telegram_id INTEGER,
    up INTEGER NOT NULL,
    down INTEGER NOT NULL,
    enable INTEGER NOT NULL,
    online INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_su_ts ON snapshot_users(ts);
CREATE INDEX IF NOT EXISTS idx_ss_ts ON snapshot_server(ts);
CREATE INDEX IF NOT EXISTS idx_sct_ts ON snapshot_client_traffic(ts);
CREATE INDEX IF NOT EXISTS idx_sct_email ON snapshot_client_traffic(email);

-- События оплат. Бот пишет сюда ОДНУ строку напрямую (без зависимости от
-- модуля analytics) сразу после подтверждённой оплаты — см. вставку в
-- process_successful_payment() в bot/handlers/payment.py. Если бот не
-- пишет (например, ещё не обновлён) — таблица просто остаётся пустой,
-- и дашборд покажет "нет данных", не падая.
CREATE TABLE IF NOT EXISTS payment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    telegram_id INTEGER,
    method TEXT,              -- yookassa / cryptobot / heleket
    kind TEXT DEFAULT 'subscription',  -- subscription / device (на будущее)
    price REAL,
    days INTEGER
);

CREATE INDEX IF NOT EXISTS idx_pe_ts ON payment_events(ts);
"""


def utcnow_naive() -> datetime:
    """
    UTC время без deprecation warning (датetime.utcnow() устарел в 3.12+),
    но без tzinfo — чтобы оставаться совместимым по формату с naive
    timestamp'ами, которые использует SQLAlchemy в БД бота
    (Column(DateTime, default=datetime.now)).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.ANALYTICS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)

        # Миграция для БД, созданных до появления поля kind в payment_events
        # (CREATE TABLE IF NOT EXISTS не добавляет колонки в уже существующую
        # таблицу — добавляем её отдельно, если её ещё нет).
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(payment_events)")}
        if "kind" not in existing_cols:
            conn.execute("ALTER TABLE payment_events ADD COLUMN kind TEXT DEFAULT 'subscription'")


def purge_old_data(retention_days: int) -> None:
    """Удаляет снапшоты старше retention_days, чтобы БД не росла бесконечно."""
    cutoff = (utcnow_naive() - timedelta(days=retention_days)).isoformat()
    with db() as conn:
        conn.execute("DELETE FROM snapshot_users WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM snapshot_server WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM snapshot_client_traffic WHERE ts < ?", (cutoff,))
