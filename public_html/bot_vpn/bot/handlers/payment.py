"""
bot/handlers/payment.py — Обработчики оплаты подписки.

Поддерживаемые способы оплаты:
  - YooKassa (банковские карты, СБП)
  - CryptoBot (USDT/крипта через @CryptoBot)
  - Heleket (крипта напрямую)

Подключение в main.py:
    from bot.handlers.payment import router as payment_router
    dp.include_router(payment_router)   # до fallback_router

Вебхуки (настраиваются на стороне платёжных систем):
    POST /yookassa-webhook
    POST /cryptobot-webhook
    POST /heleket-webhook

Нужные переменные в .env / config:
    YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY
    CRYPTOBOT_TOKEN
    HELEKET_MERCHANT_ID, HELEKET_API_KEY
    WEBHOOK_DOMAIN   (ваш домен, напр. api.vpn.com)
    BOT_USERNAME     (username бота без @)
"""

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

import aiohttp
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.api_client import BackendAPIError, api_client
from bot.keyboards.keyboards import payment_success_keyboard
from config import settings

logger = logging.getLogger(__name__)

router = Router(name="payment")

# ── Запись факта оплаты для модуля аналитики ─────────────────────────────────
# Путь к БД аналитики. Если analytics/ лежит у вас не по этому пути —
# поправьте строку ниже (или замените на os.getenv("ANALYTICS_DB_PATH", ...),
# если хотите задавать его через .env бота).
_ANALYTICS_DB_PATH = "/root/bot-vpn/analytics/analytics.db"


def _record_payment_event(telegram_id: int, method: str, price: float, days: int, kind: str = "subscription") -> None:
    """
    Записывает одну строку о факте оплаты в БД модуля аналитики — отдельно
    и независимо от основной бизнес-логики бота.

    Намеренно не импортирует ничего из модуля analytics (чтобы не тащить
    в бот лишнюю зависимость) — просто открывает sqlite3 напрямую коротким
    соединением и сразу его закрывает. Любая ошибка здесь (файл не найден,
    модуль аналитики ещё не развёрнут, БД занята и т.п.) только логируется
    и НИКОГДА не прерывает обработку самого платежа — это вторичная,
    необязательная для работы бота функция.

    kind: "subscription" или "device" — что именно купили (для разбивки
    на дашборде аналитики).
    """
    try:
        import sqlite3
        from datetime import datetime

        conn = sqlite3.connect(_ANALYTICS_DB_PATH, timeout=5)
        try:
            conn.execute(
                "INSERT INTO payment_events (ts, telegram_id, method, kind, price, days) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), telegram_id, method, kind, price, days),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Не удалось записать payment_event в аналитику (не критично): %s", exc)


# ── Конфигурация платёжных систем ─────────────────────────────────────────────
# Добавьте эти поля в ваш config.py / .env:
#   YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY
#   CRYPTOBOT_TOKEN
#   HELEKET_MERCHANT_ID, HELEKET_API_KEY
#   WEBHOOK_DOMAIN, BOT_USERNAME

def _get_cfg(name: str, default: str = "") -> str:
    return getattr(settings, name, default) or ""


# ── FSM ───────────────────────────────────────────────────────────────────────

class PaymentStates(StatesGroup):
    choosing_method = State()


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def _payment_methods_keyboard(kind: str = "subscription") -> InlineKeyboardMarkup:
    """
    Строит клавиатуру только из доступных (настроенных) способов оплаты.

    kind: "subscription" или "device_slot" — встраивается в callback_data
    (pay:<метод>:<kind>), чтобы pay_yookassa/pay_cryptobot/pay_heleket знали,
    за что именно создают платёж, без отдельного FSM-стейта на каждый случай.
    """
    builder = InlineKeyboardBuilder()

    if _get_cfg("YOOKASSA_SHOP_ID") and _get_cfg("YOOKASSA_SECRET_KEY"):
        builder.row(InlineKeyboardButton(
            text="💳 Банковская карта / СБП (YooKassa)",
            callback_data=f"pay:yookassa:{kind}",
        ))

    if _get_cfg("CRYPTOBOT_TOKEN"):
        builder.row(InlineKeyboardButton(
            text="🤖 Крипта через CryptoBot (USDT и др.)",
            callback_data=f"pay:cryptobot:{kind}",
        ))

    if _get_cfg("HELEKET_MERCHANT_ID") and _get_cfg("HELEKET_API_KEY"):
        builder.row(InlineKeyboardButton(
            text="🌐 Крипта напрямую (Heleket)",
            callback_data=f"pay:heleket:{kind}",
        ))

    back_target = "devices:back" if kind == "device_slot" else "menu:main"
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=back_target))
    return builder.as_markup()


def _payment_context(kind: str) -> tuple[float, int, str]:
    """
    Возвращает (price, days, description) для данного kind платежа.
    Единая точка, откуда берутся цена/срок/текст — чтобы не дублировать
    эти числа в каждой из трёх функций оплаты (YooKassa/CryptoBot/Heleket).

    days для device_slot равен 0 — это не подписка, дни здесь не имеют
    смысла, поле сохраняется только для единообразия структуры metadata.
    """
    if kind == "device_slot":
        return settings.EXTRA_DEVICE_PRICE, 0, "Доп. устройство VPN"
    return settings.SUBSCRIPTION_PRICE, settings.SUBSCRIPTION_DAYS, f"VPN подписка на {settings.SUBSCRIPTION_DAYS} дней"


def _open_url_keyboard(url: str, label: str = "💳 Перейти к оплате") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=label, url=url))
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))
    return builder.as_markup()


# ── Точка входа: выбор способа оплаты ────────────────────────────────────────

async def _show_payment_methods(callback: CallbackQuery, state: FSMContext, kind: str) -> None:
    """
    Общая логика показа списка способов оплаты — используется и для
    подписки (subscription:confirm), и для докупки устройства
    (device_slot:confirm). kind определяет цену/текст и какие callback_data
    получат кнопки оплаты (через _payment_methods_keyboard).
    """
    await callback.answer()
    await state.set_state(PaymentStates.choosing_method)

    kb = _payment_methods_keyboard(kind)
    pay_buttons = [
        row for row in kb.inline_keyboard
        if any(btn.callback_data and btn.callback_data.startswith("pay:") for btn in row)
    ]

    if not pay_buttons:
        await callback.message.edit_text(
            text=(
                "⚠️ <b>Оплата временно недоступна</b>\n\n"
                "Администратор ещё не настроил платёжные системы.\n"
                "Обратитесь в 🆘 Поддержку для ручной оплаты."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")
            ).as_markup(),
        )
        return

    price, days, description = _payment_context(kind)

    if kind == "device_slot":
        text = (
            f"💳 <b>Докупка дополнительного устройства</b>\n\n"
            f"Стоимость: <b>{price:.0f} ₽</b> (разово, навсегда добавляет 1 место)\n\n"
            "Выберите способ оплаты:"
        )
    else:
        text = (
            f"💳 <b>Оплата подписки</b>\n\n"
            f"Сумма: <b>{price:.0f} ₽</b>\n"
            f"Срок: <b>{days} дней</b>\n\n"
            "Выберите способ оплаты:"
        )

    await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "subscription:confirm")
async def callback_choose_payment(callback: CallbackQuery, state: FSMContext) -> None:
    """Показывает список способов оплаты подписки."""
    await _show_payment_methods(callback, state, kind="subscription")


@router.callback_query(F.data == "device_slot:confirm")
async def callback_choose_device_slot_payment(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает список способов оплаты доп. устройства — точка входа из
    экрана "достигнут лимит устройств" (см. devices.py, кнопка
    buy_device_slot_keyboard()).
    """
    await _show_payment_methods(callback, state, kind="device_slot")


# ── YooKassa ──────────────────────────────────────────────────────────────────

def _payment_detail_line(kind: str, days: int) -> str:
    """Строка с деталями платежа для сообщения после создания счёта."""
    if kind == "device_slot":
        return "Покупка: <b>+1 устройство</b> (навсегда)"
    return f"Подписка: <b>{days} дней</b>"


def _back_to_methods_callback(kind: str) -> str:
    """Куда ведёт кнопка 'Назад к выбору' при ошибке создания платежа."""
    return "device_slot:confirm" if kind == "device_slot" else "subscription:confirm"


@router.callback_query(PaymentStates.choosing_method, F.data.startswith("pay:yookassa"))
async def pay_yookassa(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("⏳ Создаю ссылку на оплату...")

    # callback.data = "pay:yookassa:subscription" или "pay:yookassa:device_slot"
    kind = callback.data.split(":")[-1]
    price, days, description = _payment_context(kind)

    shop_id = _get_cfg("YOOKASSA_SHOP_ID")
    secret_key = _get_cfg("YOOKASSA_SECRET_KEY")
    user_id = callback.from_user.id
    bot_username = _get_cfg("BOT_USERNAME")

    idempotency_key = str(uuid.uuid4())
    payload = {
        "amount": {"value": f"{price:.2f}", "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{bot_username}" if bot_username else "https://t.me/",
        },
        "capture": True,
        "description": f"{description} — user {user_id}",
        "metadata": {
            "telegram_id": user_id,
            "days": days,
            "price": price,
            "kind": kind,
        },
    }

    try:
        auth = aiohttp.BasicAuth(shop_id, secret_key)
        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.post(
                "https://api.yookassa.ru/v3/payments",
                json=payload,
                headers={"Idempotence-Key": idempotency_key},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

        if resp.status != 200:
            raise RuntimeError(f"YooKassa API {resp.status}: {data}")

        pay_url = data["confirmation"]["confirmation_url"]
        await state.clear()

        await callback.message.edit_text(
            text=(
                "💳 <b>Оплата через YooKassa</b>\n\n"
                f"Сумма: <b>{price:.0f} ₽</b>\n"
                f"{_payment_detail_line(kind, days)}\n\n"
                "Нажмите кнопку ниже для перехода на страницу оплаты.\n"
                "После оплаты — автоматически зачислится."
            ),
            parse_mode="HTML",
            reply_markup=_open_url_keyboard(pay_url, "💳 Оплатить картой / СБП"),
        )

    except Exception as exc:
        logger.error("YooKassa payment creation failed for user %d: %s", user_id, exc)
        await state.clear()
        await callback.message.edit_text(
            text="❌ Не удалось создать платёж YooKassa. Попробуйте другой способ или обратитесь в поддержку.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="◀️ Назад к выбору", callback_data=_back_to_methods_callback(kind))
            ).as_markup(),
        )


# ── CryptoBot ─────────────────────────────────────────────────────────────────

async def _get_usdt_rub_rate() -> Decimal | None:
    """Получает курс USDT/RUB через Binance P2P API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                json={
                    "asset": "USDT", "fiat": "RUB", "merchantCheck": False,
                    "page": 1, "rows": 10, "tradeType": "BUY",
                },
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                prices = [
                    Decimal(ad["adv"]["price"])
                    for ad in data.get("data", [])
                    if ad.get("adv", {}).get("price")
                ]
                if prices:
                    return sum(prices) / len(prices)
    except Exception as exc:
        logger.warning("Failed to get USDT/RUB rate: %s", exc)
    return None


@router.callback_query(PaymentStates.choosing_method, F.data.startswith("pay:cryptobot"))
async def pay_cryptobot(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("⏳ Создаю счёт в Crypto Pay...")

    kind = callback.data.split(":")[-1]
    price, days, description = _payment_context(kind)
    price_rub = Decimal(str(price))

    token = _get_cfg("CRYPTOBOT_TOKEN")
    user_id = callback.from_user.id

    try:
        # CryptoBot поддерживает выставление счёта в рублях напрямую (fiat RUB).
        # payload: "{telegram_id}:{days}:{price}:{kind}" — kind на 4-м месте,
        # парсится в webhook_server.py с обратной совместимостью на старый
        # 3-частный формат (если kind отсутствует — считается subscription).
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://pay.crypt.bot/api/createInvoice",
                json={
                    "currency_type": "fiat",
                    "fiat": "RUB",
                    "amount": float(price_rub),
                    "description": description,
                    "payload": f"{user_id}:{days}:{float(price_rub)}:{kind}",
                    "expires_in": 3600,
                },
                headers={"Crypto-Pay-API-Token": token},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

        if not data.get("ok"):
            raise RuntimeError(f"CryptoBot error: {data}")

        pay_url = data["result"]["pay_url"]
        await state.clear()

        await callback.message.edit_text(
            text=(
                "🤖 <b>Оплата через CryptoBot</b>\n\n"
                f"Сумма: <b>{price_rub:.0f} ₽</b> (в USDT по курсу)\n"
                f"{_payment_detail_line(kind, days)}\n\n"
                "Нажмите кнопку ниже — откроется @CryptoBot с выставленным счётом."
            ),
            parse_mode="HTML",
            reply_markup=_open_url_keyboard(pay_url, "🤖 Оплатить через CryptoBot"),
        )

    except Exception as exc:
        logger.error("CryptoBot invoice creation failed for user %d: %s", user_id, exc)
        await state.clear()
        await callback.message.edit_text(
            text="❌ Не удалось создать счёт CryptoBot. Попробуйте другой способ.",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="◀️ Назад к выбору", callback_data=_back_to_methods_callback(kind))
            ).as_markup(),
        )


# ── Heleket ───────────────────────────────────────────────────────────────────

def _heleket_sign(payload: dict, api_key: str) -> str:
    """Генерирует подпись для Heleket API."""
    data_str = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    base64_encoded = base64.b64encode(data_str.encode()).decode()
    raw = f"{base64_encoded}{api_key}"
    return hashlib.md5(raw.encode()).hexdigest()


@router.callback_query(PaymentStates.choosing_method, F.data.startswith("pay:heleket"))
async def pay_heleket(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("⏳ Создаю счёт Heleket...")

    kind = callback.data.split(":")[-1]
    price, days, description_text = _payment_context(kind)

    merchant_id = _get_cfg("HELEKET_MERCHANT_ID")
    api_key = _get_cfg("HELEKET_API_KEY")
    domain = _get_cfg("WEBHOOK_DOMAIN")
    bot_username = _get_cfg("BOT_USERNAME")
    user_id = callback.from_user.id

    order_id = str(uuid.uuid4())
    metadata = {"telegram_id": user_id, "days": days, "price": price, "kind": kind}
    redirect_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me/"

    payload = {
        "amount": f"{price:.2f}",
        "currency": "RUB",
        "order_id": order_id,
        "description": json.dumps(metadata),
        "url_return": redirect_url,
        "url_success": redirect_url,
        "url_callback": f"https://{domain}/heleket-webhook" if domain else "",
        "lifetime": 1800,
        "is_payment_multiple": False,
    }

    headers = {
        "merchant": merchant_id,
        "sign": _heleket_sign(payload, api_key),
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.heleket.com/v1/payment",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()

        pay_url = data.get("result", {}).get("url")
        if not pay_url:
            raise RuntimeError(f"Heleket error: {data}")

        await state.clear()

        await callback.message.edit_text(
            text=(
                "🌐 <b>Оплата через Heleket</b>\n\n"
                f"Сумма: <b>{price:.0f} ₽</b> (в криптовалюте)\n"
                f"{_payment_detail_line(kind, days)}\n\n"
                "Нажмите кнопку ниже для оплаты."
            ),
            parse_mode="HTML",
            reply_markup=_open_url_keyboard(pay_url, "🌐 Оплатить через Heleket"),
        )

    except Exception as exc:
        logger.error("Heleket invoice creation failed for user %d: %s", user_id, exc)
        await state.clear()
        await callback.message.edit_text(
            text="❌ Не удалось создать счёт Heleket. Попробуйте другой способ.",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="◀️ Назад к выбору", callback_data=_back_to_methods_callback(kind))
            ).as_markup(),
        )


# ── Обработка успешной оплаты (вызывается из вебхуков) ───────────────────────

async def process_successful_payment(bot, metadata: dict) -> None:
    """
    Диспетчер успешной оплаты — вызывается из вебхук-сервера (webhook_server.py)
    для всех трёх платёжных систем и обоих видов покупки.

    metadata должен содержать:
        telegram_id (int), days (int), price (float), kind (str, опционально)

    kind == "device_slot" → докупка доп. устройства (_process_device_slot_payment).
    Любое другое значение (включая отсутствие поля, для обратной совместимости
    со старыми платежами без kind) → обычная подписка (_process_subscription_payment).
    """
    telegram_id = int(metadata.get("telegram_id", 0))
    if not telegram_id:
        logger.error("process_successful_payment: no telegram_id in metadata %s", metadata)
        return

    kind = metadata.get("kind", "subscription")

    if kind == "device_slot":
        await _process_device_slot_payment(bot, metadata, telegram_id)
    else:
        await _process_subscription_payment(bot, metadata, telegram_id)


async def _process_subscription_payment(bot, metadata: dict, telegram_id: int) -> None:
    """
    Активирует подписку после подтверждения оплаты. Логика идентична
    исходной (до появления докупки устройств) — поведение для подписки
    не изменилось ни в чём.

    Если это первая оплата пользователя и он был приглашён по реферальной
    ссылке, backend начисляет рефереру 7 дней подписки и сообщает об этом
    в ответе (referral_bonus_granted, referrer_id) — в этом случае рефереру
    отправляется отдельное уведомление.
    """
    days = int(metadata.get("days", settings.SUBSCRIPTION_DAYS))
    price = float(metadata.get("price", settings.SUBSCRIPTION_PRICE))
    payment_method = metadata.get("payment_method", "unknown")

    try:
        data = await api_client.buy_subscription(telegram_id=telegram_id)

        expires_str = data.get("expires_at", "—")
        referral_bonus_granted = data.get("referral_bonus_granted", False)
        referrer_id = data.get("referrer_id")

        extra = (
            "\n\n🔑 Перейдите в «🔑 Мой VPN» → «Мои ключи», чтобы получить ключ для устройства "
            "(если устройство ещё не добавлено — добавьте его в «Мои устройства»)."
        )

        method_icons = {
            "yookassa": "💳",
            "cryptobot": "🤖",
            "heleket": "🌐",
        }
        icon = method_icons.get(payment_method.lower(), "✅")

        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"✅ <b>Оплата прошла успешно!</b>\n\n"
                f"{icon} Способ: <b>{payment_method}</b>\n"
                f"💰 Сумма: <b>{price:.0f} ₽</b>\n"
                f"📅 Подписка до: <b>{expires_str}</b>"
                f"{extra}"
            ),
            parse_mode="HTML",
            reply_markup=payment_success_keyboard(),
        )

        # Реферальный бонус: это была первая оплата приглашённого пользователя,
        # и backend уже начислил рефереру 7 дней подписки. Уведомляем реферера
        # отдельным сообщением — он не видит сам процесс оплаты, поэтому
        # должен узнать о бонусе именно отсюда.
        if referral_bonus_granted and referrer_id:
            try:
                await bot.send_message(
                    chat_id=referrer_id,
                    text=(
                        "🎁 <b>Реферальный бонус!</b>\n\n"
                        "Один из приглашённых вами пользователей оплатил подписку "
                        "в первый раз — вам начислено <b>+7 дней</b> подписки!\n\n"
                        "Загляните в <b>💳 Подписка</b>, чтобы увидеть новую дату окончания."
                    ),
                    parse_mode="HTML",
                )
                logger.info(
                    "Referral bonus notification sent to referrer %d (referred=%d)",
                    referrer_id, telegram_id,
                )
            except Exception as exc:
                # Реферер мог заблокировать бота — это не должно ломать обработку платежа
                logger.warning(
                    "Failed to notify referrer %d about bonus: %s", referrer_id, exc
                )

        # Фиксируем факт оплаты для модуля аналитики (см. _record_payment_event
        # выше). Делается сразу после подтверждённой активации подписки —
        # то есть только для реально прошедших оплат, не для попыток.
        _record_payment_event(telegram_id, payment_method, price, days, kind="subscription")

        logger.info(
            "Payment processed: user=%d method=%s price=%.2f days=%d",
            telegram_id, payment_method, price, days,
        )

    except BackendAPIError as exc:
        logger.error("Failed to activate subscription for user %d: %s", telegram_id, exc)
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                "⚠️ Оплата получена, но произошла ошибка при активации подписки.\n"
                "Обратитесь в поддержку — мы активируем вручную."
            ),
        )
    except Exception as exc:
        logger.error("Unexpected error processing payment for user %d: %s", telegram_id, exc, exc_info=True)


async def _process_device_slot_payment(bot, metadata: dict, telegram_id: int) -> None:
    """
    Начисляет дополнительное место под устройство после подтверждённой оплаты.

    В отличие от подписки, здесь нет реферального бонуса и нет понятия
    "срок действия" — это разовая, постоянная прибавка лимита устройств.
    """
    price = float(metadata.get("price", settings.EXTRA_DEVICE_PRICE))
    payment_method = metadata.get("payment_method", "unknown")

    try:
        data = await api_client.buy_device_slot(telegram_id=telegram_id)
        new_max = data.get("max_devices", "—")

        method_icons = {"yookassa": "💳", "cryptobot": "🤖", "heleket": "🌐"}
        icon = method_icons.get(payment_method.lower(), "✅")

        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"✅ <b>Оплата прошла успешно!</b>\n\n"
                f"{icon} Способ: <b>{payment_method}</b>\n"
                f"💰 Сумма: <b>{price:.0f} ₽</b>\n"
                f"📱 Доступно устройств: <b>{new_max}</b>\n\n"
                "Перейдите в «👤 Личный кабинет» → «📱 Мои устройства» → "
                "«➕ Добавить устройство», чтобы добавить новое."
            ),
            parse_mode="HTML",
        )

        _record_payment_event(telegram_id, payment_method, price, days=0, kind="device")

        logger.info(
            "Device slot payment processed: user=%d method=%s price=%.2f new_max=%s",
            telegram_id, payment_method, price, new_max,
        )

    except BackendAPIError as exc:
        logger.error("Failed to grant device slot for user %d: %s", telegram_id, exc)
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                "⚠️ Оплата получена, но произошла ошибка при начислении места под устройство.\n"
                "Обратитесь в поддержку — мы начислим вручную."
            ),
        )
    except Exception as exc:
        logger.error("Unexpected error processing device slot payment for user %d: %s", telegram_id, exc, exc_info=True)
