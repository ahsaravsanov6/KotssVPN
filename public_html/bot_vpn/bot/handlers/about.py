"""
bot/handlers/about.py — Обработчик раздела «О нас».

Отображает информацию о владельце сервиса (реквизиты, контакты)
и ссылку на политику конфиденциальности.

Раздел теперь открывается из ⚙️ Ещё → ℹ️ О нас (инлайн-кнопка),
а не с главного меню — обращаются к нему редко.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.keyboards import about_keyboard
from config import settings

logger = logging.getLogger(__name__)

router = Router(name="about")


@router.callback_query(F.data == "menu:about")
async def handle_about(callback: CallbackQuery) -> None:
    """Показывает информацию о владельце сервиса и ссылку на политику конфиденциальности."""
    await callback.answer()

    if not callback.message:
        return

    ogrnip_line = (
        f"📋 <b>ОГРНИП:</b> <code>{settings.OWNER_OGRNIP}</code>\n"
        if settings.OWNER_OGRNIP else ""
    )

    text = (
        f"ℹ️ <b>О нас</b>\n\n"
        f"👤 <b>Владелец сервиса:</b>\n"
        f"{settings.OWNER_FULL_NAME}\n\n"
        f"📋 <b>ИНН:</b> <code>{settings.OWNER_INN}</code>\n"
        f"{ogrnip_line}"
        f"📧 <b>Контакты:</b> {settings.OWNER_CONTACT_EMAIL}\n\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Используя бота, вы соглашаетесь с условиями "
        f"публичной оферты и политики конфиденциальности.\n\n"
        f"Ознакомиться с политикой конфиденциальности можно по кнопке ниже."
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=about_keyboard(settings.PRIVACY_POLICY_URL),
        parse_mode="HTML",
    )
