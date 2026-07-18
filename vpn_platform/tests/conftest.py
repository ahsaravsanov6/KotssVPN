"""
tests/conftest.py — фабрики in-memory объектов для тестов чистой логики
(vless.py, subscription_generator.py). Никакой БД здесь не поднимается —
Server (ServerConfig, обычный dataclass — не ORM)/User/Device достаточно
сконструировать в памяти.
"""

from datetime import datetime, timedelta

import pytest

from app.db.models.device import Device
from app.db.models.user import User
from app.servers_config import ServerConfig


@pytest.fixture
def sample_server() -> ServerConfig:
    return ServerConfig(
        id="nl-1",
        name="Test Server",
        country="NL",
        address="test.example.com",
        port=443,
        sni="www.microsoft.com",
        reality_public_key="pk_test_value",
        reality_short_id="ab12",
        flow="xtls-rprx-vision",
        fingerprint="chrome",
        panel_type="3x-ui",
        panel_base_url="https://panel.example.com:2053",
        panel_username="admin",
        panel_password="secret",
        inbound_id=1,
    )


@pytest.fixture
def sample_user() -> User:
    return User(
        id=1,
        telegram_id=123456789,
        sub_token="test-sub-token",
        is_active=True,
        subscription_expires_at=datetime.utcnow() + timedelta(days=10),
        tariff="standard",
    )


@pytest.fixture
def sample_device(sample_user) -> Device:
    return Device(
        id=1,
        user_id=sample_user.id,
        device_name="iPhone",
        uuid="11111111-2222-3333-4444-555555555555",
    )
