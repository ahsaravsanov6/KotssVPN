"""
app/config.py — единственная точка входа для конфигурации платформы.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    DATABASE_URL: str = Field(
        default="sqlite:////var/lib/vpn-platform/platform.db",
        description="SQLAlchemy DSN. Для прод — postgresql+psycopg://...",
    )

    BOT_TOKEN: str = Field(description="Токен Telegram-бота")

    SERVERS_FILE: str = Field(
        default="/etc/vpn-platform/servers.yaml",
        description="Путь к YAML-файлу со списком серверов (см. app/servers_config.py)",
    )

    API_BASE_URL: str = Field(description="URL, по которому доступен app/api (например http://127.0.0.1:8090)")
    API_ADMIN_KEY: str = Field(description="Секрет для служебных /admin/* и /internal/* эндпоинтов")

    SUBSCRIPTION_PUBLIC_DOMAIN: str = Field(description="Публичный домен без схемы, напр. sub.example.com")

    DEFAULT_TARIFF: str = "standard"
    SUBSCRIPTION_DAYS_DEFAULT: int = 30
    TRIAL_DAYS_DEFAULT: int = 3
    DEFAULT_MAX_DEVICES: int = Field(
        default=3, description="Базовый лимит устройств на пользователя (аналог 3 + extra_devices в исходном проекте)"
    )

    LOG_DIR: Path = Field(default=Path("/var/log/vpn-platform"))
    LOG_LEVEL: str = "INFO"

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
    return PlatformSettings()


settings = get_settings()
