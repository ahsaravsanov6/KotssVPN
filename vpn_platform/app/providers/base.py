"""
app/providers/base.py — контракт "панели управления сервером".

ProvisioningService (business logic) знает только этот интерфейс.
Он никогда не импортирует httpx, ничего не знает про cookie/csrf 3X-UI,
про формат ответа /panel/api/clients/get/{email} и т.п. — это дело
конкретной реализации (providers/xui/client.py).

Если завтра появится второй тип панели (Marzban, Marzneshin, свой
Xray-агент) — она просто реализует этот же интерфейс и регистрируется
в providers/registry.py. Business logic не меняется ни на строку.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from app.db.models.device import Device
from app.servers_config import ServerConfig as Server


@dataclass
class ProvisionResult:
    success: bool
    remote_id: Optional[str] = None   # email/идентификатор клиента в панели
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
    """Результат чтения технических параметров инбаунда с панели —
    то, чем автоматически заполняются sni/reality_public_key/... в
    servers.yaml вместо ручного набора (см. ServerManager.apply_technical_config,
    POST /admin/servers/{id}/autofill)."""
    success: bool
    port: Optional[int] = None
    sni: Optional[str] = None
    reality_public_key: Optional[str] = None
    reality_short_id: Optional[str] = None
    flow: Optional[str] = None
    fingerprint: Optional[str] = None
    message: str = ""


class PanelProvider(ABC):
    """Провижининг клиента ОДНОГО устройства на ОДНОМ сервере. Ничего не
    знает про подписку, тарифы, лимиты — чистый adapter к панели."""

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
        """Неразрушающая проверка доступности панели (логин + чтение конфигурации),
        без создания/изменения/удаления клиентов. Используется сразу после
        добавления сервера, чтобы поймать опечатку в кредах до того, как на
        сервер попытаются провижинить первого реального пользователя."""

    @abstractmethod
    async def fetch_technical_config(self, server: Server) -> TechnicalConfigResult:
        """
        Читает с панели то, что технически необходимо для сборки
        vless://-ссылки (sni/reality-ключи/порт/flow/fingerprint) — вместо
        того, чтобы требовать это ручным вводом. Требует только уже
        рабочих panel_base_url/username/password/inbound_id (то есть
        сначала должен пройти health_check). Без побочных эффектов на
        панели — только чтение конфигурации инбаунда."""
