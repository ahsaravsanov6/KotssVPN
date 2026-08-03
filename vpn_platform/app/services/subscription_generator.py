"""
app/services/subscription_generator.py

Строит тело подписки (список vless://-ссылок) из пар (Device, сервера
этого устройства). Используется двояко:

  * build_body([(device1, servers1), (device2, servers2), ...]) —
    подписка на ВСЕ устройства сразу (сохранено для отладки/обратной
    совместимости, см. GET /sub/{token});
  * build_body([(device, servers)]) — подписка ОДНОГО устройства
    (именно так строится персональная ссылка, которую видит пользователь
    в боте, см. SubscriptionService.build_device_subscription и
    GET /sub/{token}/{device_id}).

Функция одна и та же в обоих случаях — единственная разница в том,
сколько пар (device, servers) в неё передают.
"""

import base64

from app.db.models.device import Device
from app.db.models.user import User
from app.servers_config import ServerConfig as Server
from app.utils.vless import build_vless_uri


class SubscriptionGenerator:
    @staticmethod
    def build_body(devices_with_servers: list[tuple[Device, list[Server]]]) -> str:
        uris: list[str] = []
        for device, servers in devices_with_servers:
            uris.extend(build_vless_uri(server, device) for server in servers)

        raw = "\n".join(uris)
        return base64.b64encode(raw.encode("utf-8")).decode("ascii")

    @staticmethod
    def build_userinfo_header(user: User) -> str:
        if not user.subscription_expires_at:
            return "upload=0; download=0; total=0"
        expire_ts = int(user.subscription_expires_at.timestamp())
        return f"upload=0; download=0; total=0; expire={expire_ts}"
