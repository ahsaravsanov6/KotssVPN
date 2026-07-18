"""
app/services/subscription_generator.py

Заменяет нативную subscription-фичу 3X-UI. Изменено: раньше тело строилось
из простого списка серверов пользователя (один UUID на всех), теперь —
из списка пар (Device, сервера этого устройства), потому что у каждого
устройства свой UUID и свой, потенциально отличающийся, набор серверов.
Итоговая подписка — это плоский список vless://-ссылок по всем
устройствам сразу, каждая подписана и сервером, и именем устройства
(см. Server.remark_for), чтобы в клиенте было видно, что к чему относится.
"""

import base64

from app.db.models.device import Device
from app.db.models.user import User
from app.servers_config import ServerConfig as Server
from app.utils.vless import build_vless_uri


class SubscriptionGenerator:
    @staticmethod
    def build_body(devices_with_servers: list[tuple[Device, list[Server]]]) -> str:
        """
        devices_with_servers: [(device1, [server_a, server_b]), (device2, [server_a]), ...]
        Возвращает base64-закодированный список vless://-ссылок — то, что
        нужно отдать телом ответа GET /sub/{token}.
        """
        uris: list[str] = []
        for device, servers in devices_with_servers:
            uris.extend(build_vless_uri(server, device) for server in servers)

        raw = "\n".join(uris)
        return base64.b64encode(raw.encode("utf-8")).decode("ascii")

    @staticmethod
    def build_userinfo_header(user: User) -> str:
        """
        Значение заголовка Subscription-Userinfo — многие клиенты (Happ,
        v2rayNG) показывают его как "срок действия/трафик" в интерфейсе.
        Трафик не считаем на этом уровне (агрегация по всем устройствам и
        серверам — отдельная задача через get_client_stats), поэтому
        передаём только expire.
        """
        if not user.subscription_expires_at:
            return "upload=0; download=0; total=0"
        expire_ts = int(user.subscription_expires_at.timestamp())
        return f"upload=0; download=0; total=0; expire={expire_ts}"
