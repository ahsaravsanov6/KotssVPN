"""
scripts/sync_devices_to_active_servers.py

Запуск после каждого добавления сервера в servers.yaml:
    python -m scripts.sync_devices_to_active_servers
"""

import asyncio
import logging

from app.db.base import SessionLocal
from app.db.repositories.device_access_repository import DeviceServerAccessRepository
from app.db.repositories.device_repository import DeviceRepository
from app.services.provisioning_service import ProvisioningService
from app.services.server_manager import ServerManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("sync_devices_to_active_servers")


async def run() -> None:
    db = SessionLocal()
    try:
        devices = DeviceRepository(db).list_all()
        active_servers = ServerManager().list_active()

        if not devices:
            logger.info("Устройств в БД нет — синхронизировать нечего")
            return
        if not active_servers:
            logger.info("Активных серверов нет — синхронизировать нечего")
            return

        access_repo = DeviceServerAccessRepository(db)
        provisioning = ProvisioningService(db)

        to_create: list[tuple] = []
        for device in devices:
            existing_server_ids = {
                a.server_id for a in access_repo.list_for_device(device.id, enabled_only=False)
            }
            for server in active_servers:
                if server.id not in existing_server_ids:
                    to_create.append((device, server))

        if not to_create:
            logger.info(
                "Все %d устройств уже имеют доступ ко всем %d активным серверам — нечего досоздавать",
                len(devices), len(active_servers),
            )
            return

        logger.info("Найдено %d отсутствующих пар устройство-сервер, провижиню", len(to_create))

        ok_count, fail_count = 0, 0
        for device, server in to_create:
            success = await provisioning.grant_device_access(device, server)
            if success:
                ok_count += 1
                logger.info(
                    "Добавлен доступ: device=%s (%s) -> server=%s",
                    device.id, device.device_name, server.id,
                )
            else:
                fail_count += 1
                logger.warning(
                    "Не удалось провижинить: device=%s -> server=%s (см. DeviceServerAccess.last_error, "
                    "будет подхвачено scripts/resync_pending_access.py)",
                    device.id, server.id,
                )

        db.commit()
        logger.info("Готово: создано и провижинено=%d, отказов=%d", ok_count, fail_count)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(run())
