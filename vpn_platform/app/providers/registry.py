"""
app/providers/registry.py

Единственное место во всей платформе, которое знает про существование
конкретных реализаций PanelProvider. ProvisioningService вызывает
только get_provider(server.panel_type) и дальше работает исключительно
через интерфейс PanelProvider — расширение на новый тип панели не
трогает ни ProvisioningService, ни модели, ни API.
"""

from app.providers.base import PanelProvider
from app.providers.xui.client import XUIProvider
from app.servers_config import PanelType

_providers: dict[str, PanelProvider] = {
    PanelType.XUI.value: XUIProvider(),
    # PanelType.MARZBAN.value: MarzbanProvider(),  # future
}


def get_provider(panel_type: str) -> PanelProvider:
    provider = _providers.get(panel_type)
    if provider is None:
        raise ValueError(f"Неизвестный тип панели: {panel_type!r}. Зарегистрируйте его в providers/registry.py")
    return provider
