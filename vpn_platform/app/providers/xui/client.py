"""
app/providers/xui/client.py — реализация PanelProvider для панели 3X-UI.

Провижининг теперь идёт на уровне Device, а не User (см. обсуждение
лимита устройств: единый UUID на пользователя стирал механику лимита
из исходного проекта). Отличия от версии "один UUID на пользователя":

  * remote_id строится из device.uuid, а не user.uuid;
  * limitIp снова = 1, как в исходном xui_service.py.create_user —
    лимит одновременных устройств пользователя технически обеспечивается
    и на панели тоже (не только проверкой количества строк Device в БД
    при добавлении), ровно как было в проекте до этого рефакторинга;
  * create_client всё так же не доверяет панели вслепую: после создания
    клиента читает его обратно и принудительно фиксирует UUID через
    update, если панель проигнорировала переданный id.
"""

import asyncio
import json
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.db.models.device import Device
from app.servers_config import ServerConfig as Server
from app.providers.base import ClientStats, HealthResult, PanelProvider, ProvisionResult, TechnicalConfigResult

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.75


def remote_id_for(device: Device) -> str:
    """Единая функция построения email-идентификатора клиента в 3X-UI.
    Используется и при создании, и при поиске — чтобы не разойтись.
    Построена из device.uuid (не из telegram_id/device.id), чтобы не
    зависеть от того, что telegram_id пользователя не поменяется."""
    return f"device_{device.uuid}"


def _extract_uuid(client: dict) -> Optional[str]:
    """
    ВАЖНО: порядок проверки полей here критичен и подтверждён на практике
    (см. лог реального прогона против вашей панели: поле "id" в ответе
    GET /clients/get/{email} оказалось внутренним числовым id строки
    клиента в БД панели, например "55" — НЕ VLESS UUID; реальный UUID
    лежал в поле "uuid"). Порядок "uuid первым, id вторым" — тот же самый,
    что был проверенно рабочим в исходном xui_service.py:
    `real_uuid = client.get("uuid") or client.get("id")`. Более ранняя
    версия этого файла проверяла в обратном порядке — это была ошибка,
    из-за которой create_client всегда ложно репортовал "uuid mismatch"
    даже когда панель всё создавала правильно с первого раза.
    """
    return client.get("uuid") or client.get("id")


class _XUISession:
    """Инкапсулирует auth-cookie+csrf+постоянный httpx-клиент для ОДНОГО
    конкретного сервера. Живёт столько же, сколько XUIProvider держит
    его в кэше (весь процесс)."""

    def __init__(self, server: Server) -> None:
        self.server = server
        self._cookies: Optional[dict] = None
        self._csrf: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self.server.panel_base_url.rstrip("/")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(verify=False, timeout=20)
        return self._client

    async def _login(self) -> None:
        client = await self._get_client()
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}

        r = await client.get(self.base_url, headers=headers, follow_redirects=True)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        tag = soup.find("meta", {"name": "csrf-token"})
        if not tag:
            raise RuntimeError(f"CSRF token not found for server {self.server.id} ({self.server.name})")
        self._csrf = tag.get("content")

        login_headers = {**headers, "x-csrf-token": self._csrf, "Content-Type": "application/x-www-form-urlencoded"}
        r = await client.post(
            f"{self.base_url}/login",
            data={"username": self.server.panel_username, "password": self.server.panel_password},
            headers=login_headers,
            follow_redirects=True,
        )
        if r.status_code not in (200, 302):
            raise RuntimeError(f"XUI login failed for server {self.server.id}: HTTP {r.status_code}")

        self._cookies = dict(r.cookies) or dict(client.cookies)
        logger.info("XUI: успешный логин на сервере id=%s (%s)", self.server.id, self.server.name)

    async def request(self, method: str, path: str, json_data: dict | None = None) -> dict:
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with self._lock:
                    if not self._cookies:
                        await self._login()
                    cookies = self._cookies
                    csrf = self._csrf

                client = await self._get_client()
                headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
                if method.upper() != "GET" and csrf:
                    headers["x-csrf-token"] = csrf

                r = await client.request(method, f"{self.base_url}{path}", json=json_data, headers=headers, cookies=cookies)

                if r.status_code in (401, 403):
                    async with self._lock:
                        self._cookies = None
                        await self._login()
                        cookies = self._cookies
                        headers["x-csrf-token"] = self._csrf or ""
                    r = await client.request(method, f"{self.base_url}{path}", json=json_data, headers=headers, cookies=cookies)

                if r.status_code in _RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(f"retryable status {r.status_code}", request=r.request, response=r)

                r.raise_for_status()
                return r.json()

            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS:
                    delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "XUI request retry %d/%d (server=%s %s %s): %s — жду %.1fs",
                        attempt, _MAX_ATTEMPTS, self.server.id, method, path, exc, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                break

        assert last_exc is not None
        raise last_exc

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class XUIProvider(PanelProvider):
    """Один инстанс обслуживает несколько серверов — сессии кэшируются
    по server.id (см. providers/registry.py — используется как синглтон)."""

    def __init__(self) -> None:
        self._sessions: dict[str, _XUISession] = {}

    def _session_for(self, server: Server) -> _XUISession:
        if server.id not in self._sessions:
            self._sessions[server.id] = _XUISession(server)
        return self._sessions[server.id]

    @staticmethod
    def _parse_client(res: dict) -> dict | None:
        obj = res.get("obj")
        if not obj:
            return None
        if isinstance(obj, dict) and "client" in obj:
            return obj["client"]
        if isinstance(obj, dict):
            return obj
        return None

    def _client_payload(self, server: Server, device: Device, remote_id: str) -> dict:
        return {
            "id": device.uuid,
            "flow": server.flow,
            "email": remote_id,
            # limitIp=1: ключ ОДНОГО устройства работает только с одного IP
            # одновременно — ровно та же гарантия, что была в исходном
            # xui_service.create_user. Лимит КОЛИЧЕСТВА устройств
            # обеспечивается отдельно, на уровне DeviceService (проверка
            # количества строк Device перед созданием нового).
            "limitIp": 1,
            "totalGB": 0,
            "expiryTime": 0,
            "enable": True,
        }

    async def _read_back(self, session: _XUISession, remote_id: str) -> Optional[dict]:
        try:
            res = await session.request("GET", f"/panel/api/clients/get/{remote_id}")
        except Exception as exc:
            logger.warning("XUI: не удалось прочитать клиента %s после операции: %s", remote_id, exc)
            return None
        if not res.get("success"):
            return None
        return self._parse_client(res)

    async def create_client(self, server: Server, device: Device) -> ProvisionResult:
        session = self._session_for(server)
        remote_id = remote_id_for(device)

        payload = {"client": self._client_payload(server, device, remote_id), "inboundIds": [server.inbound_id]}

        try:
            res = await session.request("POST", "/panel/api/clients/add", payload)
        except Exception as exc:
            logger.error("XUI create_client failed (server=%s device=%s): %s", server.id, device.id, exc)
            return ProvisionResult(success=False, message=str(exc))

        if not res.get("success"):
            msg = str(res.get("msg", res))
            if "duplicate" not in msg.lower() and "exist" not in msg.lower():
                return ProvisionResult(success=False, message=msg)
            logger.info("XUI create_client: клиент %s уже существовал, сверяю UUID", remote_id)

        # ── Критическая проверка: панель могла проигнорировать переданный id ──
        actual = await self._read_back(session, remote_id)
        if actual is None:
            return ProvisionResult(success=False, message="client not found after create")

        actual_uuid = _extract_uuid(actual)
        if actual_uuid != device.uuid:
            logger.warning(
                "XUI: панель создала клиента %s с uuid=%s вместо ожидаемого %s — принудительно исправляю",
                remote_id, actual_uuid, device.uuid,
            )
            fix = await session.request(
                "POST", f"/panel/api/clients/update/{remote_id}", self._client_payload(server, device, remote_id)
            )
            if not fix.get("success"):
                return ProvisionResult(success=False, message=f"uuid mismatch, force-update failed: {fix}")

            verify = await self._read_back(session, remote_id)
            if not verify or _extract_uuid(verify) != device.uuid:
                return ProvisionResult(success=False, message="uuid mismatch persists after force-update")

        return ProvisionResult(success=True, remote_id=remote_id)

    async def delete_client(self, server: Server, remote_id: str) -> ProvisionResult:
        session = self._session_for(server)
        try:
            res = await session.request("POST", f"/panel/api/clients/del/{remote_id}")
        except Exception as exc:
            logger.error("XUI delete_client failed (server=%s remote_id=%s): %s", server.id, remote_id, exc)
            return ProvisionResult(success=False, message=str(exc))

        if not res.get("success"):
            already_gone = "not found" in str(res.get("msg", "")).lower() or "не найден" in str(res.get("msg", "")).lower()
            if already_gone:
                return ProvisionResult(success=True, message="already absent")
            return ProvisionResult(success=False, message=str(res))

        return ProvisionResult(success=True)

    async def update_client(self, server: Server, device: Device, remote_id: str) -> ProvisionResult:
        session = self._session_for(server)
        payload = self._client_payload(server, device, remote_id)
        try:
            res = await session.request("POST", f"/panel/api/clients/update/{remote_id}", payload)
        except Exception as exc:
            logger.error("XUI update_client failed (server=%s remote_id=%s): %s", server.id, remote_id, exc)
            return ProvisionResult(success=False, message=str(exc))

        if not res.get("success"):
            return ProvisionResult(success=False, message=str(res))

        verify = await self._read_back(session, remote_id)
        if not verify or _extract_uuid(verify) != device.uuid:
            return ProvisionResult(success=False, message="update reported success but uuid did not change")

        return ProvisionResult(success=True, remote_id=remote_id)

    async def get_client_stats(self, server: Server, remote_id: str) -> Optional[ClientStats]:
        session = self._session_for(server)
        client = await self._read_back(session, remote_id)
        if not client:
            return None
        return ClientStats(
            online=False,  # для online-статуса нужен отдельный /inbounds/onlines — не входит в этот вызов
            up_bytes=int(client.get("up", 0) or 0),
            down_bytes=int(client.get("down", 0) or 0),
            enabled=bool(client.get("enable", True)),
        )

    async def health_check(self, server: Server) -> HealthResult:
        session = self._session_for(server)
        try:
            res = await session.request("GET", "/panel/api/inbounds/list")
        except Exception as exc:
            return HealthResult(healthy=False, detail=str(exc))

        if not res.get("success"):
            return HealthResult(healthy=False, detail=str(res))

        inbound_ids = [ib.get("id") for ib in (res.get("obj") or [])]
        detail = "" if server.inbound_id in inbound_ids else (
            f"inbound_id={server.inbound_id} не найден среди {inbound_ids} на панели"
        )
        return HealthResult(healthy=True, detail=detail, inbound_ids=inbound_ids)

    @staticmethod
    def _maybe_parse_json(value) -> dict:
        """streamSettings/settings в ответе 3x-ui бывают то JSON-строкой,
        то уже распарсенным dict — зависит от версии/форка панели.
        Нормализуем к dict в обоих случаях."""
        if isinstance(value, str):
            try:
                return json.loads(value) or {}
            except (json.JSONDecodeError, TypeError):
                return {}
        return value or {}

    async def fetch_technical_config(self, server: Server) -> TechnicalConfigResult:
        session = self._session_for(server)
        try:
            res = await session.request("GET", "/panel/api/inbounds/list")
        except Exception as exc:
            return TechnicalConfigResult(success=False, message=str(exc))

        if not res.get("success"):
            return TechnicalConfigResult(success=False, message=str(res))

        inbound = next(
            (ib for ib in (res.get("obj") or []) if ib.get("id") == server.inbound_id),
            None,
        )
        if inbound is None:
            return TechnicalConfigResult(
                success=False,
                message=f"inbound_id={server.inbound_id} не найден на панели",
            )

        stream = self._maybe_parse_json(inbound.get("streamSettings"))
        if stream.get("security") != "reality":
            return TechnicalConfigResult(
                success=False,
                message=(
                    f"Инбаунд {server.inbound_id} использует security={stream.get('security')!r}, "
                    "а не reality — автозаполнение сейчас поддерживает только Reality-инбаунды"
                ),
            )

        reality = stream.get("realitySettings") or {}
        reality_inner = reality.get("settings") or {}

        server_names = [s for s in (reality.get("serverNames") or []) if s]
        short_ids = [s for s in (reality.get("shortIds") or []) if s]  # пустые short_id панель тоже отдаёт — берём непустые
        public_key = reality_inner.get("publicKey")

        if not server_names or not public_key:
            return TechnicalConfigResult(
                success=False,
                message=(
                    "У инбаунда не заполнены serverNames или publicKey Reality-настроек на самой "
                    "панели — сначала донастройте это в 3X-UI, автозаполнение может только прочитать, не придумать"
                ),
            )

        # flow не хранится на уровне инбаунда — берём с первого существующего
        # клиента, если такой уже есть (частый случай: инбаунд создавался
        # вручную через саму панель до подключения нашей платформы).
        settings_obj = self._maybe_parse_json(inbound.get("settings"))
        clients = settings_obj.get("clients") or []
        flow = next((c.get("flow") for c in clients if c.get("flow")), None)

        return TechnicalConfigResult(
            success=True,
            port=inbound.get("port"),
            sni=server_names[0],
            reality_public_key=public_key,
            reality_short_id=(short_ids[0] if short_ids else ""),
            flow=flow,  # None, если ни у одного клиента flow не задан — ServerManager оставит текущее значение
            fingerprint=reality_inner.get("fingerprint"),
        )

    async def aclose_all(self) -> None:
        """Вызывать при graceful shutdown процесса."""
        for session in self._sessions.values():
            await session.aclose()
