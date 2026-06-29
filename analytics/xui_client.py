"""
analytics/xui_client.py — клиент 3X-UI для целей АНАЛИТИКИ.

Сделан отдельно от bot/services/xui_service.py (который отвечает за
создание/удаление/обновление VPN-клиентов в основном боте), чтобы
модуль аналитики был полностью самодостаточным и не зависел от кода
бота. Логика авторизации та же (cookie + csrf-token через /login),
потому что это требование самой панели, а не выбор бота.

Используемые эндпоинты:
    GET  /panel/api/inbounds/list        — список инбаундов с клиентами
                                            и их трафиком (up/down per-client)
    GET/POST /panel/api/server/status    — CPU/RAM/диск/сеть/uptime сервера.
                                            Подтверждённая схема ответа для
                                            этой панели:
                                              {success, obj: {cpu, mem:{current,
                                              total}, swap:{...}, disk:{current,
                                              total}, netIO:{up,down},
                                              xray:{state,version}, tcpCount,
                                              load:{load1,load5,load15}}}
                                            Полей cpuCores, netTraffic, uptime,
                                            udpCount эта панель НЕ отдаёт —
                                            соответствующие колонки в БД
                                            останутся NULL, это ожидаемо.
    POST /panel/api/inbounds/onlines     — список email онлайн-клиентов
                                            (в некоторых версиях это POST,
                                            а не GET).
"""

import logging
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)

# Кандидаты на путь+метод для статуса сервера, в порядке убывания вероятности.
# Первый вариант подтверждён реальным ответом панели пользователя;
# остальные оставлены как fallback для других версий/форков 3X-UI.
# При первом успешном запросе сохраняем рабочую пару в self._status_endpoint,
# чтобы не перебирать их на каждом цикле сбора.
_STATUS_ENDPOINT_CANDIDATES = [
    ("POST", "/panel/api/server/status"),
    ("GET", "/panel/api/server/status"),
    ("POST", "/server/status"),
    ("GET", "/server/status"),
]


class XUIAnalyticsClient:
    def __init__(self) -> None:
        self.base_url = settings.XUI_BASE_URL.rstrip("/")
        self.username = settings.XUI_USERNAME
        self.password = settings.XUI_PASSWORD
        self._cookies: Optional[dict] = None
        self._csrf: Optional[str] = None
        # Запоминаем рабочую пару (метод, путь) для /server/status после
        # первого успешного запроса, чтобы не перебирать кандидатов каждый раз.
        self._status_endpoint: Optional[tuple[str, str]] = None
        # Аналогично для onlines: True если POST, False если GET сработал.
        self._onlines_method: Optional[str] = None

    async def _login(self) -> dict:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}

        async with httpx.AsyncClient(headers=headers, verify=False, follow_redirects=True, timeout=20) as client:
            r = await client.get(self.base_url)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "html.parser")
            tag = soup.find("meta", {"name": "csrf-token"})
            if not tag:
                raise RuntimeError("CSRF token not found on 3X-UI login page")
            self._csrf = tag.get("content")

            login_headers = {
                **headers,
                "x-csrf-token": self._csrf,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            r = await client.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                headers=login_headers,
            )
            if r.status_code not in (200, 302):
                raise RuntimeError(f"3X-UI login failed: HTTP {r.status_code}")

            self._cookies = dict(client.cookies)
            return self._cookies

    async def _request(self, method: str, path: str, json_data: Any = None, raise_on_404: bool = True) -> dict[str, Any]:
        """
        Универсальный запрос GET/POST с авторизацией и повторным логином
        при истёкшей сессии. Если raise_on_404=False — 404 не считается
        ошибкой авторизации, а просто возвращает httpx.Response для того,
        чтобы вызывающий код мог попробовать следующий путь-кандидат.
        """
        if not self._cookies:
            await self._login()

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        if method.upper() != "GET" and self._csrf:
            headers["x-csrf-token"] = self._csrf

        async with httpx.AsyncClient(cookies=self._cookies, headers=headers, verify=False, timeout=20) as client:
            r = await client.request(method, f"{self.base_url}{path}", json=json_data)

            if r.status_code in (401, 403):
                logger.info("3X-UI session expired, re-authenticating")
                self._cookies = None
                await self._login()
                async with httpx.AsyncClient(cookies=self._cookies, headers=headers, verify=False, timeout=20) as c2:
                    r = await c2.request(method, f"{self.base_url}{path}", json=json_data)

            if r.status_code == 404 and not raise_on_404:
                return {"__http_404__": True}

            r.raise_for_status()
            return r.json()

    async def _get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def get_server_status(self) -> Optional[dict[str, Any]]:
        """
        Возвращает dict с полями cpu/mem/disk/net/... из эндпоинта статуса
        сервера, либо None, если ни один из известных путей не сработал
        (не должно ронять весь коллектор).

        Путь и HTTP-метод отличаются между версиями/форками 3X-UI — при
        первом успешном запросе запоминаем рабочую пару в self._status_endpoint
        и дальше используем её напрямую, без повторного перебора.
        """
        candidates = [self._status_endpoint] if self._status_endpoint else _STATUS_ENDPOINT_CANDIDATES

        for method, path in candidates:
            try:
                res = await self._request(method, path, raise_on_404=False)
            except Exception as exc:
                logger.debug("3X-UI %s %s ошибка: %s", method, path, exc)
                continue

            if res.get("__http_404__"):
                continue

            if not res.get("success"):
                logger.warning("3X-UI %s %s вернул success=false: %s", method, path, res)
                continue

            if not self._status_endpoint:
                self._status_endpoint = (method, path)
                logger.info("3X-UI server status: используем %s %s", method, path)

            return res.get("obj") or {}

        logger.warning(
            "3X-UI: не удалось получить статус сервера ни по одному из известных путей "
            "(%s) — снапшот сервера будет пропущен. Проверьте Swagger вашей панели "
            "(/panel/api/openapi.json) и сообщите реальный путь, если он отличается.",
            ", ".join(f"{m} {p}" for m, p in _STATUS_ENDPOINT_CANDIDATES),
        )
        return None

    async def list_clients_traffic(self) -> list[dict[str, Any]]:
        """
        Возвращает список клиентов со всех инбаундов с их трафиком:
        [{"email": ..., "up": int, "down": int, "enable": bool, "online": bool}, ...]

        Источник: /panel/api/inbounds/list -> каждый inbound содержит
        clientStats (per-client up/down/enable), а список реально онлайн
        клиентов берётся отдельно через /panel/api/inbounds/onlines
        (если недоступен — online просто остаётся False, без падения).
        """
        try:
            res = await self._get("/panel/api/inbounds/list")
        except Exception as exc:
            logger.warning("3X-UI /panel/api/inbounds/list недоступен: %s", exc)
            return []

        if not res.get("success"):
            logger.warning("3X-UI inbounds/list вернул success=false: %s", res)
            return []

        online_emails: set[str] = set()
        onlines_methods = [self._onlines_method] if self._onlines_method else ["POST", "GET"]
        for method in onlines_methods:
            try:
                online_res = await self._request(method, "/panel/api/inbounds/onlines", raise_on_404=False)
                if online_res.get("__http_404__"):
                    continue
                if online_res.get("success") and isinstance(online_res.get("obj"), list):
                    online_emails = set(online_res["obj"])
                    if not self._onlines_method:
                        self._onlines_method = method
                        logger.info("3X-UI onlines: используем %s", method)
                    break
            except Exception as exc:
                logger.debug("3X-UI onlines (%s) недоступен (не критично): %s", method, exc)

        clients: list[dict[str, Any]] = []
        for inbound in res.get("obj") or []:
            for stat in inbound.get("clientStats") or []:
                email = stat.get("email")
                if not email:
                    continue
                clients.append({
                    "email": email,
                    "up": int(stat.get("up") or 0),
                    "down": int(stat.get("down") or 0),
                    "enable": bool(stat.get("enable", True)),
                    "online": email in online_emails,
                })

        return clients


xui_analytics_client = XUIAnalyticsClient()
