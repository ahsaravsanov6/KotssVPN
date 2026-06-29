"""
bot/main.py — Точка входа Telegram бота.

Запуск:
    python -m bot.main
"""

import asyncio
import logging
import logging.config

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.start import router as start_router
from bot.handlers.account import router as account_router
from bot.handlers.vpn import router as vpn_router
from bot.handlers.subscription import router as subscription_router
from bot.handlers.payment import router as payment_router
from bot.handlers.devices import router as devices_router
from bot.handlers.referral import router as referral_router
from bot.handlers.about import router as about_router
from bot.handlers.fallback import router as fallback_router
from bot.services.api_client import api_client
from bot.webhook_server import start_webhook_server
from config import settings


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.FileHandler",
            "formatter": "default",
            "filename": "bot.log",
            "encoding": "utf-8",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"],
    },
    "loggers": {
        "aiogram": {"level": "WARNING"},
        "aiohttp": {"level": "WARNING"},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("=" * 60)
    logger.info("VPN Bot starting...")
    logger.info("Backend URL: %s", settings.backend_url)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    await api_client.start()
    logger.info("API Client started")

    # Порядок важен: fallback_router — ВСЕГДА последним.
    dp.include_router(start_router)
    dp.include_router(subscription_router)
    dp.include_router(payment_router)
    dp.include_router(vpn_router)
    dp.include_router(account_router)
    dp.include_router(devices_router)
    dp.include_router(referral_router)
    dp.include_router(about_router)
    dp.include_router(fallback_router)

    logger.info(
        "Routers registered: start, subscription, payment, vpn, account, devices, referral, about, fallback"
    )

    # Запускаем сервер вебхуков платёжных систем (YooKassa / CryptoBot / Heleket)
    asyncio.create_task(start_webhook_server(bot))

    try:
        bot_info = await bot.get_me()
        logger.info(
            "Bot info: @%s (id=%d name='%s')",
            bot_info.username,
            bot_info.id,
            bot_info.full_name,
        )
    except Exception as exc:
        logger.error("Failed to get bot info: %s", exc)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook deleted, pending updates dropped")
    logger.info("Bot is running. Press Ctrl+C to stop.")
    logger.info("=" * 60)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        logger.info("Bot stopping...")
        await api_client.stop()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt)")
