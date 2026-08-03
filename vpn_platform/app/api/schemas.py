"""
app/api/schemas.py — request/response модели.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ── internal (бот) ────────────────────────────────────────────────────────────

class RegisterUserRequest(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    referrer_id: Optional[int] = None


class BuySubscriptionRequest(BaseModel):
    telegram_id: int
    days: Optional[int] = Field(default=None, gt=0, le=3650)


class StartTrialRequest(BaseModel):
    telegram_id: int
    days: Optional[int] = Field(default=None, gt=0, le=90)


class AddDeviceRequest(BaseModel):
    telegram_id: int
    device_name: str = Field(min_length=1, max_length=128)


class RemoveDeviceRequest(BaseModel):
    telegram_id: int
    device_id: int


class RegenerateDeviceKeyRequest(BaseModel):
    telegram_id: int
    device_id: int


class AddServerToDeviceRequest(BaseModel):
    telegram_id: int
    device_id: int
    server_id: str


class BuyDeviceSlotRequest(BaseModel):
    """
    Подтверждённая (после вебхука платёжки) докупка доп. места под
    устройство — аналог public_html/backend/main.py::buy_device_slot,
    только extra_devices теперь на app/db/models/user.py::User.
    """
    telegram_id: int

# Схем для создания/изменения серверов здесь больше нет — список серверов
# правится вручную, редактированием servers.yaml.
