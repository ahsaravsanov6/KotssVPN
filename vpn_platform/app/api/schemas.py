"""
app/api/schemas.py — request/response модели.

Раньше (public_html/backend/main.py) все эндпоинты принимали
`data: dict = Body(...)` и читали поля через `.get(...)` — опечатка в
поле или отсутствующее обязательное значение проявлялись только в виде
500-й или тихого None где-то в середине бизнес-логики. Pydantic-схемы
дают понятную 422-ошибку с указанием, какого именно поля не хватает,
ещё на входе в эндпоинт.
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

# Схем для создания/изменения серверов здесь больше нет — список серверов
# правится вручную, редактированием servers.yaml (см. app/servers_config.py
# и docstring в app/api/routers/admin_servers.py).
