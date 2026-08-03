"""
app/db/models/device_server_access.py — доступ конкретного устройства
к конкретному серверу.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DeviceServerAccess(Base):
    __tablename__ = "device_server_access"
    __table_args__ = (UniqueConstraint("device_id", "server_id", name="uq_device_server"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False)
    server_id: Mapped[str] = mapped_column(String(64), nullable=False)  # id из servers.yaml, НЕ FK

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    client_remote_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    provisioned: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    device: Mapped["Device"] = relationship(back_populates="server_access")
