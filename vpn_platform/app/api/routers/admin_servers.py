"""
app/api/routers/admin_servers.py
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
