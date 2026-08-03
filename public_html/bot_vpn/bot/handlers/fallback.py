"""
bot/handlers/fallback.py — Обработчики «краевых» сценариев.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.keyboards import buy_subscription_keyboard, main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router(name="fallback")


# ── /cancel вне FSM ───────────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel_no_state(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer(
            text="ℹ️ Нет активного действия, которое можно отменить.\n\nВыберите раздел:",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await state.clear()
        await message.answer(
            text="❌ Действие отменено.",
            reply_markup=main_menu_keyboard(),
        )


MAIN_MENU_BUTTONS = {
    "🔑 Мой VPN",
    "💳 Подписка",
    "⚙️ Ещё",
}


@router.message(F.text.in_(MAIN_MENU_BUTTONS))
async def handle_menu_button_during_fsm(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer(
            text=(
                "↩️ Действие отменено — вы перешли в другой раздел.\n\n"
                "Если хотели добавить устройство, откройте ⚙️ <b>Ещё</b> → "
                "👤 <b>Личный кабинет</b> → 📱 <b>Мои устройства</b>."
            ),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )


@router.message(F.text)
async def handle_unknown_text(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()

    if current_state:
        await message.answer(
            text=(
                "❓ Не понял ввод. Если хотите отменить — нажмите /cancel.\n\n"
                "Или введите нужное значение."
            ),
        )
        return

    text = message.text or ""

    if text.startswith("/"):
        await message.answer(
            text=(
                f"❓ Команда <code>{text}</code> не найдена.\n\n"
                "Используйте меню ниже:"
            ),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer(
            text=(
                "🤷 Не могу обработать это сообщение.\n\n"
                "Воспользуйтесь кнопками меню:"
            ),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query()
async def handle_unknown_callback(callback: CallbackQuery) -> None:
    await callback.answer(
        text="⏳ Эта кнопка устарела. Пожалуйста, начните заново.",
        show_alert=True,
    )
    logger.debug("Unknown callback from user %d: %s", callback.from_user.id, callback.data)
