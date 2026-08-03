"""
bot/services/api_client.py — HTTP клиент бота к vpn_platform (app/api/*).

Заменяет обращения к старому public_html/backend. Все запросы идут в
/internal/* (см. vpn_platform/app/api/routers/internal.py) с заголовком
x-api-key = settings.PLATFORM_API_KEY (должен совпадать с
vpn_platform settings.API_ADMIN_KEY).

Модель подписки: один VLESS-клиент (один UUID) на одно устройство,
но этот клиент реплицируется во ВСЕ активные панели (по одной записи
DeviceServerAccess на сервер) — см. app/services/provisioning_service.py
и app/providers/xui/client.py::remote_id_for на стороне платформы. Для
пользователя это выглядит как раньше: "добавил устройство -> получил
один ключ/ссылку для него", просто внутри эта ссылка теперь охватывает
несколько серверов сразу.

Каждое устройство получает СВОЮ ссылку подписки:
    GET /sub/{user.sub_token}/{device_id}
которую платформа возвращает уже готовой строкой в поле "sub_url"
внутри ответов /internal/devices/*.
"""

import logging
from typing import Any, Optional

import aiohttp

from config import settings

logger = logging.getLogger(__name__)


class BackendAPIError(Exception):
    """Исключение при ошибке запроса к API vpn_platform."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API Error {status_code}: {detail}")


class APIClient:
    """
    Асинхронный HTTP клиент для взаимодействия с vpn_platform (app/api).
    Сессия создаётся один раз и переиспользуется.
    """

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._base_url = settings.PLATFORM_API_URL
        # x-api-key — заголовок, который проверяет verify_admin_key()
        # в vpn_platform/app/api/deps.py (FastAPI Header(...), имя
        # аргумента x_api_key конвертируется в заголовок "x-api-key").
        self._headers = {"x-api-key": settings.PLATFORM_API_KEY, "Content-Type": "application/json"}

    async def start(self) -> None:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                base_url=self._base_url,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
            logger.info("Platform API Client session created. Base URL: %s", self._base_url)

    async def stop(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Platform API Client session closed")

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict[str, Any]:
        if not self._session or self._session.closed:
            await self.start()

        try:
            async with self._session.request(method=method, url=path, json=json, params=params) as response:
                data = await response.json()

                if response.status >= 400:
                    detail = data.get("detail", str(data))
                    logger.error(
                        "Platform API request failed: %s %s → %d %s",
                        method, path, response.status, detail,
                    )
                    raise BackendAPIError(status_code=response.status, detail=str(detail))

                return data

        except aiohttp.ClientError as exc:
            logger.error("Network error calling %s %s: %s", method, path, exc)
            raise

    # ── Users / subscription ─────────────────────────────────────────────────

    async def register_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        referrer_id: Optional[int] = None,
    ) -> dict:
        """POST /internal/users/register"""
        return await self._request(
            "POST",
            "/internal/users/register",
            json={
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "referrer_id": referrer_id,
            },
        )

    async def get_account(self, telegram_id: int) -> dict:
        """GET /internal/users/account/{telegram_id}"""
        return await self._request("GET", f"/internal/users/account/{telegram_id}")

    async def buy_subscription(self, telegram_id: int, days: Optional[int] = None) -> dict:
        """
        POST /internal/subscription/buy

        days — сколько дней покупает пользователь (совпадает с тем, что
        показано на экране оплаты, см. config.SUBSCRIPTION_DAYS). Если не
        передать — backend возьмёт свой SUBSCRIPTION_DAYS_DEFAULT.
        """
        payload: dict[str, Any] = {"telegram_id": telegram_id}
        if days is not None:
            payload["days"] = days
        return await self._request("POST", "/internal/subscription/buy", json=payload)

    async def start_trial(self, telegram_id: int, days: int) -> dict:
        """POST /internal/subscription/trial"""
        return await self._request(
            "POST",
            "/internal/subscription/trial",
            json={"telegram_id": telegram_id, "days": days},
        )

    # ── Referral ──────────────────────────────────────────────────────────────
    # ЗАГЛУШКА: реферальной системы в vpn_platform пока нет (нет модели
    # Referral и начисления бонуса в UserService). Возвращаем нули, чтобы
    # раздел "Пригласить друга" не падал, пока это не перенесено отдельно.
    async def get_referral_stats(self, telegram_id: int) -> dict:
        logger.debug("get_referral_stats: referral system not implemented on vpn_platform yet")
        return {"invited_count": 0, "bonus_days": 0, "pending_count": 0}

    # ── Devices ───────────────────────────────────────────────────────────────

    async def get_devices(self, telegram_id: int) -> dict:
        """
        GET /internal/devices/{telegram_id}

        Возвращает {"success", "devices": [{"id","device_name","sub_url"}...],
        "devices_count", "max_devices"} — у каждого устройства уже есть его
        персональная ссылка подписки (sub_url), отдельный запрос за конфигом
        не нужен.
        """
        return await self._request("GET", f"/internal/devices/{telegram_id}")

    async def add_device(self, telegram_id: int, device_name: str) -> dict:
        """
        POST /internal/devices/add

        Успех: {"success": True, "device_id", "device_number", "sub_url", ...}
        Лимит: {"success": False, "limit_reached": True, "max_devices", "message"}
        """
        return await self._request(
            "POST",
            "/internal/devices/add",
            json={"telegram_id": telegram_id, "device_name": device_name},
        )

    async def remove_device(self, telegram_id: int, device_id: int) -> dict:
        """DELETE /internal/devices/remove"""
        return await self._request(
            "DELETE",
            "/internal/devices/remove",
            json={"telegram_id": telegram_id, "device_id": device_id},
        )

    async def regenerate_device(self, telegram_id: int, device_id: int) -> dict:
        """
        POST /internal/devices/regenerate

        Перевыпускает UUID устройства и обновляет клиента на ВСЕХ серверах,
        где оно провижинено (см. ProvisioningService.regenerate_device_key).
        Сама ссылка (sub_url) не меняется — меняется её содержимое.
        """
        return await self._request(
            "POST",
            "/internal/devices/regenerate",
            json={"telegram_id": telegram_id, "device_id": device_id},
        )

    async def buy_device_slot(self, telegram_id: int) -> dict:
        """POST /internal/devices/buy_slot — докупка доп. места под устройство."""
        return await self._request(
            "POST",
            "/internal/devices/buy_slot",
            json={"telegram_id": telegram_id},
        )


# ── Синглтон клиента ────────────────────────────────────────────────────────
api_client = APIClient()
