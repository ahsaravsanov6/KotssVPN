"""
analytics/config.py — настройки модуля аналитики.

Полностью отдельный конфиг от основного бота: читает свой .env
(analytics/.env), не трогает config.py бота. Единственная точка
пересечения с ботом — путь к его БД (BOT_DB_PATH), которую этот
модуль открывает ТОЛЬКО НА ЧТЕНИЕ.
"""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class AnalyticsSettings:
    # ── Путь к БД бота (read-only) и собственной БД аналитики ──────────────
    BOT_DB_PATH: str = os.getenv("BOT_DB_PATH", str(BASE_DIR.parent / "vpn_bot.db"))
    ANALYTICS_DB_PATH: str = os.getenv("ANALYTICS_DB_PATH", str(BASE_DIR / "analytics.db"))

    # ── 3X-UI ────────────────────────────────────────────────────────────────
    XUI_BASE_URL: str = os.getenv("XUI_BASE_URL", "")
    XUI_USERNAME: str = os.getenv("XUI_USERNAME", "")
    XUI_PASSWORD: str = os.getenv("XUI_PASSWORD", "")

    # ── Периодичность сбора (секунды) ───────────────────────────────────────
    COLLECT_INTERVAL_SECONDS: int = int(os.getenv("COLLECT_INTERVAL_SECONDS", 900))  # 15 минут

    # ── Сколько хранить снапшоты сервера/трафика (дней), чтобы БД не росла бесконечно ──
    RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS", 180))

    # ── Веб-панель ───────────────────────────────────────────────────────────
    WEB_HOST: str = os.getenv("WEB_HOST", "127.0.0.1")
    WEB_PORT: int = int(os.getenv("WEB_PORT", 8082))

    # Логин/пароль (Basic Auth) — задаются в .env, дефолт небезопасный нарочно,
    # чтобы сразу было видно, что их нужно сменить.
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

    # Секретный токен в URL (?token=...), второй слой защиты.
    # Если не задан в .env — генерируется один раз и выводится в лог при старте,
    # чтобы не оставлять панель открытой по умолчанию.
    SECRET_TOKEN: str = os.getenv("SECRET_TOKEN", "secret")

    # За белым списком прокси (nginx) укажите True, чтобы корректно читать IP
    BEHIND_PROXY: bool = _bool("BEHIND_PROXY", True)


settings = AnalyticsSettings()

if not settings.SECRET_TOKEN:
    settings.SECRET_TOKEN = secrets.token_urlsafe(24)
    _GENERATED_TOKEN_WARNING = True
else:
    _GENERATED_TOKEN_WARNING = False
