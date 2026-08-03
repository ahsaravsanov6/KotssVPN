from urllib.parse import parse_qs, unquote, urlparse

from app.servers_config import ServerConfig as Server
from app.utils.vless import build_vless_uri


def test_build_vless_uri_contains_device_uuid(sample_server, sample_device):
    uri = build_vless_uri(sample_server, sample_device)
    assert uri.startswith(f"vless://{sample_device.uuid}@")


def test_build_vless_uri_contains_server_address_and_port(sample_server, sample_device):
    uri = build_vless_uri(sample_server, sample_device)
    parsed = urlparse(uri)
    assert parsed.hostname == sample_server.address
    assert parsed.port == sample_server.port


def test_build_vless_uri_query_params(sample_server, sample_device):
    uri = build_vless_uri(sample_server, sample_device)
    parsed = urlparse(uri)
    query = parse_qs(parsed.query)

    assert query["security"] == ["reality"]
    assert query["sni"] == [sample_server.sni]
    assert query["pbk"] == [sample_server.reality_public_key]
    assert query["sid"] == [sample_server.reality_short_id]
    assert query["flow"] == [sample_server.flow]
    assert query["fp"] == [sample_server.fingerprint]


def test_build_vless_uri_remark_contains_server_and_device_name(sample_server, sample_device):
    uri = build_vless_uri(sample_server, sample_device)
    fragment = unquote(uri.split("#", 1)[1])
    assert sample_server.name in fragment
    assert sample_server.country in fragment
    assert sample_device.device_name in fragment


def test_same_device_different_servers_same_uuid(sample_server, sample_device):
    other = Server(
        id="de-1", name="Second", country="DE", address="second.example.com", port=443,
        sni="www.microsoft.com", reality_public_key="pk2", reality_short_id="cd34",
        flow="xtls-rprx-vision", fingerprint="chrome", panel_type="3x-ui",
        panel_base_url="https://panel2:2053", panel_username="admin",
        panel_password="secret", inbound_id=1,
    )
    uri1 = build_vless_uri(sample_server, sample_device)
    uri2 = build_vless_uri(other, sample_device)

    assert uri1.split("@")[0] == uri2.split("@")[0]
    assert "second.example.com" in uri2
    assert "second.example.com" not in uri1


def test_different_devices_same_server_different_uuid(sample_server, sample_device):
    from app.db.models.device import Device

    other_device = Device(id=2, user_id=sample_device.user_id, device_name="Android", device_number=2, uuid="99999999-8888-7777-6666-555555555555")

    uri1 = build_vless_uri(sample_server, sample_device)
    uri2 = build_vless_uri(sample_server, other_device)

    assert uri1.split("@")[0] != uri2.split("@")[0]
