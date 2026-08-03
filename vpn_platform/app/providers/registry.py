"""
app/providers/registry.py
"""

from app.providers.base import PanelProvider
from app.providers.xui.client import XUIProvider
from app.servers_config import PanelType

_providers: dict[str, PanelProvider] = {
    PanelType.XUI.value: XUIProvider(),
}


def get_provider(panel_type: str) -> PanelProvider:
    provider = _providers.get(panel_type)
    if provider is None:
        raise ValueError(f"Неизвестный тип панели: {panel_type!r}. Зарегистрируйте его в providers/registry.py")
    return provider
