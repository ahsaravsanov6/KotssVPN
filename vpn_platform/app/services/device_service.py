"""
app/services/device_service.py

Прямой преемник логики /devices/add, /devices/remove из
public_html/backend/main.py. Ключевая проверка лимита ("достигнут лимит
устройств") перенесена почти дословно: было
`len(user.devices) >= max_devices`, здесь то же самое через
DeviceRepository.count_for_user().

Отличие от исходного: там же, в одном эндпоинте, был вызов
xui_client.create_user() на единственный сервер. Здесь добавление
устройства и провижининг на серверах разделены — DeviceService отвечает
за лимиты и запись в БД, ProvisioningService — за реальное создание
клиентов на панелях (может быть несколько серверов на одно устройство).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.device import Device
from app.db.models.user import User
from app.db.repositories.device_repository import DeviceRepository


@dataclass
class AddDeviceResult:
    success: bool
    device: Device | None = None
    limit_reached: bool = False
    max_devices: int = 0
    message: str = ""


class DeviceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.devices = DeviceRepository(db)

    def max_devices_for(self, user: User) -> int:
        return settings.DEFAULT_MAX_DEVICES + user.extra_devices

    def add_device(self, user: User, device_name: str) -> AddDeviceResult:
        if user.subscription_status != "active":
            return AddDeviceResult(success=False, message="Для добавления устройства нужна активная подписка.")

        max_devices = self.max_devices_for(user)
        current_count = self.devices.count_for_user(user.id)

        if current_count >= max_devices:
            return AddDeviceResult(
                success=False,
                limit_reached=True,
                max_devices=max_devices,
                message=f"Достигнут лимит устройств ({max_devices})",
            )

        device = self.devices.create(user_id=user.id, device_name=device_name)
        return AddDeviceResult(success=True, device=device, max_devices=max_devices)

    def unique_device_name(self, user: User, base_name: str) -> str:
        """Аналог _build_unique_device_name из bot/handlers/devices.py, но
        на стороне backend — единая точка правды вместо дублирования
        логики нумерации в боте."""
        existing_names = {d.device_name for d in self.devices.list_for_user(user.id)}
        if base_name not in existing_names:
            return base_name
        index = 2
        while f"{base_name} #{index}" in existing_names:
            index += 1
        return f"{base_name} #{index}"

    def list_devices(self, user_id: int) -> list[Device]:
        return self.devices.list_for_user(user_id)

    def get_owned_device(self, user_id: int, device_id: int) -> Device | None:
        """Всегда используйте этот метод, а не devices.get_by_id() напрямую,
        в хендлерах, куда device_id приходит от пользователя — иначе
        пользователь A сможет управлять устройством пользователя B, просто
        подобрав/угадав числовой id."""
        return self.devices.get_for_user(device_id, user_id)
