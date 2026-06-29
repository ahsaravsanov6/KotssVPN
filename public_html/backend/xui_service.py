import httpx
import logging
import uuid
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from config import settings

logger = logging.getLogger(__name__)


class XUIClient:
    """
    Stable 3X-UI client (clients-based API)
    """

    def __init__(self):
        self.base_url = settings.XUI_BASE_URL.rstrip("/")
        self.username = settings.XUI_USERNAME
        self.password = settings.XUI_PASSWORD

        self._cookies = None
        self._csrf = None

    # ---------------------------
    # AUTH
    # ---------------------------
    async def _auth(self):
        if self._cookies:
            return self._cookies

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml",
        }

        async with httpx.AsyncClient(
            headers=headers,
            verify=False,
            follow_redirects=True
        ) as client:

            r = await client.get(self.base_url)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "html.parser")
            tag = soup.find("meta", {"name": "csrf-token"})
            if not tag:
                raise Exception("CSRF token not found")

            self._csrf = tag.get("content")

            login_headers = {
                **headers,
                "x-csrf-token": self._csrf,
                "Content-Type": "application/x-www-form-urlencoded",
            }

            r = await client.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                headers=login_headers
            )

            if r.status_code not in (200, 302):
                raise Exception(f"Login failed: {r.text}")

            self._cookies = dict(client.cookies)
            return self._cookies

    # ---------------------------
    # REQUEST LAYER
    # ---------------------------
    async def _request(self, method: str, path: str, json_data=None):
        cookies = await self._auth()

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }

        if method.upper() != "GET" and self._csrf:
            headers["x-csrf-token"] = self._csrf

        async with httpx.AsyncClient(
            cookies=cookies,
            headers=headers,
            verify=False,
            follow_redirects=True
        ) as client:

            r = await client.request(
                method,
                f"{self.base_url}{path}",
                json=json_data,
                timeout=20
            )

            r.raise_for_status()
            return r.json()

    # ---------------------------
    # BUILD SUBSCRIPTION LINK (предпочтительный способ)
    # ---------------------------
    def _build_subscription_link(self, sub_id: str) -> str:
        """
        Собирает ссылку-подписку локально, без запроса к панели.
        Формат зависит от Settings -> Subscription Settings в 3X-UI:
        https://{domain}:{port}{path}{subId}
        """
        domain = settings.XUI_SUB_DOMAIN
        port = settings.XUI_SUB_PORT
        path = settings.XUI_SUB_PATH
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path = path + "/"
        return f"https://{domain}:{port}{path}{sub_id}"

    # ---------------------------
    # VERIFY SUBSCRIPTION LINK
    # ---------------------------
    async def _verify_subscription_link(self, sub_link: str) -> bool:
        """
        Проверяет, что subscription-ссылка реально отдаёт данные
        (sub-сервер запущен и настроен правильно), а не просто
        собрана по шаблону.
        """
        try:
            async with httpx.AsyncClient(verify=False, timeout=10) as client:
                r = await client.get(sub_link)
                if r.status_code != 200:
                    logger.warning(
                        f"Subscription link вернула статус {r.status_code}: {sub_link}"
                    )
                    return False
                if not r.text.strip():
                    logger.warning(f"Subscription link вернула пустой ответ: {sub_link}")
                    return False
                return True
        except Exception as exc:
            logger.warning(f"Subscription link недоступна ({sub_link}): {exc}")
            return False

    # ---------------------------
    # GET VLESS LINK VIA subId (используется только как fallback)
    # ---------------------------
    async def _get_link_by_sub_id(self, sub_id: str) -> str | None:
        """
        Получает готовую VLESS-ссылку с сервера по subId клиента.
        Сервер сам формирует правильные Reality-параметры.
        Используется только если по какой-то причине не удалось
        собрать subscription-ссылку.
        """
        res = await self._request("GET", f"/panel/api/clients/subLinks/{sub_id}")

        obj = res.get("obj")
        if not obj or not isinstance(obj, list) or len(obj) == 0:
            logger.warning(f"subLinks returned empty for subId={sub_id}")
            return None

        return obj[0]

    # ---------------------------
    # PARSE CLIENT FROM GET RESPONSE
    # ---------------------------
    def _parse_client(self, res: dict) -> dict | None:
        """Извлекает dict клиента из ответа GET /clients/get/{email}"""
        obj = res.get("obj")
        if not obj:
            return None
        # Новый формат: obj = {"client": {...}, "inboundIds": [...]}
        if isinstance(obj, dict) and "client" in obj:
            return obj["client"]
        # Старый формат: obj = {...} напрямую
        if isinstance(obj, dict):
            return obj
        return None

    # ---------------------------
    # RESOLVE LINK (subscription -> subLinks -> manual fallback)
    # ---------------------------
    async def _resolve_link(self, sub_id: str | None, fallback_uuid: str) -> str:
        """
        Единая точка получения ссылки для пользователя.
        Порядок попыток:
          1. Subscription-ссылка — собирается локально и ПРОВЕРЯЕТСЯ
             реальным запросом, что sub-сервер действительно отдаёт конфиги
          2. subLinks API панели (старый способ, одиночный конфиг)
          3. Ручная сборка vless-ссылки (последний fallback)
        """
        if sub_id:
            sub_link = self._build_subscription_link(sub_id)
            if await self._verify_subscription_link(sub_link):
                return sub_link
            logger.warning(
                f"Subscription link не прошла проверку для subId={sub_id}, "
                f"пробуем subLinks API"
            )

            link = await self._get_link_by_sub_id(sub_id)
            if link:
                return link

        logger.warning("Используем ручную сборку vless-ссылки (последний fallback)")
        return self._build_link_fallback(fallback_uuid)

    # ---------------------------
    # CREATE USER (per-device client)
    # ---------------------------
    async def create_user(self, telegram_id: int, device_id: int):
        """
        Создаёт отдельный VLESS-клиент в панели для ОДНОГО конкретного
        устройства пользователя (а не общий клиент на всего пользователя).

        email формируется как user_{telegram_id}_dev{device_id} — это
        обеспечивает уникальность ключа поиска в панели на каждое
        устройство и позволяет позже однозначно найти/удалить именно
        этот клиент через delete_user(email).

        limitIp=1: ключ одного устройства может использоваться только
        с одного IP одновременно. Лимит устройств пользователя (например,
        3) тем самым реализуется как 3 независимых клиента по 1 IP каждый,
        а не как один общий клиент с limitIp=3 — иначе три человека могли
        бы делить один ключ одновременно, и лимит устройств был бы
        чисто декларативным.
        """
        email = f"user_{telegram_id}_dev{device_id}"
        sub_id = str(uuid.uuid4()).replace("-", "")[:16]

        payload = {
            "client": {
                "flow": "xtls-rprx-vision",
                "email": email,
                "subId": sub_id,
                "limitIp": 1,
                "totalGB": 0,
                "expiryTime": 0,
                "tgId": telegram_id,
                "enable": True
            },
            "inboundIds": [settings.XUI_INBOUND_ID]
        }

        res = await self._request("POST", "/panel/api/clients/add", payload)
        if not res.get("success"):
            return {"success": False, "message": res}

        # Читаем клиента с сервера — единственный источник истины
        client_res = await self._request("GET", f"/panel/api/clients/get/{email}")
        if not client_res.get("success"):
            return {"success": False, "message": "Client created but failed to retrieve"}

        client = self._parse_client(client_res)
        if not client:
            return {"success": False, "message": "Invalid client data after create"}

        real_uuid = client.get("uuid") or client.get("id")
        real_sub_id = client.get("subId") or sub_id

        if not real_uuid:
            return {"success": False, "message": "Server did not return UUID"}

        # Получаем ссылку: сначала subscription, затем fallback-цепочка
        config_link = await self._resolve_link(real_sub_id, real_uuid)

        return {
            "success": True,
            "uuid": real_uuid,
            "email": email,
            "sub_id": real_sub_id,
            "config": config_link,
        }

    # ---------------------------
    # DELETE USER (отзыв доступа конкретного устройства)
    # ---------------------------
    async def delete_user(self, email: str):
        """
        Удаляет VLESS-клиента из панели по email.

        Вызывается при удалении устройства пользователем в боте —
        в отличие от старой модели, это РЕАЛЬНО отзывает доступ
        (а не просто прячет строку в локальной БД бота), потому что
        конфиг физически удаляется из 3X-UI и сразу перестаёт работать.

        Путь /panel/api/clients/del/{email} соответствует тому же
        email-based роутингу, что уже используется в get_user_config
        (/clients/get/{email}) — для этой версии/форка 3X-UI операции
        с клиентом идут по email, а не по uuid/inboundId.
        """
        res = await self._request("POST", f"/panel/api/clients/del/{email}")

        if not res.get("success"):
            # Если клиента и так уже нет в панели — считаем удаление успешным,
            # чтобы повторный вызов (например, из-за сетевого ретрая) не блокировал
            # удаление устройства в боте.
            already_gone = "not found" in str(res.get("msg", "")).lower() or "не найден" in str(res.get("msg", "")).lower()
            if already_gone:
                return {"success": True, "message": "Client already absent"}
            return {"success": False, "message": res}

        return {"success": True}

    # ---------------------------
    # GET CLIENT CONFIG (по email конкретного device-клиента)
    # ---------------------------
    async def get_user_config(self, email: str):
        res = await self._request("GET", f"/panel/api/clients/get/{email}")

        if not res.get("success"):
            return {"success": False, "message": "not found"}

        client = self._parse_client(res)
        if not client:
            return {"success": False, "message": "not found"}

        user_uuid = client.get("uuid") or client.get("id")
        sub_id = client.get("subId")

        if not user_uuid:
            return {"success": False, "message": "uuid field not found"}

        # Получаем ссылку: сначала subscription, затем fallback-цепочка
        config_link = await self._resolve_link(sub_id, user_uuid)

        return {
            "success": True,
            "uuid": user_uuid,
            "email": client.get("email", email),
            "config": config_link
        }

    # ---------------------------
    # REGENERATE UUID (для конкретного device-клиента по email)
    # ---------------------------
    async def regenerate_user(self, telegram_id: int, email: str):
        # Сначала читаем текущего клиента
        user = await self.get_user_config(email)
        if not user["success"]:
            return user

        new_uuid = str(uuid.uuid4())

        payload = {
            "uuid": new_uuid,
            "flow": "xtls-rprx-vision",
            "email": email,
            "limitIp": 1,
            "totalGB": 0,
            "expiryTime": 0,
            "tgId": telegram_id,
            "enable": True
        }

        res = await self._request("POST", f"/panel/api/clients/update/{email}", payload)
        if not res.get("success"):
            return {"success": False, "message": res}

        # Перечитываем — берём актуальный UUID и ссылку с сервера
        updated = await self.get_user_config(email)
        if not updated["success"]:
            return {"success": False, "message": "UUID updated but failed to re-read client"}

        return {
            "success": True,
            "new_uuid": updated["uuid"],
            "config": updated["config"]
        }

    # ---------------------------
    # FALLBACK LINK BUILDER (ручная сборка vless, последний рубеж)
    # ---------------------------
    def _build_link_fallback(self, uuid_str: str) -> str:
        parsed = urlparse(self.base_url)
        domain = parsed.hostname

        return (
            f"vless://{uuid_str}@{domain}:{settings.XUI_PORT}"
            f"?type=tcp"
            f"&security=reality"
            f"&sni={settings.XUI_SNI}"
            f"&fp=chrome"
            f"&pbk={settings.XUI_PUBLIC_KEY}"
            f"&sid={settings.XUI_SHORT_ID}"
            f"&flow=xtls-rprx-vision"
            f"#MyVPN"
        )


xui_client = XUIClient()
