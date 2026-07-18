"""
tests/test_xui_extract_uuid.py

Регрессионный тест на баг, реально проявившийся на боевой панели:
GET /clients/get/{email} вернул {"id": 55, "uuid": "70eb88f8-..."} —
где "id" оказался внутренним числовым id строки клиента в БД панели,
а НЕ VLESS UUID. _extract_uuid обязана проверять "uuid" первым, иначе
create_client/update_client будут ложно репортовать "uuid mismatch"
на каждом провижининге, даже когда панель всё создала правильно.
"""

from app.providers.xui.client import _extract_uuid


def test_extract_uuid_prefers_uuid_field_over_numeric_id():
    """Именно тот ответ панели, что вызвал реальный сбой в проде."""
    client = {"id": 55, "uuid": "70eb88f8-d6bc-43b0-9625-a56260481fe1", "email": "device_70eb88f8..."}
    assert _extract_uuid(client) == "70eb88f8-d6bc-43b0-9625-a56260481fe1"


def test_extract_uuid_falls_back_to_id_when_uuid_field_missing():
    """Некоторые форки/версии панели вообще не отдают отдельное поле uuid —
    тогда единственный вариант — довериться "id" (как в проверенном
    исходном xui_service.py: `client.get("uuid") or client.get("id")`)."""
    client = {"id": "70eb88f8-d6bc-43b0-9625-a56260481fe1", "email": "device_..."}
    assert _extract_uuid(client) == "70eb88f8-d6bc-43b0-9625-a56260481fe1"


def test_extract_uuid_returns_none_when_both_missing():
    assert _extract_uuid({"email": "device_..."}) is None
