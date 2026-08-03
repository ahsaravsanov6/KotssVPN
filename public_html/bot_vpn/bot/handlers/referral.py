"""
bot/handlers/referral.py — Обработчики раздела «Пригласить друга».

ВАЖНО: vpn_platform пока не содержит реферальной системы (нет модели
Referral) — api_client.get_referral_stats() возвращает нули-заглушку,
пока эта логика не перенесена отдельным шагом на сторону vpn_platform
(app/db/models/referral.py + начисление бонуса в UserService/internal
subscription/buy). Экран не падает, просто показывает 0 по всем полям.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.keyboards import referral_keyboard
from bot.services.api_client import BackendAPIError, api_client

logger = logging.getLogger(__name__)

router = Router(name="referral")

REFERRAL_BONUS_DAYS = 7


@router.callback_query(F.data == "menu:referral")
async def handle_referral(callback: CallbackQuery) -> None:
    await callback.answer()

    user = callback.from_user
    if not user or not callback.message:
        return

    bot = callback.bot
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"

    try:
        stats = await api_client.get_referral_stats(telegram_id=user.id)
        invited_count = stats.get("invited_count", 0)
        bonus_days = stats.get("bonus_days", 0)
        pending_count = stats.get("pending_count", 0)
    except BackendAPIError as exc:
        logger.error("referral: API error getting stats for user %d: %s", user.id, exc)
        invited_count = bonus_days = pending_count = 0
    except Exception as exc:
        logger.error("referral: unexpected error for user %d: %s", user.id, exc, exc_info=True)
        invited_count = bonus_days = pending_count = 0

    pending_line = (
        f"⏳ <b>Ожидают первой оплаты:</b> {pending_count}\n"
        if pending_count else ""
    )

    text = (
        "👥 <b>Пригласить друга</b>\n\n"
        f"Поделитесь своей реферальной ссылкой — за каждого друга, который "
        f"оплатит подписку в первый раз, вы получите "
        f"<b>+{REFERRAL_BONUS_DAYS} дней</b> подписки!\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 <b>Приглашено друзей:</b> {invited_count}\n"
        f"{pending_line}"
        f"🎁 <b>Начислено бонусных дней:</b> {bonus_days}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        "💡 <i>Бонус начисляется один раз за каждого приглашённого — "
        "именно за его первую оплату подписки.</i>"
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=referral_keyboard(bot_username=bot_username, ref_link=ref_link),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
