"""
bot/handlers/subscription.py — Единый экран «Подписка»: статус + покупка/продление.

Это единственное место в боте, где показывается статус подписки и дата
её окончания (раньше статус дублировался также в личном кабинете —
см. историю изменений в account.py). Если у пользователя нет активной
подписки — показывается предложение купить. Если подписка активна —
показывается дата окончания и кнопка продления.

Перед переходом к оплате показывается экран с публичной офертой —
пользователь должен подтвердить, что ознакомился и согласен с условиями
(callback_query(F.data == "subscription:offer")).

Само создание платежа (выбор способа оплаты: YooKassa / CryptoBot / Heleket,
формирование ссылки на оплату) обрабатывается в bot/handlers/payment.py —
см. там callback_query(F.data == "subscription:confirm").
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.handlers.account import _format_expires_at, _format_subscription_status
from bot.keyboards.keyboards import (
    buy_subscription_keyboard,
    offer_confirmation_keyboard,
    payment_success_keyboard,
)
from bot.services.api_client import BackendAPIError, api_client
from config import settings

logger = logging.getLogger(__name__)

router = Router(name="subscription")


def _build_subscription_text(data: dict) -> tuple[str, bool, bool]:
    """
    Формирует текст единого экрана подписки.

    Returns:
        (текст, has_active_subscription, trial_available) — флаги нужны
        клавиатуре, чтобы показать «Оплатить» (нет подписки) или
        «Продлить» + переход в VPN (подписка активна), а также кнопку
        пробного периода, если он включён в .env (TRIAL_ENABLED) и ещё
        не был использован пользователем (проверяет backend).
    """
    status = data.get("subscription_status", "none")
    sub_status = _format_subscription_status(status)
    expires_at = _format_expires_at(data.get("subscription_expires_at"))
    is_active = status == "active"
    trial_available = bool(getattr(settings, "TRIAL_ENABLED", False)) and bool(data.get("trial_available"))

    header = (
        f"💳 <b>Подписка</b>\n\n"
        f"📋 <b>Статус:</b> {sub_status}\n"
        f"📅 <b>Действует до:</b> {expires_at}\n\n"
        f"━━━━━━━━━━━━━━━\n\n"
    )

    plan_details = (
        f"📦 <b>VPN Подписка — {settings.SUBSCRIPTION_DAYS} дней</b>\n\n"
        f"✅ Неограниченный трафик\n"
        f"✅ До {settings.DEFAULT_MAX_DEVICES} устройств одновременно\n"
        f"✅ Высокая скорость\n"
        f"✅ Серверы в разных странах\n"
        f"✅ Поддержка VLESS/Xray протокола\n\n"
        f"💰 <b>Стоимость:</b> {settings.SUBSCRIPTION_PRICE:.0f} ₽\n\n"
    )

    if is_active:
        footer = "✅ Ваш VPN активен. Хотите продлить заранее — нажмите кнопку ниже."
    elif trial_available:
        footer = (
            f"🎁 Вам доступен бесплатный пробный период на {settings.TRIAL_DAYS} дн. — "
            "попробуйте VPN перед покупкой!\n\n"
            "Нажмите <b>✅ Оплатить</b>, чтобы купить сразу, или возьмите пробный период выше."
        )
    else:
        footer = "Нажмите <b>✅ Оплатить</b>, чтобы продолжить."

    return header + plan_details + footer, is_active, trial_available


async def _show_subscription_screen(telegram_id: int) -> tuple[str, bool, bool]:
    """Запрашивает статус подписки у backend и собирает текст экрана."""
    try:
        data = await api_client.get_account(telegram_id=telegram_id)
        return _build_subscription_text(data)
    except BackendAPIError as exc:
        logger.error("subscription: API error for user %d: %s", telegram_id, exc)
        if exc.status_code == 404:
            text = (
                "❓ Вы ещё не зарегистрированы.\n"
                "Отправьте команду /start для регистрации."
            )
        else:
            text = f"⚠️ Ошибка загрузки данных. Попробуйте позже.\n\n<code>{exc.detail}</code>"
        return text, False, False
    except Exception as exc:
        logger.error("subscription: unexpected error for user %d: %s", telegram_id, exc, exc_info=True)
        return "⚠️ Произошла ошибка. Попробуйте позже.", False, False


@router.message(F.text == "💳 Подписка")
async def handle_subscription_screen(message: Message) -> None:
    """
    Единый экран подписки: показывает текущий статус и предлагает
    оплатить (если подписки нет) или продлить (если она активна).
    """
    user = message.from_user
    if not user:
        return

    text, is_active, trial_available = await _show_subscription_screen(user.id)

    await message.answer(
        text=text,
        reply_markup=buy_subscription_keyboard(has_active_subscription=is_active, trial_available=trial_available),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:subscription")
async def callback_subscription_screen(callback: CallbackQuery) -> None:
    """Тот же единый экран подписки, но как инлайн-переход (например, из личного кабинета)."""
    await callback.answer()

    user = callback.from_user
    if not user or not callback.message:
        return

    text, is_active, trial_available = await _show_subscription_screen(user.id)

    await callback.message.edit_text(
        text=text,
        reply_markup=buy_subscription_keyboard(has_active_subscription=is_active, trial_available=trial_available),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "subscription:offer")
async def callback_show_offer(callback: CallbackQuery) -> None:
    """
    Показывает условия публичной оферты перед переходом к оплате.
    Пользователь должен явно подтвердить согласие кнопкой,
    прежде чем попасть в payment.py (subscription:confirm).
    """
    await callback.answer()

    offer_url = settings.OFFER_URL
    price = settings.SUBSCRIPTION_PRICE
    days = settings.SUBSCRIPTION_DAYS

    text = (
        f"📄 <b>Перед оплатой</b>\n\n"
        f"Подписка на <b>{days} дней</b> — <b>{price:.0f} ₽</b>\n\n"
        f"Прежде чем перейти к оплате, ознакомьтесь с условиями "
        f"публичной оферты по кнопке ниже.\n\n"
        f"Нажимая «✅ Согласен, перейти к оплате», вы подтверждаете, "
        f"что ознакомились и согласны с условиями публичной оферты."
    )

    if callback.message:
        await callback.message.edit_text(
            text=text,
            reply_markup=offer_confirmation_keyboard(offer_url),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "subscription:trial")
async def callback_start_trial(callback: CallbackQuery) -> None:
    """
    Активация бесплатного пробного периода — без экрана оферты и без
    выбора способа оплаты, т.к. деньги не участвуют. Кнопка показывается
    только если TRIAL_ENABLED=true в .env и backend подтвердил, что
    пользователь ещё не использовал триал (см. trial_available в
    /users/account и buy_subscription_keyboard).

    Backend всё равно перепроверяет это сам (см. /subscription/trial) —
    клавиатура лишь скрывает кнопку, а не является единственной защитой.
    """
    await callback.answer()

    user = callback.from_user
    if not user or not callback.message:
        return

    if not getattr(settings, "TRIAL_ENABLED", False):
        await callback.message.answer("⚠️ Пробный период сейчас недоступен.")
        return

    try:
        data = await api_client.start_trial(telegram_id=user.id, days=settings.TRIAL_DAYS)
    except BackendAPIError as exc:
        logger.error("subscription: trial activation API error for user %d: %s", user.id, exc)
        await callback.message.answer("⚠️ Не удалось активировать пробный период. Попробуйте позже.")
        return
    except Exception as exc:
        logger.error("subscription: unexpected trial error for user %d: %s", user.id, exc, exc_info=True)
        await callback.message.answer("⚠️ Произошла ошибка. Попробуйте позже.")
        return

    if not data.get("success"):
        # Например: "Пробный период уже был использован." или
        # "доступен только новым пользователям без подписки."
        await callback.message.answer(f"ℹ️ {data.get('message', 'Пробный период недоступен.')}")
        return

    expires_str = _format_expires_at(data.get("expires_at"))
    days = data.get("days", settings.TRIAL_DAYS)

    await callback.message.answer(
        text=(
            f"🎁 <b>Пробный период активирован!</b>\n\n"
            f"Вам доступен VPN на <b>{days} {_ru_days_word(days)}</b> бесплатно.\n"
            f"📅 Действует до: <b>{expires_str}</b>\n\n"
            f"🔑 Добавьте устройство в «Мои устройства», чтобы получить ключ."
        ),
        parse_mode="HTML",
        reply_markup=payment_success_keyboard(),
    )


def _ru_days_word(n: int) -> str:
    """Правильное склонение слова 'день' для русского языка (1 день, 2 дня, 5 дней)."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"
