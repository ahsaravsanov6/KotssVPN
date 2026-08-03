"""
bot/handlers/payment.py — Обработчики оплаты подписки (vpn_platform).

Поддерживаемые способы оплаты: YooKassa, CryptoBot, Heleket — без
изменений. Изменился только последний шаг: вместо public_html/backend
дергаем vpn_platform (api_client -> /internal/subscription/buy,
/internal/devices/buy_slot).

ВНИМАНИЕ: vpn_platform пока не умеет реферальные бонусы (нет модели
Referral) — buy_subscription() у неё не возвращает
referral_bonus_granted/referrer_id, поэтому здесь это read через .get()
и просто никогда не сработает, пока реферальная система не перенесена
на сторону платформы отдельным шагом.
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
from bot.keyboards.keyboards import payment_success_keyboard, back_to_main_keyboard
from config import settings

logger = logging.getLogger(__name__)

router = Router(name="payment")

# ── Запись факта оплаты для модуля аналитики ─────────────────────────────────
_ANALYTICS_DB_PATH = "/root/bot-vpn/analytics/analytics.db"


def _record_payment_event(telegram_id: int, method: str, price: float, days: int, kind: str = "subscription") -> None:
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


def _get_cfg(name: str, default: str = "") -> str:
    return getattr(settings, name, default) or ""


# ── FSM ───────────────────────────────────────────────────────────────────────

class PaymentStates(StatesGroup):
    choosing_method = State()


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def _payment_methods_keyboard(kind: str = "subscription") -> InlineKeyboardMarkup:
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
    """Обработчик кнопки «Согласен, перейти к оплате»."""
    if settings.TEST_MODE:
        # Тестовый режим: активируем подписку сразу
        await callback.answer("⏳ Активирую подписку...")
        user_id = callback.from_user.id
        days = settings.SUBSCRIPTION_DAYS
        price = settings.SUBSCRIPTION_PRICE

        try:
            data = await api_client.buy_subscription(telegram_id=user_id, days=days)
            expires_str = data.get("expires_at", "—")
            await callback.message.edit_text(
                text=(
                    f"✅ <b>Подписка активирована (тестовый режим)!</b>\n\n"
                    f"💰 Сумма: <b>{price:.0f} ₽</b>\n"
                    f"📅 Подписка до: <b>{expires_str}</b>\n\n"
                    f"🔑 Перейдите в «Мой VPN» → «Мои ключи», чтобы получить ключ."
                ),
                parse_mode="HTML",
                reply_markup=payment_success_keyboard(),
            )
            logger.info("Test subscription activated for user %d", user_id)
        except BackendAPIError as exc:
            logger.error("Test subscription activation failed for user %d: %s", user_id, exc)
            await callback.message.edit_text(
                text=f"⚠️ Ошибка активации: {exc.detail}",
                reply_markup=back_to_main_keyboard(),
            )
        return

    # Обычный режим – показываем выбор способа оплаты
    await _show_payment_methods(callback, state, kind="subscription")


@router.callback_query(F.data == "device_slot:confirm")
async def callback_choose_device_slot_payment(callback: CallbackQuery, state: FSMContext) -> None:
    """Докупка места – всегда через выбор платежа (тестовый режим не применяется)."""
    await _show_payment_methods(callback, state, kind="device_slot")


# ── YooKassa ──────────────────────────────────────────────────────────────────

def _payment_detail_line(kind: str, days: int) -> str:
    if kind == "device_slot":
        return "Покупка: <b>+1 устройство</b> (навсегда)"
    return f"Подписка: <b>{days} дней</b>"


def _back_to_methods_callback(kind: str) -> str:
    return "device_slot:confirm" if kind == "device_slot" else "subscription:confirm"


@router.callback_query(PaymentStates.choosing_method, F.data.startswith("pay:yookassa"))
async def pay_yookassa(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("⏳ Создаю ссылку на оплату...")

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
    Активирует подписку в vpn_platform после подтверждения оплаты.

    ВАЖНО: vpn_platform::/internal/subscription/buy НЕ провижинит сервера
    и не выдаёт устройства сама — она только двигает дату подписки (см.
    docstring app/api/routers/internal.py на стороне платформы). Ключи
    выдаются позже, когда пользователь жмёт «Добавить устройство».
    """
    days = int(metadata.get("days", settings.SUBSCRIPTION_DAYS))
    price = float(metadata.get("price", settings.SUBSCRIPTION_PRICE))
    payment_method = metadata.get("payment_method", "unknown")

    try:
        data = await api_client.buy_subscription(telegram_id=telegram_id, days=days)

        expires_str = data.get("expires_at", "—")
        # TODO: реферальный бонус — vpn_platform это поле пока не отдаёт
        # (нет модели Referral), см. api_client.get_referral_stats.
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
                logger.warning(
                    "Failed to notify referrer %d about bonus: %s", referrer_id, exc
                )

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