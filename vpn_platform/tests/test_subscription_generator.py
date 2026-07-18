import base64
from datetime import datetime, timedelta

from app.db.models.device import Device
from app.servers_config import ServerConfig as Server
from app.services.subscription_generator import SubscriptionGenerator


def test_build_body_single_device_single_server(sample_server, sample_device):
    body = SubscriptionGenerator.build_body([(sample_device, [sample_server])])
    decoded = base64.b64decode(body).decode("utf-8")
    lines = decoded.strip().split("\n")

    assert len(lines) == 1
    assert lines[0].startswith(f"vless://{sample_device.uuid}@")


def test_build_body_one_device_two_servers(sample_server, sample_device):
    second = Server(
        id="de-1", name="Second", country="DE", address="de.example.com", port=443,
        sni="www.microsoft.com", reality_public_key="pk2", reality_short_id="cd34",
        flow="xtls-rprx-vision", fingerprint="chrome", panel_type="3x-ui",
        panel_base_url="https://panel2:2053", panel_username="admin",
        panel_password="secret", inbound_id=1,
    )
    body = SubscriptionGenerator.build_body([(sample_device, [sample_server, second])])
    decoded = base64.b64decode(body).decode("utf-8")
    lines = decoded.strip().split("\n")

    assert len(lines) == 2
    assert all(line.startswith(f"vless://{sample_device.uuid}@") for line in lines)


def test_build_body_two_devices_produce_different_uuids(sample_server, sample_device):
    second_device = Device(id=2, user_id=sample_device.user_id, device_name="Android", uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    body = SubscriptionGenerator.build_body([
        (sample_device, [sample_server]),
        (second_device, [sample_server]),
    ])
    decoded = base64.b64decode(body).decode("utf-8")
    lines = decoded.strip().split("\n")

    assert len(lines) == 2
    uuids_in_body = {line.split("@")[0].replace("vless://", "") for line in lines}
    assert uuids_in_body == {sample_device.uuid, second_device.uuid}


def test_build_body_empty_devices_is_valid_empty_subscription():
    body = SubscriptionGenerator.build_body([])
    decoded = base64.b64decode(body).decode("utf-8")
    assert decoded == ""


def test_build_body_device_with_no_servers_contributes_nothing(sample_server, sample_device):
    """Устройство без ни одного провижиненного сервера (например, панель
    была недоступна при добавлении) не должно ронять генерацию подписки —
    просто не добавляет строк."""
    body = SubscriptionGenerator.build_body([(sample_device, [])])
    decoded = base64.b64decode(body).decode("utf-8")
    assert decoded == ""


def test_userinfo_header_contains_expire_when_subscription_active(sample_user):
    header = SubscriptionGenerator.build_userinfo_header(sample_user)
    expected_ts = int(sample_user.subscription_expires_at.timestamp())
    assert f"expire={expected_ts}" in header


def test_userinfo_header_without_expire_when_no_subscription(sample_user):
    sample_user.subscription_expires_at = None
    header = SubscriptionGenerator.build_userinfo_header(sample_user)
    assert "expire" not in header
    assert "total=0" in header


def test_subscription_status_property():
    from app.db.models.user import User

    active_user = User(subscription_expires_at=datetime.utcnow() + timedelta(days=1))
    expired_user = User(subscription_expires_at=datetime.utcnow() - timedelta(days=1))
    none_user = User(subscription_expires_at=None)

    assert active_user.subscription_status == "active"
    assert expired_user.subscription_status == "expired"
    assert none_user.subscription_status == "none"
