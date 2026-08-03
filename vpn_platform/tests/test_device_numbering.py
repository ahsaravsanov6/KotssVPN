"""
tests/test_device_numbering.py

Проверяет ключевую новую логику: у устройства номер (device_number)
соответствует реальному порядку добавления его пользователем, счётчик
монотонен (не переиспользует номера после удаления), и remote_id_for()
строит имя клиента панели по формату "{telegram_id}_device_{N}".
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models  # noqa: F401
from app.db.models.user import User
from app.providers.xui.client import remote_id_for
from app.services.device_service import DeviceService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def active_user(db_session) -> User:
    user = User(
        telegram_id=367482910,
        subscription_expires_at=datetime.utcnow() + timedelta(days=10),
        is_active=True,
        extra_devices=3,  # чтобы лимит не мешал добавить >3 устройств в тесте
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_devices_get_sequential_numbers(db_session, active_user):
    service = DeviceService(db_session)

    d1 = service.add_device(active_user, "iPhone").device
    d2 = service.add_device(active_user, "Android").device
    d3 = service.add_device(active_user, "MacBook").device

    assert (d1.device_number, d2.device_number, d3.device_number) == (1, 2, 3)


def test_device_number_survives_deletion_of_earlier_device(db_session, active_user):
    """
    Удаление устройства №1 не должно приводить к тому, что следующее
    добавленное устройство снова получит номер 1 — нумерация монотонна.
    """
    service = DeviceService(db_session)

    d1 = service.add_device(active_user, "iPhone").device
    service.add_device(active_user, "Android")

    db_session.delete(d1)
    db_session.flush()

    d3 = service.add_device(active_user, "iPad").device
    assert d3.device_number == 3


def test_remote_id_for_uses_telegram_id_and_device_number(db_session, active_user):
    service = DeviceService(db_session)
    device = service.add_device(active_user, "iPhone").device

    assert remote_id_for(device) == f"{active_user.telegram_id}_device_1"


def test_remote_id_for_falls_back_to_device_id_when_number_missing(db_session, active_user):
    """Устройства, перенесённые до появления device_number (legacy), не должны падать."""
    from app.db.models.device import Device

    device = Device(user_id=active_user.id, device_name="Legacy", device_number=None)
    db_session.add(device)
    db_session.flush()

    assert remote_id_for(device) == f"{active_user.telegram_id}_device_{device.id}"
