"""
analytics/bot_db_reader.py — read-only доступ к БД основного бота (vpn_bot.db).

КРИТИЧЕСКИ ВАЖНО: этот модуль никогда не выполняет INSERT/UPDATE/DELETE
в БД бота. Открывает соединение в режиме "ro" (read-only) на уровне SQLite,
так что случайная попытка записи упадёт с ошибкой, а не испортит данные бота.
"""

import sqlite3
from pathlib import Path
from typing import Any

from config import settings
from storage import utcnow_naive


def _connect_readonly() -> sqlite3.Connection:
    db_path = Path(settings.BOT_DB_PATH).resolve()
    # uri=True + mode=ro гарантирует, что соединение НЕ МОЖЕТ писать в файл,
    # даже если в коде где-то по ошибке появится INSERT.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def read_bot_snapshot() -> dict[str, Any]:
    """
    Снимает текущую картину пользователей/подписок/устройств/рефералки
    из БД бота одним коротким read-only соединением.
    """
    now_iso = utcnow_naive().isoformat()

    with _connect_readonly() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

        active_subscriptions = conn.execute(
            "SELECT COUNT(*) FROM users "
            "WHERE subscription_expires_at IS NOT NULL AND subscription_expires_at > ?",
            (now_iso,),
        ).fetchone()[0]

        expired_subscriptions = conn.execute(
            "SELECT COUNT(*) FROM users "
            "WHERE subscription_expires_at IS NOT NULL AND subscription_expires_at <= ?",
            (now_iso,),
        ).fetchone()[0]

        no_subscription = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_expires_at IS NULL"
        ).fetchone()[0]

        total_devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]

        devices_with_vpn_key = conn.execute(
            "SELECT COUNT(*) FROM devices WHERE vpn_email IS NOT NULL"
        ).fetchone()[0]

        total_referrals = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]

        bonus_granted_referrals = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE bonus_granted = 1"
        ).fetchone()[0]

        # email -> telegram_id, чтобы потом сматчить с трафиком из 3X-UI
        device_rows = conn.execute(
            "SELECT vpn_email, user_id, device_name FROM devices WHERE vpn_email IS NOT NULL"
        ).fetchall()
        email_to_user = {
            row["vpn_email"]: {"telegram_id": row["user_id"], "device_name": row["device_name"]}
            for row in device_rows
        }

        # Регистрации пользователей по дням — у User нет created_at в текущей
        # схеме бота, поэтому здесь это не доступно. Оставляем как явный
        # пробел, чтобы не выдумывать данные: график "рост пользователей"
        # дашборд строит по собственным снапшотам total_users во времени,
        # а не по дате регистрации (которой просто нет в схеме бота).

    return {
        "ts": now_iso,
        "total_users": total_users,
        "active_subscriptions": active_subscriptions,
        "expired_subscriptions": expired_subscriptions,
        "no_subscription": no_subscription,
        "total_devices": total_devices,
        "devices_with_vpn_key": devices_with_vpn_key,
        "total_referrals": total_referrals,
        "bonus_granted_referrals": bonus_granted_referrals,
        "email_to_user": email_to_user,
    }
