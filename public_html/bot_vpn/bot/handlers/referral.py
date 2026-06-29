"""
bot/handlers/referral.py — Обработчики раздела «Пригласить друга».

Реферальная система: пользователь делится персональной ссылкой
(https://t.me/<bot>?start=ref_<telegram_id>). Когда приглашённый
переходит по ней и совершает СВОЮ ПЕРВУЮ оплату подписки — рефереру
единоразово начисляется 7 дней подписки. Повторные оплаты приглашённого
бонус больше не дают (см. bot/handlers/payment.py и backend /subscription/buy).

Раздел открывается из ⚙️ Ещё → 👥 Пригласить друга (инлайн-кнопка),
а не с главного меню — частота использования у него ниже, чем у VPN/подписки.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.keyboards import referral_keyboard
from bot.services.api_client import BackendAPIError, api_client

logger = logging.getLogger(__name__)

router = Router(name="referral")

# Сколько дней подписки начисляется рефереру за первую оплату приглашённого.
# Совпадает со значением, которое backend хранит в Referral.bonus_days —
# здесь используется только для текста, реальное начисление считает backend.
REFERRAL_BONUS_DAYS = 7


@router.callback_query(F.data == "menu:referral")
async def handle_referral(callback: CallbackQuery) -> None:
    """
    Показывает реферальную ссылку и статистику приглашений.
    """
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
