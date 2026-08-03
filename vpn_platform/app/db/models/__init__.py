"""
Импортировать этот модуль обязательно перед create_all_tables()/Alembic —
иначе SQLAlchemy не увидит модели и не создаст таблицы.

Server больше НЕ здесь — сервера с этого момента живут в файле
(см. app/servers_config.py), а не в БД. В таблицах платформы остались
только User, Device, DeviceServerAccess.
"""

from app.db.models.device import Device
from app.db.models.device_server_access import DeviceServerAccess
from app.db.models.user import User

__all__ = ["User", "Device", "DeviceServerAccess"]
