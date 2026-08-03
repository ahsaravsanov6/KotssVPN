"""
bot/services/subscription_guard.py — Хелпер проверки активной подписки.
"""

import logging
from typing import Union

from aiogram.types import CallbackQuery, Message

from bot.keyboards.keyboards import buy_subscription_keyboard, main_menu_keyboard
from bot.services.api_client import BackendAPIError, api_client

logger = logging.getLogger(__name__)


async def require_subscription(
    event: Union[Message, CallbackQuery],
    *,
    answer_callback: bool = True,
) -> bool:
    user = event.from_user
    if not user:
        return False

    try:
        data = await api_client.get_account(telegram_id=user.id)
    except BackendAPIError as exc:
        logger.warning("subscription_guard: API error for user %d: %s", user.id, exc)
        if exc.status_code == 404:
            await _send_not_registered(event, answer_callback)
        else:
            await _send_error(event, answer_callback)
        return False
    except Exception as exc:
        logger.error("subscription_guard: unexpected error for user %d: %s", user.id, exc)
        await _send_error(event, answer_callback)
        return False

    status = data.get("subscription_status", "none")
    if status == "active":
        return True

    if status == "expired":
        await _send_expired(event, answer_callback)
    else:
        await _send_no_subscription(event, answer_callback)

    return False


async def _reply(
    event: Union[Message, CallbackQuery],
    text: str,
    answer_callback: bool,
    **kwargs,
) -> None:
    if isinstance(event, CallbackQuery):
        if answer_callback:
            await event.answer()
        if event.message:
            await event.message.answer(text=text, **kwargs)
    else:
        await event.answer(text=text, **kwargs)


async def _send_no_subscription(
    event: Union[Message, CallbackQuery],
    answer_callback: bool,
) -> None:
    await _reply(
        event,
        text=(
            "🔒 <b>Нет активной подписки</b>\n\n"
            "Для использования этой функции необходима подписка.\n\n"
            "💳 Оформите подписку — это займёт меньше минуты:"
        ),
        answer_callback=answer_callback,
        reply_markup=buy_subscription_keyboard(),
        parse_mode="HTML",
    )


async def _send_expired(
    event: Union[Message, CallbackQuery],
    answer_callback: bool,
) -> None:
    await _reply(
        event,
        text=(
            "⏰ <b>Подписка истекла</b>\n\n"
            "Ваш VPN приостановлен. Продлите подписку, чтобы продолжить:"
        ),
        answer_callback=answer_callback,
        reply_markup=buy_subscription_keyboard(),
        parse_mode="HTML",
    )


async def _send_not_registered(
    event: Union[Message, CallbackQuery],
    answer_callback: bool,
) -> None:
    await _reply(
        event,
        text=(
            "👋 Кажется, вы ещё не зарегистрированы.\n\n"
            "Отправьте команду /start — это займёт секунду."
        ),
        answer_callback=answer_callback,
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


async def _send_error(
    event: Union[Message, CallbackQuery],
    answer_callback: bool,
) -> None:
    await _reply(
        event,
        text="⚠️ Не удалось проверить статус подписки. Попробуйте позже.",
        answer_callback=answer_callback,
        reply_markup=main_menu_keyboard(),
    )
