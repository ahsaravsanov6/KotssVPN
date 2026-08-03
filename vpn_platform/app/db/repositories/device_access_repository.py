"""
app/db/repositories/device_access_repository.py
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.device_server_access import DeviceServerAccess


class DeviceServerAccessRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, device_id: int, server_id: str) -> Optional[DeviceServerAccess]:
        return self.db.scalar(
            select(DeviceServerAccess).where(
                DeviceServerAccess.device_id == device_id,
                DeviceServerAccess.server_id == server_id,
            )
        )

    def list_for_device(self, device_id: int, enabled_only: bool = True) -> list[DeviceServerAccess]:
        stmt = select(DeviceServerAccess).where(DeviceServerAccess.device_id == device_id)
        if enabled_only:
            stmt = stmt.where(DeviceServerAccess.enabled.is_(True))
        return list(self.db.scalars(stmt))

    def get_or_create(self, device_id: int, server_id: str) -> DeviceServerAccess:
        existing = self.get(device_id, server_id)
        if existing:
            return existing
        access = DeviceServerAccess(device_id=device_id, server_id=server_id)
        self.db.add(access)
        self.db.flush()
        return access

    def save(self, access: DeviceServerAccess) -> None:
        self.db.add(access)
        self.db.flush()

    def delete(self, access: DeviceServerAccess) -> None:
        self.db.delete(access)
        self.db.flush()
