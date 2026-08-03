"""
app/api/routers/internal.py — эндпоинты, которые дёргает Telegram-бот.

/subscription/buy и /subscription/trial только двигают дату подписки —
провижининг на серверах происходит там же, где и раньше: при добавлении
устройства (/devices/add), теперь сразу на все активные сервера платформы.

ИЗМЕНЕНО (per-device подписка): списки/ответы по устройствам теперь
включают "sub_url" — персональную ссылку ИМЕННО этого устройства
(GET /sub/{token}/{device_id}, см. routers/subscription.py), а не общую
ссылку на всего пользователя. Модель "один UUID на устройство,
реплицированный на несколько панелей" не изменилась — просто у каждого
устройства теперь своя ссылка, как и в исходном UX бота.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, verify_admin_key
from app.api.schemas import (
    AddDeviceRequest,
    AddServerToDeviceRequest,
    BuyDeviceSlotRequest,
    BuySubscriptionRequest,
    RegenerateDeviceKeyRequest,
    RegisterUserRequest,
    RemoveDeviceRequest,
    StartTrialRequest,
)
from app.config import settings
from app.db.repositories.user_repository import UserRepository
from app.services.device_service import DeviceService
from app.services.provisioning_service import ProvisioningService
from app.services.subscription_service import SubscriptionService
from app.services.user_service import UserService

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_admin_key)])


def _subscription_url(sub_token: str) -> str:
    """Ссылка на ВСЕ устройства сразу (сохранена для отладки/обратной совместимости)."""
    return f"https://{settings.SUBSCRIPTION_PUBLIC_DOMAIN}/sub/{sub_token}"


def _device_subscription_url(sub_token: str, device_id: int) -> str:
    """Персональная ссылка ОДНОГО устройства — именно её показывает бот."""
    return f"https://{settings.SUBSCRIPTION_PUBLIC_DOMAIN}/sub/{sub_token}/{device_id}"


def _get_user_or_404(db: Session, telegram_id: int):
    user = UserRepository(db).get_by_telegram_id(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Пользователи / подписка ─────────────────────────────────────────────────────

@router.post("/users/register")
async def register_user(payload: RegisterUserRequest, db: Session = Depends(get_db_session)):
    service = UserService(db)
    user, is_new = service.register(
        telegram_id=payload.telegram_id,
        username=payload.username,
        first_name=payload.first_name,
        referrer_telegram_id=payload.referrer_id,
    )
    return {"success": True, "is_new": is_new, "sub_url": _subscription_url(user.sub_token)}


@router.get("/users/account/{telegram_id}")
async def get_account(telegram_id: int, db: Session = Depends(get_db_session)):
    user = _get_user_or_404(db, telegram_id)
    device_service = DeviceService(db)
    devices_count = len(device_service.list_devices(user.id))

    return {
        "username": user.username or user.first_name,
        "subscription_status": user.subscription_status,
        "subscription_expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
        "trial_available": (not user.trial_used) and user.subscription_expires_at is None,
        "devices_count": devices_count,
        "max_devices": device_service.max_devices_for(user),
        "sub_url": _subscription_url(user.sub_token),
    }


@router.post("/subscription/buy")
async def buy_subscription(payload: BuySubscriptionRequest, db: Session = Depends(get_db_session)):
    user = _get_user_or_404(db, payload.telegram_id)
    days = payload.days or settings.SUBSCRIPTION_DAYS_DEFAULT

    was_active_before = user.subscription_expires_at is not None
    UserService(db).activate_subscription(user, days=days)

    return {
        "success": True,
        "expires_at": user.subscription_expires_at.isoformat(),
        "is_first_payment": not was_active_before,
        "sub_url": _subscription_url(user.sub_token),
    }


@router.post("/subscription/trial")
async def start_trial(payload: StartTrialRequest, db: Session = Depends(get_db_session)):
    user = _get_user_or_404(db, payload.telegram_id)
    ok, message = UserService(db).start_trial(user, days=payload.days)
    if not ok:
        return {"success": False, "message": message}

    return {
        "success": True,
        "expires_at": user.subscription_expires_at.isoformat(),
        "sub_url": _subscription_url(user.sub_token),
    }


# ── Устройства ────────────────────────────────────────────────────────────────

@router.get("/devices/{telegram_id}")
async def list_devices(telegram_id: int, db: Session = Depends(get_db_session)):
    user = _get_user_or_404(db, telegram_id)
    device_service = DeviceService(db)
    devices = device_service.list_devices(user.id)
    return {
        "success": True,
        "devices": [
            {
                "id": d.id,
                "device_name": d.device_name,
                "device_number": d.device_number,
                "sub_url": _device_subscription_url(user.sub_token, d.id),
            }
            for d in devices
        ],
        "devices_count": len(devices),
        "max_devices": device_service.max_devices_for(user),
    }


@router.post("/devices/add")
async def add_device(payload: AddDeviceRequest, db: Session = Depends(get_db_session)):
    """
    Создаёт устройство (со своим порядковым device_number у пользователя)
    и провижинит один и тот же UUID сразу на всех активных серверах
    платформы. Возвращает персональную ссылку подписки ЭТОГО устройства.
    """
    user = _get_user_or_404(db, payload.telegram_id)
    sub_service = SubscriptionService(db)

    result = await sub_service.add_device(user, payload.device_name)
    if not result.success:
        return {
            "success": False,
            "limit_reached": result.limit_reached,
            "max_devices": result.max_devices,
            "message": result.message,
        }

    return {
        "success": True,
        "device_id": result.device.id,
        "device_number": result.device.device_number,
        "sub_url": _device_subscription_url(user.sub_token, result.device.id),
    }


@router.delete("/devices/remove")
async def remove_device(payload: RemoveDeviceRequest, db: Session = Depends(get_db_session)):
    user = _get_user_or_404(db, payload.telegram_id)
    sub_service = SubscriptionService(db)

    ok = await sub_service.remove_device(user, payload.device_id)
    if not ok:
        return {"success": False, "message": "Устройство не найдено"}
    return {"success": True, "message": "Устройство успешно удалено (доступ отозван на всех серверах)"}


@router.post("/devices/regenerate")
async def regenerate_device_key(payload: RegenerateDeviceKeyRequest, db: Session = Depends(get_db_session)):
    user = _get_user_or_404(db, payload.telegram_id)
    device = DeviceService(db).get_owned_device(user.id, payload.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await ProvisioningService(db).regenerate_device_key(device)
    return {
        "success": True,
        "sub_url": _device_subscription_url(user.sub_token, device.id),
    }


@router.post("/devices/add_server")
async def add_server_to_device(payload: AddServerToDeviceRequest, db: Session = Depends(get_db_session)):
    """Точечное расширение конкретного устройства ещё одним сервером."""
    user = _get_user_or_404(db, payload.telegram_id)
    sub_service = SubscriptionService(db)

    ok = await sub_service.add_server_to_device(user, payload.device_id, payload.server_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Не удалось провижинить доступ на выбранном сервере")
    return {
        "success": True,
        "sub_url": _device_subscription_url(user.sub_token, payload.device_id),
    }


@router.post("/devices/buy_slot")
async def buy_device_slot(payload: BuyDeviceSlotRequest, db: Session = Depends(get_db_session)):
    """
    Подтверждённая (после вебхука платёжки) докупка доп. места под
    устройство. extra_devices увеличивается на 1 и больше никогда не
    уменьшается автоматически — аудиторский счётчик факта оплаты, не
    "остаток мест" (тот же принцип, что был в public_html/backend).
    """
    user = _get_user_or_404(db, payload.telegram_id)
    user.extra_devices += 1
    db.add(user)
    db.flush()

    device_service = DeviceService(db)
    new_max = device_service.max_devices_for(user)

    return {
        "success": True,
        "max_devices": new_max,
        "message": f"Дополнительное место под устройство добавлено! Теперь доступно {new_max} устройств.",
    }
