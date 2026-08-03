# Файл: config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    """
    Настройки бота.
    Pydantic автоматически загрузит эти значения из файла .env
    """

    # --- Секретные ключи (Обязательно должны быть в .env) ---
    BOT_TOKEN: str = Field(description="Токен бота из BotFather")

    # --- vpn_platform (новый backend, заменяет public_html/backend) ---
    PLATFORM_API_URL: str = Field(description="URL app/api vpn_platform, напр. http://127.0.0.1:8090")
    PLATFORM_API_KEY: str = Field(description="Секретный ключ vpn_platform (API_ADMIN_KEY)")

    # Публичный домен, на котором отдаётся подписка (для сборки ссылок
    # /sub/<token>/<device_id> самим ботом, если понадобится — обычно
    # достаточно того, что уже приходит из ответа платформы полем sub_url,
    # это поле оставлено на случай, если бот когда-то будет строить ссылку сам).
    SUBSCRIPTION_PUBLIC_DOMAIN: Optional[str] = None

    # --- Настройки подписки (Можно менять в .env или оставить по умолчанию) ---
    SUBSCRIPTION_PRICE: float = 100.0       # Цена подписки
    SUBSCRIPTION_DAYS: int = 30             # Срок подписки в днях
    DEFAULT_MAX_DEVICES: int = 3            # Макс. кол-во устройств по умолчанию

    # --- Пробный период (бесплатные дни для новых пользователей) ---
    TRIAL_ENABLED: bool = False
    TRIAL_DAYS: int = 3

    # --- Цена докупки дополнительного устройства сверх базового лимита ---
    EXTRA_DEVICE_PRICE: float = 50.0

    # --- Прочее ---
    NEWS_CHANNEL_URL: str = "https://t.me/peakpeaknews"
    BOT_USERNAME: Optional[str] = None

    # --- Юридическая информация ---
    OFFER_URL: str = Field(
        default="https://telegra.ph/DOGOVOR-PUBLICHNOJ-OFERTY-06-23",
        description="Ссылка на публичную оферту (telegra.ph)"
    )
    PRIVACY_POLICY_URL: str = Field(
        default="https://telegra.ph/Politika-konfidencialnosti-06-23-71",
        description="Ссылка на политику конфиденциальности (telegra.ph)"
    )

    # --- Раздел «О нас»: реквизиты владельца сервиса ---
    OWNER_FULL_NAME: str = Field(
        default="Карданов Арсенис Амиранович",
        description="ФИО владельца сервиса (физлицо/ИП)"
    )
    OWNER_INN: str = Field(
        default="151312865743",
        description="ИНН владельца сервиса"
    )
    OWNER_OGRNIP: Optional[str] = Field(
        default=None,
        description="ОГРНИП (если зарегистрирован как ИП)"
    )
    OWNER_CONTACT_EMAIL: str = Field(
        default="kardanov443@gmail.com",
        description="Контактный email для юридических вопросов"
    )

    # --- Платёжные системы (опционально, заполняйте по необходимости) ---
    YOOKASSA_SHOP_ID: Optional[str] = None
    YOOKASSA_SECRET_KEY: Optional[str] = None
    CRYPTOBOT_TOKEN: Optional[str] = None
    HELEKET_MERCHANT_ID: Optional[str] = None
    HELEKET_API_KEY: Optional[str] = None

    # Вебхук-сервер для приёма уведомлений об оплате
    WEBHOOK_HOST: str = "0.0.0.0"
    WEBHOOK_PORT: int = 8080
    WEBHOOK_DOMAIN: Optional[str] = None

    # --- Тестовый режим (активирует подписку без оплаты) ---
    TEST_MODE: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()