"""
app/services/provisioning_service.py

Единственное место, где бизнес-логика встречается с провайдерами панелей.
Работает исключительно через PanelProvider (см. providers/base.py).

Изменено после решения вернуть лимит устройств: провижининг теперь на
уровне Device, а не User. Один Device -> один VLESS-клиент на каждом
сервере, куда устройство добавлено (DeviceServerAccess) — та же
гранулярность, что была в исходном проекте, только размноженная на N
серверов вместо одного.

Ключевой инвариант не изменился: провижининг на одном сервере никогда
не должен ронять провижининг на другом. Ошибка одной панели логируется
в DeviceServerAccess.last_error и не прерывает цикл по остальным
серверам.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.device import Device
from app.db.repositories.device_access_repository import DeviceServerAccessRepository
from app.providers.registry import get_provider
from app.services.server_manager import ServerManager
from app.servers_config import ServerConfig as Server

logger = logging.getLogger(__name__)

# Локальные (per-process) блокировки на пару (device_id, server_id) —
# защищают от гонки при повторных вебхуках/ретраях, аналогично тому, как
# было устроено на уровне (user_id, server_id) в предыдущей версии.
_access_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _lock_for(device_id: int, server_id: str) -> asyncio.Lock:
    key = (device_id, server_id)
    if key not in _access_locks:
        _access_locks[key] = asyncio.Lock()
    return _access_locks[key]


class ProvisioningService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.access = DeviceServerAccessRepository(db)
        self.server_manager = ServerManager()

    async def grant_device_access(self, device: Device, server: Server) -> bool:
        """Выдаёт устройству доступ на конкретном сервере: создаёт клиента
        на панели и фиксирует результат. Идемпотентна и безопасна к
        параллельным вызовам для одной и той же пары (device, server)."""
        async with _lock_for(device.id, server.id):
            try:
                access = self.access.get_or_create(device.id, server.id)
            except IntegrityError:
                self.db.rollback()
                access = self.access.get(device.id, server.id)
                if access is None:
                    raise

            provider = get_provider(server.panel_type)

            result = await provider.create_client(server, device)
            access.enabled = True
            access.last_synced_at = datetime.utcnow()

            if result.success:
                access.provisioned = True
                access.client_remote_id = result.remote_id
                access.last_error = None
            else:
                access.provisioned = False
                access.last_error = result.message
                logger.error("Provisioning failed: device=%s server=%s: %s", device.id, server.id, result.message)

            self.access.save(access)
            return result.success

    async def revoke_device_access(self, device: Device, server: Server) -> bool:
        """Отзывает доступ устройства на конкретном сервере — удаляет
        клиента на панели, помечает доступ выключенным."""
        async with _lock_for(device.id, server.id):
            access = self.access.get(device.id, server.id)
            if not access:
                return True

            provider = get_provider(server.panel_type)
            success = True
            if access.provisioned and access.client_remote_id:
                result = await provider.delete_client(server, access.client_remote_id)
                success = result.success
                if not result.success:
                    access.last_error = result.message
                    logger.error("Revoke failed: device=%s server=%s: %s", device.id, server.id, result.message)

            access.enabled = False
            access.provisioned = False
            access.last_synced_at = datetime.utcnow()
            self.access.save(access)
            return success

    async def revoke_all_for_device(self, device: Device) -> None:
        """Полное удаление устройства со всех серверов — вызывается при
        удалении устройства пользователем (аналог xui_client.delete_user
        в devices.py, только по всем серверам, а не одному)."""
        for access in self.access.list_for_device(device.id, enabled_only=False):
            server = self.server_manager.get_by_id(access.server_id)
            if server is None:
                logger.warning(
                    "revoke_all_for_device: сервер %r из servers-файла удалён, "
                    "просто помечаю доступ выключенным без похода на панель",
                    access.server_id,
                )
                access.enabled = False
                access.provisioned = False
                self.access.save(access)
                continue
            await self.revoke_device_access(device, server)

    async def sync_device_to_servers(self, device: Device, servers: list[Server]) -> None:
        """Гарантирует, что устройство провижинено на каждом сервере из
        списка. Вызывается сразу после добавления устройства — на все
        активные сервера платформы (см. ServerManager.pick_servers_for_new_device)."""
        for server in servers:
            await self.grant_device_access(device, server)

    async def regenerate_device_key(self, device: Device) -> None:
        """
        Перевыпуск UUID конкретного устройства: обновляет ключ на ВСЕХ
        серверах, где у устройства есть провижиненный доступ. Частичный
        отказ на одном сервере не откатывает уже обновлённые — ошибка
        остаётся в last_error того конкретного DeviceServerAccess и может
        быть повторена отдельно (см. scripts/resync_pending_access.py).
        """
        device.regenerate_uuid()
        for access in self.access.list_for_device(device.id, enabled_only=True):
            if not (access.provisioned and access.client_remote_id):
                continue
            server = self.server_manager.get_by_id(access.server_id)
            if server is None:
                logger.warning(
                    "regenerate_device_key: сервер %r из servers-файла удалён, пропускаю обновление на нём",
                    access.server_id,
                )
                continue
            provider = get_provider(server.panel_type)
            result = await provider.update_client(server, device, access.client_remote_id)
            access.last_synced_at = datetime.utcnow()
            access.last_error = None if result.success else result.message
            self.access.save(access)
