"""
app/db/models/device_server_access.py — доступ конкретного устройства
к конкретному серверу.

ИЗМЕНЕНО: после переноса серверов из БД в файл (app/servers_config.py)
server_id — это строковый слаг сервера ("nl-1"), а не внешний ключ на
таблицу servers (такой таблицы больше не существует). Целостность
(существует ли ещё сервер с таким id) проверяется в рантайме через
ServerManager.get_by_id(), а не СУБД — это осознанный компромисс: при
единицах серверов, редко меняющихся вручную, лишний внешний ключ не
стоит той жёсткости, которую он даёт, а вот гибкость "сервер — просто
файл" стоит того, чтобы не тащить его в реляционную схему.

Если сервер удалён из файла, а строки с его id всё ещё есть в этой
таблице — это не ошибка целостности БД, а нормальная ситуация: такие
"осиротевшие" доступы просто перестают попадать в подписку
(ServerManager.get_by_id вернёт None, SubscriptionService их отфильтрует)
и могут быть безопасно вычищены отдельной администраторской командой,
если понадобится.
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

    provisioned: Mapped[bool] = mapped_column(Boolean, default=False)  # успешно создан на панели
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    device: Mapped["Device"] = relationship(back_populates="server_access")
    # ORM-связи на server больше нет — сервер резолвится в рантайме через
    # ServerManager.get_by_id(access.server_id), см. ProvisioningService/
    # SubscriptionService.
