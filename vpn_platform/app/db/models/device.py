"""
app/db/models/device.py — устройство пользователя.

ДОБАВЛЕНО: device_number — порядковый номер устройства ИМЕННО ЭТОГО
пользователя (1, 2, 3, ... и дальше при докупке доп. мест), взятый из
User.next_device_number в момент создания (см. DeviceService.add_device).
Используется для построения email/remote_id клиента в панелях —
"{telegram_id}_device_{device_number}" (см.
app/providers/xui/client.py::remote_id_for) — чтобы номер устройства в
панели соответствовал реальному порядковому номеру устройства
пользователя, а не произвольному автоинкрементному id строки в БД.

nullable=True — для обратной совместимости с устройствами, перенесёнными
migrations/migrate_from_legacy.py ДО этой миграции; remote_id_for
подстрахован фоллбэком на device.id, если device_number почему-то пуст.

Модель провижининга не изменилась: один UUID на устройство, реплицированный
на каждый активный сервер через DeviceServerAccess.
"""

import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _new_uuid() -> str:
    return str(uuid_lib.uuid4())


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    device_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Порядковый номер устройства пользователя (1, 2, 3, ...) — см. докстринг выше.
    device_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Один UUID на устройство — используется как VLESS id на КАЖДОМ
    # сервере, куда это устройство провижинено (см. DeviceServerAccess).
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=_new_uuid)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="devices")
    server_access: Mapped[list["DeviceServerAccess"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    def regenerate_uuid(self) -> None:
        """
        Перевыпуск ключа ЭТОГО устройства. Сам по себе НЕ обновляет
        клиентов на серверах — это ProvisioningService.regenerate_device_key(),
        который обязан вызвать update_client на каждом сервере, где у
        устройства есть провижиненный доступ, СРАЗУ после этого вызова.
        """
        self.uuid = _new_uuid()
