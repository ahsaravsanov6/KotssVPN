"""
tests/test_device_service.py — единственный тест в наборе, которому
реально нужна база (лимит считается через COUNT(*) в репозитории).
Используется in-memory SQLite, создаётся и уничтожается на каждый тест —
никакого файла на диске, никакой зависимости от .env.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.db.models  # noqa: F401 — регистрирует модели в Base.metadata
from app.db.models.user import User
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
        telegram_id=1,
        subscription_expires_at=datetime.utcnow() + timedelta(days=10),
        is_active=True,
        extra_devices=0,
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_add_device_succeeds_when_under_limit(db_session, active_user):
    service = DeviceService(db_session)
    result = service.add_device(active_user, "iPhone")
    assert result.success
    assert result.device is not None
    assert result.device.device_name == "iPhone"


def test_add_device_fails_without_active_subscription(db_session):
    user = User(telegram_id=2, subscription_expires_at=None, is_active=False)
    db_session.add(user)
    db_session.flush()

    service = DeviceService(db_session)
    result = service.add_device(user, "iPhone")
    assert not result.success
    assert not result.limit_reached  # это другая причина отказа, не лимит


def test_add_device_respects_default_limit(db_session, active_user):
    """Ключевая проверка ради которой всё затевалось: ровно
    DEFAULT_MAX_DEVICES устройств проходят, следующее — limit_reached."""
    from app.config import settings

    service = DeviceService(db_session)
    for i in range(settings.DEFAULT_MAX_DEVICES):
        result = service.add_device(active_user, f"Device {i}")
        assert result.success, f"устройство {i} должно было добавиться"

    over_limit = service.add_device(active_user, "One too many")
    assert not over_limit.success
    assert over_limit.limit_reached
    assert over_limit.max_devices == settings.DEFAULT_MAX_DEVICES


def test_extra_devices_increase_limit(db_session, active_user):
    active_user.extra_devices = 2
    db_session.flush()

    service = DeviceService(db_session)
    assert service.max_devices_for(active_user) == service.max_devices_for(active_user)  # sanity
    from app.config import settings
    assert service.max_devices_for(active_user) == settings.DEFAULT_MAX_DEVICES + 2


def test_unique_device_name_appends_index_on_collision(db_session, active_user):
    service = DeviceService(db_session)
    service.add_device(active_user, "iOS")
    unique_name = service.unique_device_name(active_user, "iOS")
    assert unique_name == "iOS #2"


def test_get_owned_device_returns_none_for_other_users_device(db_session, active_user):
    """Защита от IDOR: пользователь не может получить чужое устройство,
    даже зная его числовой id."""
    other_user = User(telegram_id=999, subscription_expires_at=datetime.utcnow() + timedelta(days=1), is_active=True)
    db_session.add(other_user)
    db_session.flush()

    service = DeviceService(db_session)
    result = service.add_device(other_user, "Foreign Device")
    assert result.success

    stolen = service.get_owned_device(active_user.id, result.device.id)
    assert stolen is None

    legit = service.get_owned_device(other_user.id, result.device.id)
    assert legit is not None
