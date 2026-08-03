"""
app/servers_config.py — сервера как данные файла, не таблицы БД.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

from app.config import settings


class PanelType(str, Enum):
    XUI = "3x-ui"


class ServerStatus(str, Enum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    DISABLED = "disabled"


@dataclass
class ServerConfig:
    id: str
    name: str
    country: str
    address: str

    sni: str = ""
    reality_public_key: str = ""
    port: int = 443
    reality_short_id: str = ""
    flow: str = "xtls-rprx-vision"
    fingerprint: str = "chrome"

    panel_type: str = PanelType.XUI.value
    panel_base_url: str = ""
    panel_username: str = ""
    panel_password: str = ""
    inbound_id: int = 1

    status: str = ServerStatus.ACTIVE.value
    priority: int = 100
    max_clients: Optional[int] = None

    @property
    def is_fully_configured(self) -> bool:
        return bool(self.sni and self.reality_public_key)

    @property
    def is_active(self) -> bool:
        return self.status == ServerStatus.ACTIVE.value and self.is_fully_configured

    def remark_for(self, device_name: str) -> str:
        return f"{device_name} · {self.name} ({self.country})"


_REQUIRED_FIELDS = {
    "id", "name", "country", "address",
    "panel_base_url", "panel_username", "panel_password", "inbound_id",
}
_KNOWN_FIELDS = {f.name for f in fields(ServerConfig)}


def _servers_file_path() -> Path:
    return Path(settings.SERVERS_FILE)


def load_all() -> dict[str, ServerConfig]:
    path = _servers_file_path()
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    entries = raw.get("servers") or []
    result: dict[str, ServerConfig] = {}

    for entry in entries:
        unknown = set(entry.keys()) - _KNOWN_FIELDS
        if unknown:
            raise ValueError(f"servers-файл: неизвестные поля у сервера {entry.get('id', '?')}: {unknown}")

        missing = _REQUIRED_FIELDS - entry.keys()
        if missing:
            raise ValueError(f"servers-файл: у сервера {entry.get('id', '?')} не хватает полей: {missing}")

        server = ServerConfig(**entry)
        if server.id in result:
            raise ValueError(f"servers-файл: дублирующийся id сервера: {server.id!r}")
        result[server.id] = server

    return result


def save_all(servers: dict[str, ServerConfig]) -> None:
    path = _servers_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {"servers": [_server_to_dict(s) for s in servers.values()]}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    try:
        path.chmod(0o600)
    except OSError:
        pass


def _server_to_dict(server: ServerConfig) -> dict:
    return {f.name: getattr(server, f.name) for f in fields(server)}
