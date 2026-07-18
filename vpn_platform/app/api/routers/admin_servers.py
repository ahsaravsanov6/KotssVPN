"""
app/api/routers/admin_servers.py

Список серверов правится ВРУЧНУЮ, редактированием servers.yaml по SSH
(см. app/servers_config.py) — при ожидаемых единицах серверов отдельный
API/CLI для create/update/delete избыточен и дублирует то, что `nano`
уже умеет.

Здесь остались только ТРИ эндпоинта — каждый устраняет конкретный
источник ошибок ручного редактирования, а не дублирует `nano`:

  * GET  /admin/servers            — если в файле синтаксическая ошибка,
                                      yaml.safe_load упадёт здесь, сразу
                                      после правки, а не при следующей
                                      реальной оплате/добавлении устройства.
  * POST /admin/servers/{id}/health — логин на панель + список инбаундов,
                                      без побочных эффектов. Ловит опечатку
                                      в pass/address/inbound_id ДО того,
                                      как на сервер попытаются провижинить
                                      первого реального пользователя.
  * POST /admin/servers/{id}/autofill — читает sni/reality-ключи/порт/flow
                                      прямо из конфигурации инбаунда на
                                      панели и дописывает их в servers.yaml.
                                      Убирает самый ошибкоёмкий шаг ручного
                                      заполнения — перенос base64 Reality-
                                      ключа руками.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import verify_admin_key
from app.providers.registry import get_provider
from app.services.server_manager import ServerManager

router = APIRouter(prefix="/admin/servers", tags=["admin"], dependencies=[Depends(verify_admin_key)])


@router.get("")
async def list_servers():
    servers = ServerManager().list_all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "country": s.country,
            "address": s.address,
            "status": s.status,
            "priority": s.priority,
            "panel_type": s.panel_type,
            "is_fully_configured": s.is_fully_configured,
        }
        for s in servers
    ]


@router.post("/{server_id}/health")
async def check_server_health(server_id: str):
    """
    Проверяет, что креды/адрес панели рабочие, без побочных эффектов на
    самой панели (только логин + чтение списка инбаундов).
    """
    manager = ServerManager()
    server = manager.get_by_id(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    provider = get_provider(server.panel_type)
    result = await provider.health_check(server)
    return {
        "healthy": result.healthy,
        "detail": result.detail,
        "inbounds_on_panel": result.inbound_ids,
    }


@router.post("/{server_id}/autofill")
async def autofill_server_technical_config(server_id: str):
    """
    Дочитывает sni/reality_public_key/reality_short_id/port/flow/fingerprint
    прямо из конфигурации инбаунда на панели и записывает их в servers.yaml.
    Требует, чтобы сервер уже существовал в файле хотя бы с
    id/name/country/address/panel_base_url/panel_username/panel_password/
    inbound_id (остальное можно оставить как есть — значения по умолчанию).

    Поддерживает только Reality-инбаунды (security: reality) — если у вас
    другой тип шифрования транспорта, автозаполнение вернёт понятную
    ошибку, и эти поля придётся заполнить вручную.

    До первого успешного вызова сервер не участвует в провижининге
    (см. ServerConfig.is_active) — недозаполненный сервер физически не
    может попасть в подписку пользователя.
    """
    manager = ServerManager()
    server = manager.get_by_id(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    provider = get_provider(server.panel_type)
    result = await provider.fetch_technical_config(server)
    if not result.success:
        raise HTTPException(status_code=502, detail=result.message)

    updated = manager.apply_technical_config(
        server_id,
        port=result.port,
        sni=result.sni,
        reality_public_key=result.reality_public_key,
        reality_short_id=result.reality_short_id,
        flow=result.flow,
        fingerprint=result.fingerprint,
    )

    return {
        "success": True,
        "is_fully_configured": updated.is_fully_configured,
        "server": {
            "id": updated.id,
            "port": updated.port,
            "sni": updated.sni,
            "reality_public_key": updated.reality_public_key,
            "reality_short_id": updated.reality_short_id,
            "flow": updated.flow,
            "fingerprint": updated.fingerprint,
        },
    }
