"""
app/services/device_service.py

Ключевая проверка лимита ("достигнут лимит устройств") — как и раньше,
через DeviceRepository.count_for_user().

ИЗМЕНЕНО: при добавлении устройства ему присваивается device_number =
user.next_device_number (1, 2, 3, ... — монотонно растущий, никогда не
переиспользуется), после чего счётчик пользователя увеличивается на 1.
Это гарантирует, что "device_1"/"device_2"/... в панелях всегда
соответствует реальному порядку добавления устройств этого пользователя
(см. app/db/models/user.py и app/db/models/device.py).
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

        device_number = user.next_device_number
        device = self.devices.create(user_id=user.id, device_name=device_name, device_number=device_number)

        user.next_device_number = device_number + 1
        self.db.add(user)
        self.db.flush()

        return AddDeviceResult(success=True, device=device, max_devices=max_devices)

    def unique_device_name(self, user: User, base_name: str) -> str:
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
        return self.devices.get_for_user(device_id, user_id)
