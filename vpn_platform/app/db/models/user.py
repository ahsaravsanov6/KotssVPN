"""
app/db/models/user.py — пользователь платформы.

ДОБАВЛЕНО: next_device_number — счётчик, из которого берётся номер
следующего добавляемого устройства (1, 2, 3, ...). Растёт монотонно и
НИКОГДА не уменьшается и не переиспользуется при удалении устройства —
это гарантирует, что "device_1/device_2/device_3..." всегда соответствует
реальному порядку добавления устройств этого пользователя, а не
случайно освободившемуся номеру. Именно этот номер (а не
db-автоинкрементный Device.id) используется для построения имени
клиента в панелях (см. app/providers/xui/client.py::remote_id_for).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _new_sub_token() -> str:
    import secrets

    return secrets.token_urlsafe(24)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)

    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Токен для публичных ссылок подписки:
    #   /sub/<sub_token>              — (сохранён для обратной совместимости/отладки,
    #                                    отдаёт ВСЕ устройства сразу)
    #   /sub/<sub_token>/<device_id>  — персональная ссылка ОДНОГО устройства,
    #                                    именно её выдаёт бот пользователю
    sub_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_new_sub_token)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tariff: Mapped[str] = mapped_column(String(32), default="standard")

    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    extra_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Следующий порядковый номер устройства ЭТОГО пользователя (см. докстринг
    # модуля). Начинается с 1, чтобы первое устройство было "device_1".
    next_device_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    referrer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.telegram_id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    devices: Mapped[list["Device"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def subscription_status(self) -> str:
        if not self.subscription_expires_at:
            return "none"
        return "active" if self.subscription_expires_at > datetime.utcnow() else "expired"
