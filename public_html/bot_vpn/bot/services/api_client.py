"""
bot/services/api_client.py — HTTP клиент для запросов от бота к Backend API.

Бот НИКОГДА не работает напрямую с БД или VPN.
Все операции проходят через этот клиент.

Использует aiohttp для асинхронных HTTP запросов.
Автоматически добавляет X-API-Key заголовок ко всем запросам.
"""

import logging
from typing import Any, Optional

import aiohttp

from config import settings

logger = logging.getLogger(__name__)


class BackendAPIError(Exception):
    """Исключение при ошибке запроса к Backend API."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API Error {status_code}: {detail}")


class APIClient:
    """
    Асинхронный HTTP клиент для взаимодействия с Backend API.

    Сессия создаётся один раз и переиспользуется.
    Все запросы автоматически содержат X-API-Key.
    """

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._base_url = settings.backend_url
        self._headers = {"X-API-Key": settings.API_KEY, "Content-Type": "application/json"}

    async def start(self) -> None:
        """Создаёт aiohttp сессию. Вызывается при старте бота."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=self._base_url,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
            logger.info("API Client session created. Base URL: %s", self._base_url)

    async def stop(self) -> None:
        """Закрывает aiohttp сессию. Вызывается при остановке бота."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("API Client session closed")

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Выполняет HTTP запрос к Backend API.

        Args:
            method: HTTP метод (GET, POST, DELETE)
            path:   URL путь (например: /users/register)
            json:   Тело запроса в виде словаря
            params: Query параметры

        Returns:
            Словарь с ответом от API

        Raises:
            BackendAPIError: При HTTP ошибке (4xx, 5xx)
            Exception:       При сетевой ошибке
        """
        if not self._session or self._session.closed:
            await self.start()

        url = path
        try:
            async with self._session.request(
                method=method,
                url=url,
                json=json,
                params=params,
            ) as response:
                data = await response.json()

                if response.status >= 400:
                    detail = data.get("detail", str(data))
                    logger.error(
                        "API request failed: %s %s → %d %s",
                        method,
                        path,
                        response.status,
                        detail,
                    )
                    raise BackendAPIError(status_code=response.status, detail=str(detail))

                return data

        except aiohttp.ClientError as exc:
            logger.error("Network error calling %s %s: %s", method, path, exc)
            raise

    # ── Users ─────────────────────────────────────────────────────────────────

    async def register_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        referrer_id: Optional[int] = None,
    ) -> dict:
        """
        POST /users/register

        referrer_id передаётся только при первой регистрации пользователя
        (когда он пришёл по ссылке /start ref_<id>) — backend сам игнорирует
        его, если пользователь уже существует, или если referrer_id невалиден.
        """
        return await self._request(
            "POST",
            "/users/register",
            json={
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "referrer_id": referrer_id,
            },
        )

    async def get_account(self, telegram_id: int) -> dict:
        """GET /users/account/{telegram_id}"""
        return await self._request("GET", f"/users/account/{telegram_id}")

    # ── Subscription ──────────────────────────────────────────────────────────

    async def buy_subscription(self, telegram_id: int) -> dict:
        """POST /subscription/buy"""
        return await self._request(
            "POST",
            "/subscription/buy",
            json={"telegram_id": telegram_id},
        )

    async def start_trial(self, telegram_id: int, days: int) -> dict:
        """
        POST /subscription/trial

        Активирует бесплатный пробный период. Backend сам проверяет,
        что пользователь ещё не использовал триал и не имеет (не имел)
        подписки — повторный вызов вернёт success=False с понятным
        сообщением, а не ошибку.
        """
        return await self._request(
            "POST",
            "/subscription/trial",
            json={"telegram_id": telegram_id, "days": days},
        )

    # ── Referral ──────────────────────────────────────────────────────────────

    async def get_referral_stats(self, telegram_id: int) -> dict:
        """GET /referral/stats/{telegram_id}"""
        return await self._request("GET", f"/referral/stats/{telegram_id}")

    # ── VPN ───────────────────────────────────────────────────────────────────

    async def get_vpn_config(self, telegram_id: int, device_id: int) -> dict:
        """GET /vpn/config/{telegram_id}/{device_id}"""
        return await self._request("GET", f"/vpn/config/{telegram_id}/{device_id}")

    async def regenerate_vpn_key(self, telegram_id: int, device_id: int) -> dict:
        """POST /vpn/regenerate"""
        return await self._request(
            "POST",
            "/vpn/regenerate",
            json={"telegram_id": telegram_id, "device_id": device_id},
        )

    # ── Devices ───────────────────────────────────────────────────────────────

    async def get_devices(self, telegram_id: int) -> dict:
        """GET /devices/{telegram_id}"""
        return await self._request("GET", f"/devices/{telegram_id}")

    async def add_device(self, telegram_id: int, device_name: str) -> dict:
        """POST /devices/add"""
        return await self._request(
            "POST",
            "/devices/add",
            json={"telegram_id": telegram_id, "device_name": device_name},
        )

    async def remove_device(self, telegram_id: int, device_id: int) -> dict:
        """DELETE /devices/remove"""
        return await self._request(
            "DELETE",
            "/devices/remove",
            json={"telegram_id": telegram_id, "device_id": device_id},
        )

    async def buy_device_slot(self, telegram_id: int) -> dict:
        """
        POST /devices/buy_slot

        Подтверждённая оплата дополнительного места под устройство сверх
        базового лимита. Вызывается ТОЛЬКО после подтверждённого вебхука
        платёжной системы — см. process_device_slot_payment в payment.py,
        тот же паттерн, что и buy_subscription.
        """
        return await self._request(
            "POST",
            "/devices/buy_slot",
            json={"telegram_id": telegram_id},
        )


# ── Синглтон клиента ──────────────────────────────────────────────────────────
# Импортируется в хэндлерах бота

api_client = APIClient()