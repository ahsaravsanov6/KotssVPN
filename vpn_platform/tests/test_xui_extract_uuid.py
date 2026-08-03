"""
tests/test_xui_extract_uuid.py
"""

from app.providers.xui.client import _extract_uuid


def test_extract_uuid_prefers_uuid_field_over_numeric_id():
    client = {"id": 55, "uuid": "70eb88f8-d6bc-43b0-9625-a56260481fe1", "email": "device_70eb88f8..."}
    assert _extract_uuid(client) == "70eb88f8-d6bc-43b0-9625-a56260481fe1"


def test_extract_uuid_falls_back_to_id_when_uuid_field_missing():
    client = {"id": "70eb88f8-d6bc-43b0-9625-a56260481fe1", "email": "device_..."}
    assert _extract_uuid(client) == "70eb88f8-d6bc-43b0-9625-a56260481fe1"


def test_extract_uuid_returns_none_when_both_missing():
    assert _extract_uuid({"email": "device_..."}) is None
