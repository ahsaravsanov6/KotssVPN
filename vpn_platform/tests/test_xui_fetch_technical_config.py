"""
tests/test_xui_fetch_technical_config.py

Проверяет разбор ответа /panel/api/inbounds/list без сети — подменяем
_XUISession.request, чтобы не тащить в тест реальный httpx/логин.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.providers.xui.client import XUIProvider


def _inbound_response(inbound_id=1, security="reality", server_names=None,
                       public_key="pk_real", short_ids=None, port=443,
                       clients=None, stream_as_string=True):
    server_names = server_names if server_names is not None else ["google.com", "www.google.com"]
    short_ids = short_ids if short_ids is not None else ["", "ab12cd34"]
    clients = clients if clients is not None else []

    stream = {
        "network": "tcp",
        "security": security,
        "realitySettings": {
            "serverNames": server_names,
            "shortIds": short_ids,
            "settings": {"publicKey": public_key, "fingerprint": "chrome"},
        },
    }
    settings = {"clients": clients}

    inbound = {
        "id": inbound_id,
        "port": port,
        "protocol": "vless",
        "streamSettings": json.dumps(stream) if stream_as_string else stream,
        "settings": json.dumps(settings) if stream_as_string else settings,
    }
    return {"success": True, "obj": [inbound]}


@pytest.mark.asyncio
async def test_fetch_technical_config_happy_path(sample_server):
    provider = XUIProvider()
    session = provider._session_for(sample_server)
    session.request = AsyncMock(return_value=_inbound_response())

    result = await provider.fetch_technical_config(sample_server)

    assert result.success
    assert result.port == 443
    assert result.sni == "google.com"          # первый непустой serverName
    assert result.reality_public_key == "pk_real"
    assert result.reality_short_id == "ab12cd34"  # первый НЕпустой short_id, не ""
    assert result.fingerprint == "chrome"


@pytest.mark.asyncio
async def test_fetch_technical_config_picks_flow_from_existing_client(sample_server):
    provider = XUIProvider()
    session = provider._session_for(sample_server)
    session.request = AsyncMock(return_value=_inbound_response(
        clients=[{"email": "someone", "flow": "xtls-rprx-vision"}]
    ))

    result = await provider.fetch_technical_config(sample_server)
    assert result.flow == "xtls-rprx-vision"


@pytest.mark.asyncio
async def test_fetch_technical_config_flow_none_when_no_clients(sample_server):
    """Пустой инбаунд (ни одного клиента ещё не создано) — flow не
    определить, ServerManager.apply_technical_config должен оставить
    текущее значение как есть, не затирая его None/пустотой."""
    provider = XUIProvider()
    session = provider._session_for(sample_server)
    session.request = AsyncMock(return_value=_inbound_response(clients=[]))

    result = await provider.fetch_technical_config(sample_server)
    assert result.success
    assert result.flow is None


@pytest.mark.asyncio
async def test_fetch_technical_config_rejects_non_reality_inbound(sample_server):
    provider = XUIProvider()
    session = provider._session_for(sample_server)
    session.request = AsyncMock(return_value=_inbound_response(security="tls"))

    result = await provider.fetch_technical_config(sample_server)
    assert not result.success
    assert "reality" in result.message.lower()


@pytest.mark.asyncio
async def test_fetch_technical_config_missing_inbound_id(sample_server):
    provider = XUIProvider()
    session = provider._session_for(sample_server)
    session.request = AsyncMock(return_value=_inbound_response(inbound_id=999))

    result = await provider.fetch_technical_config(sample_server)
    assert not result.success
    assert "не найден" in result.message


@pytest.mark.asyncio
async def test_fetch_technical_config_handles_dict_not_string_stream_settings(sample_server):
    """Некоторые версии/форки 3x-ui отдают streamSettings/settings уже
    распарсенным dict, а не JSON-строкой — оба варианта должны работать."""
    provider = XUIProvider()
    session = provider._session_for(sample_server)
    session.request = AsyncMock(return_value=_inbound_response(stream_as_string=False))

    result = await provider.fetch_technical_config(sample_server)
    assert result.success
    assert result.sni == "google.com"


@pytest.mark.asyncio
async def test_fetch_technical_config_missing_public_key(sample_server):
    provider = XUIProvider()
    session = provider._session_for(sample_server)
    session.request = AsyncMock(return_value=_inbound_response(public_key=""))

    result = await provider.fetch_technical_config(sample_server)
    assert not result.success
