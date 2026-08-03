# Файл: bot/handlers/__init__.py
from bot.handlers.start import router as start_router
from bot.handlers.account import router as account_router
from bot.handlers.vpn import router as vpn_router
from bot.handlers.subscription import router as subscription_router
from bot.handlers.devices import router as devices_router
from bot.handlers.referral import router as referral_router

__all__ = [
    "start_router",
    "account_router",
    "vpn_router",
    "subscription_router",
    "devices_router",
    "referral_router",
]
