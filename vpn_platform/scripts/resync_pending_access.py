"""
scripts/resync_pending_access.py

ProvisioningService.grant_device_access никогда не бросает исключение
наружу при отказе панели — ошибка оседает в DeviceServerAccess.last_error,
а enabled=True/provisioned=False. Это осознанное решение (провижининг на
одном сервере не должен ронять провижининг на другом), но кто-то должен
периодически досматривать такие "зависшие" записи и повторять попытку —
иначе устройство, которое добавили в момент недоступности одного из
серверов, рискует навсегда остаться без доступа именно к нему.

Запуск (рекомендуется через cron/systemd timer раз в 5-15 минут):
    python -m scripts.resync_pending_access
"""

import asyncio
import logging

from app.db.base import SessionLocal
from app.db.models.device_server_access import DeviceServerAccess
from app.services.provisioning_service import ProvisioningService
from app.services.server_manager import ServerManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("resync_pending_access")


async def run() -> None:
    db = SessionLocal()
    server_manager = ServerManager()
    try:
        pending = (
            db.query(DeviceServerAccess)
            .filter(DeviceServerAccess.enabled.is_(True), DeviceServerAccess.provisioned.is_(False))
            .all()
        )
        if not pending:
            logger.info("Нет зависших доступов — всё синхронизировано")
            return

        logger.info("Найдено %d зависших доступов, повторяю провижининг", len(pending))
        provisioning = ProvisioningService(db)

        ok_count, fail_count, orphaned_count = 0, 0, 0
        for access in pending:
            device = access.device
            server = server_manager.get_by_id(access.server_id)
            if server is None:
                logger.warning(
                    "Сервер %r из servers-файла больше не существует — пропускаю device=%s",
                    access.server_id, device.id,
                )
                orphaned_count += 1
                continue

            success = await provisioning.grant_device_access(device, server)
            if success:
                ok_count += 1
                logger.info(
                    "Восстановлен доступ: device=%s (%s) server=%s",
                    device.id, device.device_name, server.name,
                )
            else:
                fail_count += 1
                logger.warning(
                    "Всё ещё не удаётся: device=%s server=%s: %s",
                    device.id, server.name, access.last_error,
                )

        db.commit()
        logger.info(
            "Готово: восстановлено=%d, всё ещё недоступно=%d, сервер не найден=%d",
            ok_count, fail_count, orphaned_count,
        )
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(run())
