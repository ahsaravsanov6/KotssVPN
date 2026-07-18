"""
app/db/models/device.py — устройство пользователя.

Прямой преемник Device из public_html/backend/database.py. Там строка
Device хранила vpn_email/vpn_uuid/vpn_sub_id ОДНОГО VLESS-клиента на
ОДНОМ сервере — потому что сервер был один. Здесь Device хранит только
свой собственный UUID (один на устройство, как и раньше — не на
пользователя), а привязка "этот device на этом сервере — вот такой
клиент" вынесена в отдельную таблицу DeviceServerAccess, по одной строке
на каждый сервер, куда устройство должно быть провижинено.

Лимит устройств пользователя (3 + user.extra_devices) проверяется по
количеству строк Device, точно как в исходном проекте
(`len(user.devices) >= max_devices` в /devices/add).
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

    # Один UUID на устройство — используется как VLESS id на КАЖДОМ
    # сервере, куда это устройство провижинено (см. DeviceServerAccess).
    # Меняется только явной операцией "перевыпустить ключ этого устройства".
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
