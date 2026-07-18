"""
app/services/subscription_service.py

Оркестрирует выдачу подписки: находит пользователя по токену, проверяет
статус, для КАЖДОГО его устройства получает сервера через
DeviceServerAccessRepository, просит SubscriptionGenerator собрать общее
тело ответа (все устройства сразу — это то, что ложится в одну ссылку
/sub/<token>).

Также здесь — оркестрация "добавить устройство и сразу провижинить его
на серверах" (используется ботом при /devices/add) и "добавить
устройству ещё один сервер" (точечное расширение, например по стране).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.device import Device
from app.db.models.user import User
from app.db.repositories.device_access_repository import DeviceServerAccessRepository
from app.db.repositories.device_repository import DeviceRepository
from app.db.repositories.user_repository import UserRepository
from app.services.device_service import AddDeviceResult, DeviceService
from app.services.provisioning_service import ProvisioningService
from app.services.server_manager import ServerManager
from app.services.subscription_generator import SubscriptionGenerator


@dataclass
class SubscriptionPayload:
    body_base64: str
    userinfo_header: str


class SubscriptionNotFound(Exception):
    pass


class SubscriptionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.devices = DeviceRepository(db)
        self.device_access = DeviceServerAccessRepository(db)
        self.server_manager = ServerManager()
        self.device_service = DeviceService(db)
        self.provisioning = ProvisioningService(db)

    def get_by_token(self, sub_token: str) -> User:
        user = self.users.get_by_sub_token(sub_token)
        if not user:
            raise SubscriptionNotFound(sub_token)
        return user

    def build_subscription(self, user: User) -> SubscriptionPayload:
        """
        Пустой список — нормальный, не ошибочный случай: подписка неактивна
        или устройств ещё нет. Клиент получит валидный пустой список вместо
        ошибки парсинга.

        Сервер для каждого DeviceServerAccess резолвится через
        ServerManager.get_by_id() — server_id больше не внешний ключ,
        поэтому "джойн" делается здесь явно, в памяти, а не SQL-запросом.
        Доступы к серверам, удалённым из servers.yaml, просто отфильтровываются.
        """
        devices_with_servers: list[tuple[Device, list]] = []

        if user.subscription_status == "active":
            for device in self.devices.list_for_user(user.id):
                access_rows = self.device_access.list_for_device(device.id, enabled_only=True)
                servers = [
                    self.server_manager.get_by_id(row.server_id)
                    for row in access_rows
                    if row.provisioned
                ]
                servers = [s for s in servers if s is not None]
                devices_with_servers.append((device, servers))

        body = SubscriptionGenerator.build_body(devices_with_servers)
        header = SubscriptionGenerator.build_userinfo_header(user)
        return SubscriptionPayload(body_base64=body, userinfo_header=header)

    async def add_device(self, user: User, device_name: str) -> AddDeviceResult:
        """
        Полный цикл добавления устройства: проверка подписки/лимита
        (DeviceService) + провижининг на всех активных серверах платформы
        (ProvisioningService). Если провижининг на КАКОМ-ТО из серверов не
        удался — устройство всё равно остаётся добавленным (частичный
        доступ лучше, чем полный отказ; см. ProvisioningService про
        независимость серверов друг от друга), а ошибка видна в
        DeviceServerAccess.last_error и будет подхвачена
        scripts/resync_pending_access.py.
        """
        result = self.device_service.add_device(user, device_name)
        if not result.success or not result.device:
            return result

        servers = self.server_manager.pick_servers_for_new_device()
        await self.provisioning.sync_device_to_servers(result.device, servers)
        return result

    async def remove_device(self, user: User, device_id: int) -> bool:
        device = self.device_service.get_owned_device(user.id, device_id)
        if not device:
            return False
        await self.provisioning.revoke_all_for_device(device)
        self.devices.delete(device)
        return True

    async def add_server_to_device(self, user: User, device_id: int, server_id: str) -> bool:
        """Точечное расширение конкретного устройства ещё одним сервером."""
        device = self.device_service.get_owned_device(user.id, device_id)
        if not device:
            return False
        server = self.server_manager.get_by_id(server_id)
        if not server:
            return False
        return await self.provisioning.grant_device_access(device, server)
