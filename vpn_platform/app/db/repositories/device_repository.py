from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.device import Device


class DeviceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, device_id: int) -> Optional[Device]:
        return self.db.get(Device, device_id)

    def get_for_user(self, device_id: int, user_id: int) -> Optional[Device]:
        """Достаёт устройство только если оно принадлежит указанному
        пользователю — защита от IDOR (телеграм-айди A не должен иметь
        возможность управлять устройством пользователя B, зная его id)."""
        return self.db.scalar(
            select(Device).where(Device.id == device_id, Device.user_id == user_id)
        )

    def list_for_user(self, user_id: int) -> list[Device]:
        return list(self.db.scalars(select(Device).where(Device.user_id == user_id)))

    def list_all(self) -> list[Device]:
        """Используется операционными скриптами (например,
        scripts/sync_devices_to_active_servers.py) — обычным сервисам,
        работающим в рамках одного пользователя, этот метод не нужен."""
        return list(self.db.scalars(select(Device)))

    def count_for_user(self, user_id: int) -> int:
        return self.db.scalar(select(func.count()).select_from(Device).where(Device.user_id == user_id)) or 0

    def create(self, user_id: int, device_name: str) -> Device:
        device = Device(user_id=user_id, device_name=device_name)
        self.db.add(device)
        self.db.flush()
        return device

    def save(self, device: Device) -> None:
        self.db.add(device)
        self.db.flush()

    def delete(self, device: Device) -> None:
        self.db.delete(device)
        self.db.flush()
