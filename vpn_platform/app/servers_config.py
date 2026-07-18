"""
app/servers_config.py — сервера как данные файла, не таблицы БД.

Решение: при ожидаемом масштабе (единицы, максимум десятки серверов)
полноценная таблица с Alembic-миграциями на каждое изменение схемы —
избыточна. Список серверов меняется редко, руками, обычно одним
администратором по SSH — плоский файл проще редактировать напрямую
(`nano`), не требует накатывать миграцию ради добавления поля, и его
проще целиком продублировать/забэкапить одной командой `cp`.

Формат — YAML, путь берётся из settings.SERVERS_FILE (по умолчанию вне
репозитория, см. app/config.py) и НЕ ХОДИТ через `.env` построчно,
потому что список серверов — это структурированные записи с вложенными
полями (адрес, reality-ключи, креды панели), а не плоские KEY=VALUE.

ВАЖНО: этот файл содержит пароли от панелей 3X-UI открытым текстом —
права на него должны быть выставлены так же строго, как на `.env`
(рекомендуется `chmod 600`), и он никогда не должен попадать в git
(см. `.gitignore`).

Технические поля (sni, reality_public_key, reality_short_id, port, flow,
fingerprint) можно не заполнять вручную — панель уже хранит их в
конфигурации инбаунда. Впишите только id/name/country/address и креды
доступа к панели (panel_base_url/username/password + inbound_id), затем
вызовите `POST /admin/servers/{id}/autofill` — технические поля
подтянутся прямо с панели и запишутся сюда же (см.
`PanelProvider.fetch_technical_config` и `ServerManager.apply_technical_config`).
Пока эти поля пусты, сервер не участвует в провижининге (см.
`ServerConfig.is_active`), чтобы случайно не выдать пользователю
нерабочую vless-ссылку.

DeviceServerAccess.server_id ссылается на ServerConfig.id (строка-слаг,
например "nl-1"), не на автоинкрементный id таблицы — потому что такой
таблицы больше не существует. Валидность server_id на момент
провижининга проверяется в рантайме через ServerManager.get_by_id(),
а не внешним ключом СУБД.
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
    # будущие провайдеры добавляются сюда и в providers/registry.py,
    # бизнес-логика (ProvisioningService) не меняется


class ServerStatus(str, Enum):
    ACTIVE = "active"        # доступен для новых подключений
    MAINTENANCE = "maintenance"  # существующие клиенты работают, новых не добавляем
    DISABLED = "disabled"    # полностью выведен из ротации


@dataclass
class ServerConfig:
    id: str  # слаг, уникальный в пределах файла, напр. "nl-1"; НЕ меняется после создания
    name: str
    country: str
    address: str

    # ── Подключение клиента (то, что попадёт в vless://) ────────────────────
    # Оставлены пустыми по умолчанию — заполняются либо руками, либо
    # автоматически через PanelProvider.fetch_technical_config() (см.
    # /admin/servers/{id}/autofill). Пока пусты — сервер считается
    # НЕ полностью настроенным и никогда не участвует в провижининге
    # устройств (см. is_fully_configured/is_active ниже), чтобы не
    # выпустить пользователю заведомо нерабочую vless-ссылку.
    sni: str = ""
    reality_public_key: str = ""
    port: int = 443
    reality_short_id: str = ""
    flow: str = "xtls-rprx-vision"
    fingerprint: str = "chrome"

    # ── Подключение к панели управления этим сервером (Provisioning) ───────
    panel_type: str = PanelType.XUI.value
    panel_base_url: str = ""
    panel_username: str = ""
    panel_password: str = ""
    inbound_id: int = 1

    # ── Состояние/приоритет ─────────────────────────────────────────────────
    status: str = ServerStatus.ACTIVE.value
    priority: int = 100
    max_clients: Optional[int] = None

    @property
    def is_fully_configured(self) -> bool:
        """True, когда есть всё необходимое, чтобы честно собрать
        vless://-ссылку. Заполняется либо руками, либо автозаполнением."""
        return bool(self.sni and self.reality_public_key)

    @property
    def is_active(self) -> bool:
        """Сервер участвует в провижининге только когда И статус active,
        И технические поля заполнены — недозаполненный "черновик" сервера
        (только что добавленный id/name/address/креды панели, до
        автозаполнения) никогда не попадёт в подписку пользователя."""
        return self.status == ServerStatus.ACTIVE.value and self.is_fully_configured

    def remark_for(self, device_name: str) -> str:
        """Человекочитаемое имя в клиенте (после # в vless://)."""
        return f"{device_name} · {self.name} ({self.country})"


_REQUIRED_FIELDS = {
    "id", "name", "country", "address",
    "panel_base_url", "panel_username", "panel_password", "inbound_id",
}
_KNOWN_FIELDS = {f.name for f in fields(ServerConfig)}


def _servers_file_path() -> Path:
    return Path(settings.SERVERS_FILE)


def load_all() -> dict[str, ServerConfig]:
    """
    Читает файл заново при КАЖДОМ вызове (не кэшируется на уровне
    процесса) — намеренно: список серверов настолько мал, что разбор
    YAML занимает доли миллисекунды, а взамен изменения в файле
    подхватываются сразу, без перезапуска API.
    """
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
        path.chmod(0o600)  # тот же уровень защиты, что у .env — тут тоже пароли от панелей
    except OSError:
        pass  # на некоторых ФС chmod недоступен — не критично


def _server_to_dict(server: ServerConfig) -> dict:
    return {f.name: getattr(server, f.name) for f in fields(server)}
