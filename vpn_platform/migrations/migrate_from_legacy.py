"""
migrations/migrate_from_legacy.py

Переносит данные из старой vpn_bot.db (public_html/backend/database.py:
User/Device/Referral) в новую схему платформы.

Запускать один раз, из корня репозитория:

    python -m migrations.migrate_from_legacy \\
        --server-id primary \\
        --server-address ... --server-sni ... --server-public-key ... \\
        --panel-base-url ... --panel-username ... --panel-password ... \\
        --inbound-id ...

Если сервер с указанным --server-id уже добавлен ранее (например, через
scripts/add_server.py) — он просто переиспользуется, остальные
--server-*/--panel-* аргументы в этом случае можно не передавать.

ИЗМЕНЕНО: сервер больше не строка БД — он либо уже существует в
servers.yaml (см. app/servers_config.py), либо создаётся в этом файле
тем же ServerManager, которым пользуется весь остальной код. Никакой
отдельной ORM-модели Server здесь больше нет.

Старая таблица Device (device_name, vpn_email, vpn_uuid) почти дословно
соответствует новой (Device + DeviceServerAccess) — каждое легаси-
устройство уже является полноценным VLESS-клиентом на панели, поэтому
миграция просто РЕГИСТРИРУЕТ это в новой БД (client_remote_id=vpn_email,
provisioned=True) БЕЗ единого сетевого вызова к панели.
"""

import argparse
import logging
import sqlite3
from pathlib import Path

from app.config import settings
from app.db.base import SessionLocal, create_all_tables
from app.db.models import Device, DeviceServerAccess, User
from app.services.server_manager import ServerManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("migrate_from_legacy")


def _read_legacy_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT telegram_id, username, first_name, is_active, "
        "subscription_expires_at, trial_used, referrer_id, extra_devices "
        "FROM users"
    ).fetchall()
    return [dict(r) for r in rows]


def _read_legacy_devices(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, user_id, device_name, vpn_email, vpn_uuid FROM devices"
    ).fetchall()
    return [dict(r) for r in rows]


def _ensure_default_server(args) -> str:
    """Возвращает id сервера (слаг), который будет использован для всех
    перенесённых устройств. Переиспользует существующую запись в
    servers.yaml, если она уже есть, иначе создаёт новую."""
    manager = ServerManager()
    existing = manager.get_by_id(args.server_id)
    if existing:
        logger.info("Использую уже существующий сервер id=%s (%s)", existing.id, existing.address)
        return existing.id

    required = ["server_address", "server_sni", "server_public_key", "panel_base_url", "panel_username", "panel_password", "inbound_id"]
    missing = [a for a in required if getattr(args, a) is None]
    if missing:
        raise SystemExit(
            f"Сервер id={args.server_id!r} ещё не существует в servers.yaml — "
            f"передайте все параметры для его создания: --{', --'.join(m.replace('_', '-') for m in missing)}"
        )

    server = manager.add_server(
        id=args.server_id,
        name=args.server_name,
        country=args.server_country,
        address=args.server_address,
        port=args.server_port,
        sni=args.server_sni,
        reality_public_key=args.server_public_key,
        reality_short_id=args.server_short_id,
        panel_base_url=args.panel_base_url,
        panel_username=args.panel_username,
        panel_password=args.panel_password,
        inbound_id=args.inbound_id,
        priority=0,
    )
    logger.info("Создан сервер id=%s (%s) в %s", server.id, server.address, settings.SERVERS_FILE)
    return server.id


def run(args: argparse.Namespace) -> None:
    legacy_path = args.legacy_db or settings.LEGACY_BOT_DB_PATH
    if not legacy_path or not Path(legacy_path).exists():
        raise SystemExit(f"Не найден файл легаси-БД: {legacy_path!r}. Укажите --legacy-db или LEGACY_BOT_DB_PATH в .env")

    create_all_tables()  # для первого запуска на пустой платформенной БД; в проде — Alembic
    default_server_id = _ensure_default_server(args)

    legacy_conn = sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True)
    legacy_conn.row_factory = sqlite3.Row
    try:
        legacy_users = _read_legacy_users(legacy_conn)
        legacy_devices = _read_legacy_devices(legacy_conn)
    finally:
        legacy_conn.close()

    logger.info("Прочитано %d пользователей и %d устройств из %s", len(legacy_users), len(legacy_devices), legacy_path)

    db = SessionLocal()
    try:
        by_telegram_id: dict[int, User] = {}
        migrated_users, skipped_users = 0, 0

        for row in legacy_users:
            existing = db.query(User).filter(User.telegram_id == row["telegram_id"]).first()
            if existing:
                by_telegram_id[row["telegram_id"]] = existing
                skipped_users += 1
                continue

            user = User(
                telegram_id=row["telegram_id"],
                username=row["username"],
                first_name=row["first_name"],
                is_active=bool(row["is_active"]),
                subscription_expires_at=row["subscription_expires_at"],
                trial_used=bool(row["trial_used"]),
                extra_devices=row["extra_devices"] or 0,
                tariff=settings.DEFAULT_TARIFF,
            )
            db.add(user)
            db.flush()
            by_telegram_id[row["telegram_id"]] = user
            migrated_users += 1

        db.commit()

        for row in legacy_users:
            if not row["referrer_id"]:
                continue
            user = by_telegram_id.get(row["telegram_id"])
            referrer = by_telegram_id.get(row["referrer_id"])
            if user and referrer:
                user.referrer_id = referrer.telegram_id
        db.commit()

        migrated_devices, provisioned_devices, unprovisioned_devices, skipped_devices = 0, 0, 0, 0

        for row in legacy_devices:
            owner = by_telegram_id.get(row["user_id"])
            if not owner:
                logger.warning("Устройство id=%s ссылается на несуществующего пользователя %s — пропускаю", row["id"], row["user_id"])
                skipped_devices += 1
                continue

            legacy_uuid = row["vpn_uuid"]
            legacy_email = row["vpn_email"]

            device = Device(user_id=owner.id, device_name=row["device_name"])
            if legacy_uuid:
                device.uuid = legacy_uuid  # переиспользуем существующий UUID — старый ключ продолжит работать
            db.add(device)
            db.flush()
            migrated_devices += 1

            if not legacy_uuid:
                unprovisioned_devices += 1
                continue

            access = DeviceServerAccess(
                device_id=device.id,
                server_id=default_server_id,
                enabled=True,
                client_remote_id=legacy_email,
                provisioned=True,  # клиент УЖЕ существует на панели — сетевой вызов не нужен
            )
            db.add(access)
            provisioned_devices += 1

        db.commit()

        logger.info(
            "Готово: пользователи создано=%d/пропущено=%d; устройства создано=%d "
            "(провижинено=%d, требуют довыпуска=%d, пропущено=%d)",
            migrated_users, skipped_users, migrated_devices,
            provisioned_devices, unprovisioned_devices, skipped_devices,
        )
        if unprovisioned_devices:
            logger.warning(
                "%d устройств перенесено без VPN-клиента (в легаси-БД не было vpn_uuid). "
                "Попросите пользователей удалить и заново добавить эти устройства через бота "
                "(это создаст рабочий клиент), либо провижиньте их вручную.",
                unprovisioned_devices,
            )
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--legacy-db", default=None, help="Путь к старой vpn_bot.db (иначе берётся LEGACY_BOT_DB_PATH из .env)")

    p.add_argument("--server-id", required=True, help="Слаг сервера в servers.yaml (существующий или новый)")
    p.add_argument("--server-name", default="Server 1")
    p.add_argument("--server-country", default="NL")
    p.add_argument("--server-address", default=None)
    p.add_argument("--server-port", type=int, default=443)
    p.add_argument("--server-sni", default=None)
    p.add_argument("--server-public-key", default=None)
    p.add_argument("--server-short-id", default="")

    p.add_argument("--panel-base-url", default=None)
    p.add_argument("--panel-username", default=None)
    p.add_argument("--panel-password", default=None)
    p.add_argument("--inbound-id", type=int, default=None)

    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())
