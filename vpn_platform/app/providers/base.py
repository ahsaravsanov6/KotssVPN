"""
app/providers/base.py — контракт "панели управления сервером".
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from app.db.models.device import Device
from app.servers_config import ServerConfig as Server


@dataclass
class ProvisionResult:
    success: bool
    remote_id: Optional[str] = None
    message: str = ""


@dataclass
class ClientStats:
    online: bool
    up_bytes: int
    down_bytes: int
    enabled: bool


@dataclass
class HealthResult:
    healthy: bool
    detail: str = ""
    inbound_ids: Optional[list[int]] = None


@dataclass
class TechnicalConfigResult:
    success: bool
    port: Optional[int] = None
    sni: Optional[str] = None
    reality_public_key: Optional[str] = None
    reality_short_id: Optional[str] = None
    flow: Optional[str] = None
    fingerprint: Optional[str] = None
    message: str = ""


class PanelProvider(ABC):
    @abstractmethod
    async def create_client(self, server: Server, device: Device) -> ProvisionResult:
        """Создаёт клиента с device.uuid на этом сервере."""

    @abstractmethod
    async def delete_client(self, server: Server, remote_id: str) -> ProvisionResult:
        """Удаляет клиента по его remote_id (email в терминах 3X-UI)."""

    @abstractmethod
    async def update_client(self, server: Server, device: Device, remote_id: str) -> ProvisionResult:
        """Обновляет клиента (например, после regenerate_uuid) на новый device.uuid."""

    @abstractmethod
    async def get_client_stats(self, server: Server, remote_id: str) -> Optional[ClientStats]:
        """Необязательная телеметрия — не должна ронять провижининг при недоступности."""

    @abstractmethod
    async def health_check(self, server: Server) -> HealthResult:
        """Неразрушающая проверка доступности панели."""

    @abstractmethod
    async def fetch_technical_config(self, server: Server) -> TechnicalConfigResult:
        """Читает с панели технические поля инбаунда."""
