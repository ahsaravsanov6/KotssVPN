from fastapi import FastAPI, Depends, HTTPException, Header, Body
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
import logging

from database import get_db, User, Device, Referral
from config import settings
from xui_service import xui_client

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI(title="VPN Bot Backend API")

# --- Middleware для проверки API-KEY ---
# Этот заголовок должен быть в каждом запросе от бота
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.API_KEY:
        logger.warning(f"Unauthorized access attempt with key: {x_api_key}")
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key

# --- Эндпоинты пользователей ---

@app.post("/users/register", dependencies=[Depends(verify_api_key)])
async def register(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Регистрация пользователя в БД.

    Если передан referrer_id (пользователь пришёл по реферальной ссылке
    /start ref_<id>) — привязываем его как пригласившего. Привязка
    делается ТОЛЬКО при первой регистрации и не может быть изменена
    задним числом — иначе кто-то мог бы "переподписать" уже активного
    пользователя себе и получить бонус с чужой оплаты.
    """
    tid = data.get("telegram_id")
    if not tid:
        raise HTTPException(status_code=400, detail="telegram_id is required")

    referrer_id = data.get("referrer_id")

    user = db.query(User).filter(User.telegram_id == tid).first()

    if not user:
        # Реферер должен реально существовать и не быть самим пользователем
        valid_referrer = None
        if referrer_id and referrer_id != tid:
            referrer = db.query(User).filter(User.telegram_id == referrer_id).first()
            if referrer:
                valid_referrer = referrer_id
            else:
                logger.warning(f"register: referrer_id={referrer_id} not found, ignoring")

        user = User(
            telegram_id=tid,
            username=data.get("username"),
            first_name=data.get("first_name"),
            referrer_id=valid_referrer,
        )
        db.add(user)
        db.commit()

        if valid_referrer:
            # Создаём запись реферала сразу при регистрации (bonus_granted=False).
            # Бонус будет начислен позже, при первой успешной оплате — см. /subscription/buy.
            existing = db.query(Referral).filter(Referral.referred_id == tid).first()
            if not existing:
                db.add(Referral(referrer_id=valid_referrer, referred_id=tid))
                db.commit()
                logger.info(f"Referral link created: referrer={valid_referrer} -> referred={tid}")

        logger.info(f"User {tid} registered in DB")
        return {"success": True, "is_new": True}

    return {"success": True, "is_new": False}

@app.get("/users/account/{telegram_id}", dependencies=[Depends(verify_api_key)])
async def get_account(telegram_id: int, db: Session = Depends(get_db)):
    """Информация о профиле и подписке"""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    devices_count = len(user.devices)
    
    # Логика статуса подписки
    status = "none"
    if user.subscription_expires_at:
        status = "active" if user.subscription_expires_at > datetime.now() else "expired"
    
    return {
        "username": user.username or user.first_name,
        "subscription_status": status,
        "subscription_expires_at": user.subscription_expires_at.isoformat() if user.subscription_expires_at else None,
        "devices_count": devices_count,
        "max_devices": 3 + user.extra_devices  # Базовый лимит + купленные доп. места
    }

# --- Эндпоинты подписки ---

@app.post("/subscription/buy", dependencies=[Depends(verify_api_key)])
async def buy_sub(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Активация подписки и создание аккаунта в VPN.

    Реферальный бонус: если это ПЕРВАЯ оплата пользователя (до этого момента
    у него никогда не было подписки, т.е. subscription_expires_at был None)
    и пользователь был приглашён по реферальной ссылке — рефереру начисляется
    7 дней подписки единоразово. Защита от повторного начисления —
    флаг Referral.bonus_granted, который выставляется один раз и больше
    никогда не сбрасывается, независимо от того, сколько раз пользователь
    продлит подписку в будущем.
    """
    tid = data.get("telegram_id")
    user = db.query(User).filter(User.telegram_id == tid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    is_first_payment = user.subscription_expires_at is None

    # ИМИТАЦИЯ ОПЛАТЫ: В реальности здесь должен быть Webhook от платежки
    # Активируем подписку на 30 дней
    user.is_active = True
    user.subscription_expires_at = datetime.now() + timedelta(days=30)
    db.commit()

    referral_bonus_granted = False
    referrer_id = None

    if is_first_payment:
        referral = (
            db.query(Referral)
            .filter(Referral.referred_id == tid, Referral.bonus_granted == False)  # noqa: E712
            .first()
        )
        if referral:
            referrer = db.query(User).filter(User.telegram_id == referral.referrer_id).first()
            if referrer:
                base = referrer.subscription_expires_at or datetime.now()
                # Если у реферера подписка уже истекла — бонусные дни считаем от текущего момента,
                # а не от прошедшей даты, иначе он не получит реальных дополнительных дней доступа.
                if base < datetime.now():
                    base = datetime.now()
                referrer.subscription_expires_at = base + timedelta(days=referral.bonus_days)
                referrer.is_active = True

                referral.bonus_granted = True
                referral.bonus_granted_at = datetime.now()
                db.commit()

                referral_bonus_granted = True
                referrer_id = referral.referrer_id
                logger.info(
                    f"Referral bonus granted: referrer={referrer_id} "
                    f"+{referral.bonus_days}d for referred={tid} first payment"
                )

    return {
        "success": True,
        "expires_at": user.subscription_expires_at.isoformat(),
        "message": "Подписка успешно активирована! Добавьте устройство в разделе «Мои устройства», чтобы получить ключ.",
        "referral_bonus_granted": referral_bonus_granted,
        "referrer_id": referrer_id,
    }


@app.post("/devices/buy_slot", dependencies=[Depends(verify_api_key)])
async def buy_device_slot(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Подтверждённая оплата дополнительного слота под устройство сверх
    базового лимита (3 + extra_devices).

    Вызывается ботом ТОЛЬКО после подтверждённого вебхука платёжной системы —
    точно так же, как /subscription/buy. Сам этот эндпоинт не проверяет
    реальность оплаты (как и /subscription/buy), он доверяет тому, что
    его вызывает только бот после подтверждённых денег.

    extra_devices увеличивается на 1 и больше никогда не уменьшается
    автоматически — это аудиторский счётчик факта оплаты, не "остаток
    мест". Если в будущем понадобится сделать возврат денег — уменьшение
    нужно будет делать отдельной осознанной операцией, а не как побочный
    эффект удаления устройства.
    """
    tid = data.get("telegram_id")
    user = db.query(User).filter(User.telegram_id == tid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.extra_devices += 1
    db.commit()

    new_max = 3 + user.extra_devices
    logger.info(f"Device slot purchased: user={tid} extra_devices={user.extra_devices} new_max={new_max}")

    return {
        "success": True,
        "max_devices": new_max,
        "message": f"Дополнительное место под устройство добавлено! Теперь доступно {new_max} устройств.",
    }

# --- Эндпоинты VPN ---

@app.get("/vpn/config/{telegram_id}/{device_id}", dependencies=[Depends(verify_api_key)])
async def get_config(telegram_id: int, device_id: int, db: Session = Depends(get_db)):
    """
    Выдача VPN-ссылки для КОНКРЕТНОГО устройства пользователя.

    В отличие от старой модели (один общий конфиг на telegram_id),
    теперь у каждого устройства свой VLESS-клиент в панели — поэтому
    обязательно нужен device_id, чтобы понять, какой именно ключ отдать.
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == telegram_id)
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Проверка активности подписки
    is_active = user.is_active and (user.subscription_expires_at and user.subscription_expires_at > datetime.now())

    if not is_active:
        return {"success": False, "message": "Нет активной подписки или срок её действия истёк"}

    if not device.vpn_email:
        return {
            "success": False,
            "message": "Для этого устройства ещё не создан VPN-ключ. Попробуйте удалить и добавить устройство снова.",
        }

    # 1. Пытаемся найти уже существующего клиента в панели
    vpn = await xui_client.get_user_config(device.vpn_email)

    # 2. Если в панели его нет (например, был сбой при создании), создаём сейчас
    if not vpn.get("success"):
        logger.info(f"Device {device_id} (user {telegram_id}) not found in panel, creating now...")
        vpn = await xui_client.create_user(telegram_id, device_id)
        if vpn.get("success"):
            device.vpn_email = vpn.get("email")
            device.vpn_uuid = vpn.get("uuid")
            device.vpn_sub_id = vpn.get("sub_id")
            db.commit()

    if not vpn.get("success"):
        return vpn

    config_link = vpn.get("config", "")
    user_uuid = vpn.get("uuid", "")

    return {
        "success": True,
        "uuid": user_uuid,
        "device_name": device.device_name,
        "config_text": config_link,
        "qr_code_url": f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={config_link}",
    }

@app.post("/vpn/regenerate", dependencies=[Depends(verify_api_key)])
async def regenerate(data: dict = Body(...), db: Session = Depends(get_db)):
    """Перегенерация UUID ключа конкретного устройства"""
    tid = data.get("telegram_id")
    device_id = data.get("device_id")
    if not tid or not device_id:
        raise HTTPException(status_code=400, detail="telegram_id and device_id are required")

    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == tid)
        .first()
    )
    if not device or not device.vpn_email:
        return {"success": False, "message": "Устройство или его VPN-ключ не найдены"}

    res = await xui_client.regenerate_user(tid, device.vpn_email)
    if res.get("success"):
        device.vpn_uuid = res.get("new_uuid")
        db.commit()
    return res

# --- Эндпоинты реферальной системы ---

@app.get("/referral/stats/{telegram_id}", dependencies=[Depends(verify_api_key)])
async def referral_stats(telegram_id: int, db: Session = Depends(get_db)):
    """
    Статистика приглашений для рефереральной ссылки пользователя.

    invited_count   — сколько людей зарегистрировалось по его ссылке (всего)
    bonus_days      — сколько всего бонусных дней начислено (по факту первых оплат)
    pending_count   — сколько приглашённых ещё не оплатили подписку (бонус не начислен)
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    referrals = db.query(Referral).filter(Referral.referrer_id == telegram_id).all()

    invited_count = len(referrals)
    granted = [r for r in referrals if r.bonus_granted]
    bonus_days = sum(r.bonus_days for r in granted)
    pending_count = invited_count - len(granted)

    return {
        "success": True,
        "invited_count": invited_count,
        "bonus_days": bonus_days,
        "pending_count": pending_count,
    }


# --- Эндпоинты устройств ---

@app.get("/devices/{telegram_id}", dependencies=[Depends(verify_api_key)])
async def get_devices(telegram_id: int, db: Session = Depends(get_db)):
    """Список привязанных устройств вместе с признаком наличия VPN-ключа"""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    devices = [
        {
            "id": d.id,
            "device_name": d.device_name,
            "has_vpn_key": bool(d.vpn_email),
        }
        for d in user.devices
    ]
    return {
        "success": True, 
        "devices": devices, 
        "devices_count": len(devices), 
        "max_devices": 3 + user.extra_devices  # Базовый лимит + купленные доп. места
    }

@app.post("/devices/add", dependencies=[Depends(verify_api_key)])
async def add_device(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Добавление нового устройства.

    Создаёт устройство в два шага:
      1. Резервируем строку Device в БД (нужен реальный id для email в панели).
      2. Создаём для неё отдельный VLESS-клиент в 3X-UI (xui_client.create_user).

    Если шаг 2 не удался — запись устройства удаляется (rollback), чтобы
    неудачная попытка не "съедала" лимит устройств пользователя и не
    оставляла в БД устройство без реального VPN-ключа.
    """
    tid = data.get("telegram_id")
    name = data.get("device_name")
    user = db.query(User).filter(User.telegram_id == tid).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    max_devices = 3 + user.extra_devices
    if len(user.devices) >= max_devices:
        # limit_reached=True — явный структурированный сигнал для бота,
        # чтобы показать экран "докупить место за N₽", а не просто текст
        # ошибки. extra_device_price бот покажет пользователю в этом экране.
        return {
            "success": False,
            "limit_reached": True,
            "max_devices": max_devices,
            "message": f"Достигнут лимит устройств ({max_devices})",
        }

    new_device = Device(user_id=tid, device_name=name)
    db.add(new_device)
    db.commit()
    db.refresh(new_device)

    vpn_data = await xui_client.create_user(tid, new_device.id)

    if not vpn_data.get("success"):
        logger.error(f"Failed to create VPN client for device {new_device.id} (user {tid}): {vpn_data.get('message')}")
        db.delete(new_device)
        db.commit()
        return {
            "success": False,
            "message": "Не удалось создать VPN-ключ для устройства. Попробуйте ещё раз через минуту.",
        }

    new_device.vpn_email = vpn_data.get("email")
    new_device.vpn_uuid = vpn_data.get("uuid")
    new_device.vpn_sub_id = vpn_data.get("sub_id")
    db.commit()

    return {
        "success": True,
        "message": f"Устройство {name} добавлено",
        "device_id": new_device.id,
        "config_text": vpn_data.get("config", ""),
        "qr_code_url": f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={vpn_data.get('config', '')}",
    }

@app.delete("/devices/remove", dependencies=[Depends(verify_api_key)])
async def remove_device(data: dict = Body(...), db: Session = Depends(get_db)):
    """
    Удаление устройства.

    Если у устройства есть привязанный VPN-ключ — сначала удаляем
    клиента из 3X-UI (xui_client.delete_user), и только потом убираем
    запись из БД. Это реально отзывает доступ: старый конфиг сразу
    перестаёт работать, а не просто исчезает из списка в боте.
    """
    did = data.get("device_id")
    device = db.query(Device).filter(Device.id == did).first()
    if not device:
        return {"success": False, "message": "Устройство не найдено"}

    if device.vpn_email:
        vpn_res = await xui_client.delete_user(device.vpn_email)
        if not vpn_res.get("success"):
            logger.error(f"Failed to delete VPN client {device.vpn_email}: {vpn_res.get('message')}")
            return {
                "success": False,
                "message": "Не удалось отозвать VPN-ключ устройства. Попробуйте позже.",
            }

    db.delete(device)
    db.commit()
    return {"success": True, "message": "Устройство успешно удалено"}

# --- Информационный эндпоинт ---
@app.get("/")
async def root():
    return {"status": "VPN Backend is running", "docs": "/docs"}
