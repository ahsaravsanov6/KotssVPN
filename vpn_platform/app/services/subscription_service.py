"""
app/services/subscription_service.py

Оркестрирует выдачу подписки: находит пользователя по токену, для его
устройств получает сервера через DeviceServerAccessRepository, просит
SubscriptionGenerator собрать тело ответа.

ДОБАВЛЕНО: build_device_subscription(user, device_id) — подписка ТОЛЬКО
для одного устройства (та самая персональная ссылка на устройство,
которую боту показывает пользователю в "Мой VPN" → "Мои ключи"). Модель
провижининга не изменилась: у устройства один UUID, реплицированный на
все сервера, куда оно добавлено — просто отдаём его отдельно от других
устройств пользователя.
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

    def _servers_for_device(self, device: Device) -> list:
        """Активные (provisioned=True) сервера конкретного устройства."""
        access_rows = self.device_access.list_for_device(device.id, enabled_only=True)
        servers = [self.server_manager.get_by_id(row.server_id) for row in access_rows if row.provisioned]
        return [s for s in servers if s is not None]

    def build_subscription(self, user: User) -> SubscriptionPayload:
        """
        Подписка на ВСЕ устройства пользователя сразу. Пустой список —
        нормальный случай (подписка неактивна или устройств ещё нет).
        """
        devices_with_servers: list[tuple[Device, list]] = []

        if user.subscription_status == "active":
            for device in self.devices.list_for_user(user.id):
                devices_with_servers.append((device, self._servers_for_device(device)))

        body = SubscriptionGenerator.build_body(devices_with_servers)
        header = SubscriptionGenerator.build_userinfo_header(user)
        return SubscriptionPayload(body_base64=body, userinfo_header=header)

    def build_device_subscription(self, user: User, device_id: int) -> SubscriptionPayload:
        """
        Подписка ОДНОГО устройства — то, что реально выдаётся ботом
        пользователю на кнопку "получить ключ" для конкретного устройства.
        Содержит записи со всех серверов, куда это устройство провижинено.
        """
        device = self.device_service.get_owned_device(user.id, device_id)
        if not device:
            raise SubscriptionNotFound(f"device:{device_id}")

        servers = self._servers_for_device(device) if user.subscription_status == "active" else []

        body = SubscriptionGenerator.build_body([(device, servers)])
        header = SubscriptionGenerator.build_userinfo_header(user)
        return SubscriptionPayload(body_base64=body, userinfo_header=header)

    async def add_device(self, user: User, device_name: str) -> AddDeviceResult:
        """
        Полный цикл добавления устройства: проверка подписки/лимита
        (DeviceService, присваивает device_number) + провижининг на всех
        активных серверах платформы (ProvisioningService) — один и тот же
        UUID устройства создаётся сразу в каждой панели.
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
        device = self.device_service.get_owned_device(user.id, device_id)
        if not device:
            return False
        server = self.server_manager.get_by_id(server_id)
        if not server:
            return False
        return await self.provisioning.grant_device_access(device, server)
