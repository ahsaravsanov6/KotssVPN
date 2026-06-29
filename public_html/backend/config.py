import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    API_KEY = os.getenv("API_KEY")
    DB_URL = "sqlite:///./vpn_bot.db"
    
    XUI_BASE_URL = os.getenv("XUI_BASE_URL")
    XUI_USERNAME = os.getenv("XUI_USERNAME")
    XUI_PASSWORD = os.getenv("XUI_PASSWORD")
    XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID", 1))

    # Новые настройки для реальной ссылки
    XUI_PORT = os.getenv("XUI_PORT", "443")
    XUI_SNI = os.getenv("XUI_SNI", "google.com")
    XUI_PUBLIC_KEY = os.getenv("XUI_PUBLIC_KEY", "")
    XUI_SHORT_ID = os.getenv("XUI_SHORT_ID", "")

    # Настройки subscription-ссылки (Settings -> Subscription Settings в панели 3X-UI)
    XUI_SUB_DOMAIN = os.getenv("XUI_SUB_DOMAIN", "peakpeak.website")
    XUI_SUB_PORT = os.getenv("XUI_SUB_PORT", "2096")
    XUI_SUB_PATH = os.getenv("XUI_SUB_PATH", "/peaksub/")

settings = Settings()
