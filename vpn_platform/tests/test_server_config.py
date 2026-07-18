from app.servers_config import ServerConfig, ServerStatus


def _minimal_server(**overrides) -> ServerConfig:
    base = dict(
        id="nl-1",
        name="Test",
        country="NL",
        address="test.example.com",
        panel_base_url="https://panel:2053",
        panel_username="admin",
        panel_password="secret",
        inbound_id=1,
        status=ServerStatus.ACTIVE.value,
    )
    base.update(overrides)
    return ServerConfig(**base)


def test_server_without_technical_fields_is_not_fully_configured():
    server = _minimal_server()  # sni/reality_public_key не заданы — дефолт ""
    assert not server.is_fully_configured


def test_server_without_technical_fields_is_not_active_even_if_status_active():
    """Ключевой инвариант: черновик сервера (только что вписанный id/name/
    address/креды панели, до autofill/ручного заполнения) никогда не
    должен попасть в провижининг, даже если статус формально 'active'."""
    server = _minimal_server()
    assert server.status == ServerStatus.ACTIVE.value
    assert not server.is_active


def test_server_with_technical_fields_is_active():
    server = _minimal_server(sni="google.com", reality_public_key="pk123")
    assert server.is_fully_configured
    assert server.is_active


def test_server_with_technical_fields_but_maintenance_status_is_not_active():
    server = _minimal_server(sni="google.com", reality_public_key="pk123", status=ServerStatus.MAINTENANCE.value)
    assert server.is_fully_configured
    assert not server.is_active
