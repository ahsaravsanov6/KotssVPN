"""
app/db/models/user.py — пользователь платформы.

ВАЖНО (изменено после решения о лимите устройств): единого User.uuid
здесь больше нет. Раньше один UUID работал сразу на всех серверах
пользователя — это красиво решало задачу "одна ссылка на N серверов",
но стирало механику лимита устройств из исходного проекта (там лимит
считался по количеству добавленных Device, каждое со своим VLESS-
клиентом и limitIp=1). Чтобы не терять это поведение, UUID снова живёт
на уровне Device (см. app/db/models/device.py) — просто теперь каждое
устройство размножается не на один сервер, а на все сервера платформы.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _new_sub_token() -> str:
    # urlsafe, без public-угадываемости telegram_id в ссылке подписки
    import secrets

    return secrets.token_urlsafe(24)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)

    username: Mapped[str | None] = mapped_column(String, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Токен для публичной ссылки подписки: /sub/<sub_token>. Не привязан
    # к telegram_id, чтобы ссылку можно было спокойно передавать/логировать.
    # Ссылка охватывает ВСЕ устройства пользователя и не меняется ни при
    # добавлении устройства, ни при добавлении сервера.
    sub_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_new_sub_token)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tariff: Mapped[str] = mapped_column(String(32), default="standard")

    trial_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Базовый лимит устройств для тарифа + купленные доп. места. Итоговый
    # лимит = DEFAULT_MAX_DEVICES (из settings) + extra_devices, ровно как
    # в исходном проекте (3 + user.extra_devices).
    extra_devices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
