"""
app/utils/vless.py — сборка vless:// URI без обращения к панели.
"""

from urllib.parse import quote

from app.db.models.device import Device
from app.servers_config import ServerConfig as Server


def build_vless_uri(server: Server, device: Device) -> str:
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
