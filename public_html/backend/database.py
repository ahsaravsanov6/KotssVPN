from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from config import settings
from datetime import datetime, timedelta

engine = create_engine(settings.DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=False)
    subscription_expires_at = Column(DateTime, nullable=True)

    # Кто пригласил этого пользователя (telegram_id реферера).
    # Заполняется один раз при регистрации через /start ref_<id> и больше не меняется.
    referrer_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=True)

    # Сколько дополнительных мест под устройства куплено сверх базового лимита
    # (settings.DEFAULT_MAX_DEVICES). Растёт на 1 при каждой подтверждённой
    # оплате доп. устройства (см. /devices/buy_slot) и НИКОГДА не уменьшается
    # автоматически — это аудиторский счётчик факта оплаты, а не текущий
    # остаток. Итоговый лимит устройств пользователя = 3 + extra_devices.
    extra_devices = Column(Integer, default=0, nullable=False)

    devices = relationship("Device", back_populates="owner", foreign_keys="Device.user_id")


class Device(Base):
    """
    Зарегистрированное устройство пользователя.

    С переходом на модель "один VLESS-клиент в 3X-UI = одно устройство"
    каждая строка Device хранит не только название, введённое пользователем,
    но и реальные идентификаторы VPN-клиента в панели:

        vpn_email   — уникальный email клиента в 3X-UI (используется как
                      ключ поиска через /panel/api/clients/get/{email})
        vpn_uuid    — UUID клиента (используется при удалении/обновлении)
        vpn_sub_id  — subId клиента (используется для subscription-ссылки)

    Это превращает лимит устройств из декларативной записи в БД в реальное
    техническое ограничение: добавить устройство сверх лимита невозможно,
    потому что бэкенд физически не создаст лишний VPN-клиент в панели.
    Удаление устройства реально отзывает доступ (удаляет клиента из панели),
    а не просто прячет строку в таблице.

    vpn_* поля nullable, чтобы не ломать уже существующие записи устройств,
    созданные до этой миграции (старые устройства без привязанного ключа
    обрабатываются отдельно — см. комментарий в main.py /devices/add).
    """
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.telegram_id"))
    device_name = Column(String)

    vpn_email = Column(String, nullable=True, unique=True)
    vpn_uuid = Column(String, nullable=True)
    vpn_sub_id = Column(String, nullable=True)

    owner = relationship("User", back_populates="devices", foreign_keys=[user_id])


class Referral(Base):
    """
    Реферальная связь "пригласивший → приглашённый" и статус бонуса.

    Одна строка на одного приглашённого (referred_id уникален) — это и есть
    гарантия, что бонус 7 дней начислится рефереру максимум один раз,
    даже если вебхук платёжки придёт повторно (что у платёжек бывает).

    bonus_granted переключается в True ровно в момент первой успешной
    оплаты подписки приглашённым (см. /subscription/buy в main.py).
    Если оплата случится снова — bonus_granted уже True, начисление
    не повторяется.
    """
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, index=True)
    referred_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.now)
    bonus_granted = Column(Boolean, default=False)
    bonus_granted_at = Column(DateTime, nullable=True)
    bonus_days = Column(Integer, default=7)


# Создаем таблицы
Base.metadata.create_all(bind=engine)

# Миграция для уже существующих БД: Base.metadata.create_all не добавляет
# колонки в уже существующую таблицу (CREATE TABLE IF NOT EXISTS не трогает
# схему), поэтому добавляем extra_devices явным ALTER TABLE, если её ещё нет.
with engine.connect() as _conn:
    _existing_cols = {row[1] for row in _conn.exec_driver_sql("PRAGMA table_info(users)")}
    if "extra_devices" not in _existing_cols:
        _conn.exec_driver_sql("ALTER TABLE users ADD COLUMN extra_devices INTEGER NOT NULL DEFAULT 0")
        _conn.commit()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
