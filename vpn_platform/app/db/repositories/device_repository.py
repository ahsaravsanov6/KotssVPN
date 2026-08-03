"""
app/db/repositories/device_repository.py
"""

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
        return self.db.scalar(
            select(Device).where(Device.id == device_id, Device.user_id == user_id)
        )

    def list_for_user(self, user_id: int) -> list[Device]:
        return list(
            self.db.scalars(
                select(Device).where(Device.user_id == user_id).order_by(Device.device_number)
            )
        )

    def list_all(self) -> list[Device]:
        return list(self.db.scalars(select(Device)))

    def count_for_user(self, user_id: int) -> int:
        return self.db.scalar(select(func.count()).select_from(Device).where(Device.user_id == user_id)) or 0

    def create(self, user_id: int, device_name: str, device_number: int | None = None) -> Device:
        device = Device(user_id=user_id, device_name=device_name, device_number=device_number)
        self.db.add(device)
        self.db.flush()
        return device

    def save(self, device: Device) -> None:
        self.db.add(device)
        self.db.flush()

    def delete(self, device: Device) -> None:
        self.db.delete(device)
        self.db.flush()
