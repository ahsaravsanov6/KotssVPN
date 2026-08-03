"""
bot/handlers/start.py — Обработчики команды /start, главного меню и раздела «Ещё».
"""

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from bot.handlers.account import _build_account_text
from bot.keyboards.keyboards import (
    account_menu_keyboard,
    back_to_more_keyboard,
    main_menu_keyboard,
    more_menu_keyboard,
)
from bot.services.api_client import BackendAPIError, api_client
from config import settings

logger = logging.getLogger(__name__)

router = Router(name="start")

NEWS_CHANNEL_URL = getattr(settings, "NEWS_CHANNEL_URL", "https://t.me/peakpeaknews")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    if not user:
        return

    args = message.text.split(maxsplit=1)
    referrer_id: int | None = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
            if referrer_id == user.id:
                referrer_id = None
        except ValueError:
            referrer_id = None

    try:
        result = await api_client.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            referrer_id=referrer_id,
        )

        is_new = result.get("is_new", False)
        logger.info(
            "User %s (id=%d) — %s%s",
            user.username or user.first_name,
            user.id,
            "registered" if is_new else "returned",
            f", referred by {referrer_id}" if (is_new and referrer_id) else "",
        )

        if is_new:
            greeting = (
                f"👋 Добро пожаловать, <b>{user.first_name or 'друг'}</b>!\n\n"
                "Вы зарегистрированы в системе.\n"
                "Для начала работы купите подписку в разделе <b>💳 Подписка</b>."
            )
        else:
            greeting = (
                f"👋 С возвращением, <b>{user.first_name or 'друг'}</b>!\n\n"
                "Выберите раздел в меню ниже."
            )

    except BackendAPIError as exc:
        logger.error("Failed to register user %d: %s", user.id, exc)
        greeting = (
            f"👋 Привет, <b>{user.first_name or 'друг'}</b>!\n\n"
            "⚠️ Временная проблема с сервером. Попробуйте позже."
        )
    except Exception as exc:
        logger.error("Unexpected error on /start for user %d: %s", user.id, exc, exc_info=True)
        greeting = "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже."

    await message.answer(
        text=greeting,
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:main")
async def callback_main_menu(callback: CallbackQuery) -> None:
    await callback.answer()

    if callback.message:
        await callback.message.answer(
            text="🏠 <b>Главное меню</b>\n\nВыберите раздел:",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@router.message(F.text == "⚙️ Ещё")
async def handle_more_menu(message: Message) -> None:
    await message.answer(
        text="⚙️ <b>Ещё</b>\n\nВыберите раздел:",
        reply_markup=more_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:more")
async def callback_more_menu(callback: CallbackQuery) -> None:
    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            text="⚙️ <b>Ещё</b>\n\nВыберите раздел:",
            reply_markup=more_menu_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "menu:account")
async def callback_account_menu(callback: CallbackQuery) -> None:
    await callback.answer()

    user = callback.from_user
    if not user or not callback.message:
        return

    try:
        data = await api_client.get_account(telegram_id=user.id)
        text = _build_account_text(user, data)
    except Exception:
        text = "👤 <b>Личный кабинет</b>\n\nВыберите действие:"

    await callback.message.edit_text(
        text=text,
        reply_markup=account_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:news")
async def callback_news_channel(callback: CallbackQuery) -> None:
    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            text=(
                "📢 <b>Наш новостной канал</b>\n\n"
                "Подписывайтесь, чтобы получать актуальные новости, "
                "анонсы обновлений и уведомления о сервисе:\n\n"
                f"👉 {NEWS_CHANNEL_URL}"
            ),
            reply_markup=back_to_more_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.callback_query(F.data == "menu:support")
async def callback_support(callback: CallbackQuery) -> None:
    await callback.answer()

    text = (
        "🆘 <b>Поддержка</b>\n\n"
        "Если у вас возникли проблемы с VPN, обратитесь к нашей поддержке:\n\n"
        "✉️ @peak_help\n"
        "Мы отвечаем в рабочее время: Пн-Пт, 10:00–19:00 МСК.\n\n"
        "🕐 Среднее время ответа: 30 минут."
    )

    if callback.message:
        await callback.message.edit_text(
            text=text,
            parse_mode="HTML",
            reply_markup=back_to_more_keyboard(),
        )
