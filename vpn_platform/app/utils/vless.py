"""
app/utils/vless.py — сборка vless:// URI без обращения к панели.

Изменено: строится из (Server, Device), не (Server, User) — теперь у
пользователя может быть несколько устройств, у каждого свой UUID и свой
набор серверов, поэтому remark включает имя устройства для наглядности
в клиенте (иначе пользователь не поймёт, какая из десяти строк подписки
относится к его телефону, а какая — к ноутбуку).
"""

from urllib.parse import quote

from app.db.models.device import Device
from app.servers_config import ServerConfig as Server


def build_vless_uri(server: Server, device: Device) -> str:
    """
    Формат параметров соответствует Reality + XTLS-Vision, как это было
    настроено в исходном проекте (см. старый _build_link_fallback).
    """
    remark = quote(server.remark_for(device.device_name))

    query = {
        "type": "tcp",
        "security": "reality",
        "sni": server.sni,
        "fp": server.fingerprint,
        "pbk": server.reality_public_key,
        "sid": server.reality_short_id,
        "flow": server.flow,
    }
    query_str = "&".join(f"{k}={quote(str(v))}" for k, v in query.items() if v)

    return f"vless://{device.uuid}@{server.address}:{server.port}?{query_str}#{remark}"
