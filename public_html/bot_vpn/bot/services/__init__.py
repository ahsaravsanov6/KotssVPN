# Файл: bot/services/__init__.py
from bot.services.api_client import APIClient, BackendAPIError, api_client

__all__ = ["APIClient", "BackendAPIError", "api_client"]
