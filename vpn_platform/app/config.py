"""
app/config.py — единственная точка входа для конфигурации платформы.

Важно: здесь НЕТ ничего, что относится к конкретному VPN-серверу
(адреса, reality-ключи, креды панели). Такие параметры живут в таблице
`servers` (см. app/db/models/server.py) и добавляются как данные, а не
как переменные окружения — иначе добавление сервера снова требовало бы
редеплоя.

Здесь только то, что описывает саму платформу: где её БД, как до неё
достучаться боту/апи, какой ключ админки.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    # ── База данных платформы (Single Source of Truth) ─────────────────────
    # По умолчанию путь ВНЕ репозитория — совпадает с требованием "репозиторий
    # содержит только код". В проде — Postgres DSN.
    DATABASE_URL: str = Field(
        default="sqlite:////var/lib/vpn-platform/platform.db",
        description="SQLAlchemy DSN. Для прод — postgresql+psycopg://...",
    )

    # ── Telegram Bot ─────────────────────────────────────────────────────────
    BOT_TOKEN: str = Field(description="Токен Telegram-бота")

    # ── Список серверов (не БД, см. app/servers_config.py) ─────────────────────
    # Путь ВНЕ репозитория по тем же причинам, что и .env — файл содержит
    # пароли от панелей 3X-UI открытым текстом.
    SERVERS_FILE: str = Field(
        default="/etc/vpn-platform/servers.yaml",
        description="Путь к YAML-файлу со списком серверов (см. app/servers_config.py)",
    )

    # ── Внутренний API платформы (бот и админ-скрипты ходят сюда) ─────────────
    API_BASE_URL: str = Field(description="URL, по которому доступен app/api (например http://127.0.0.1:8090)")
    API_ADMIN_KEY: str = Field(description="Секрет для служебных /admin/* эндпоинтов")

    # ── Публичный домен, на котором отдаётся подписка ──────────────────────────
    # Ссылка подписки = f"https://{SUBSCRIPTION_PUBLIC_DOMAIN}/sub/{token}"
    SUBSCRIPTION_PUBLIC_DOMAIN: str = Field(description="Публичный домен без схемы, напр. sub.example.com")

    # ── Бизнес-правила по умолчанию (не завязаны на сервер) ───────────
    DEFAULT_TARIFF: str = "standard"
    SUBSCRIPTION_DAYS_DEFAULT: int = 30
    TRIAL_DAYS_DEFAULT: int = 3
    DEFAULT_MAX_DEVICES: int = Field(
        default=3, description="Базовый лимит устройств на пользователя (аналог 3 + extra_devices в исходном проекте)"
    )

    # ── Логи ─────────────────────────────────────────────────────────────────
    LOG_DIR: Path = Field(default=Path("/var/log/vpn-platform"))
    LOG_LEVEL: str = "INFO"

    # ── Legacy (используется только миграционным скриптом) ─────────────────────
    LEGACY_BOT_DB_PATH: Optional[str] = Field(
        default=None,
        description="Путь к старой vpn_bot.db — нужен только для migrations/migrate_from_legacy.py",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> PlatformSettings:
    """Кэшируем — .env читается один раз за процесс."""
    return PlatformSettings()


settings = get_settings()
