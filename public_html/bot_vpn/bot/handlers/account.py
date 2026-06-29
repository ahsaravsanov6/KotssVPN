"""
bot/handlers/account.py — Обработчики раздела «Личный кабинет».

Личный кабинет отвечает за профиль (имя, ID) и устройства.
Статус подписки и дата её окончания показываются на отдельном
едином экране 💳 Подписка (bot/handlers/subscription.py) — чтобы
не дублировать одни и те же данные о подписке в двух разных местах.

Функции _format_subscription_status / _format_expires_at оставлены здесь
и используются в subscription.py — там они формируют единственную
карточку статуса подписки во всём боте.
"""

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import Message

from bot.keyboards.keyboards import account_menu_keyboard
from bot.services.api_client import BackendAPIError, api_client

logger = logging.getLogger(__name__)

router = Router(name="account")


def _format_subscription_status(status: str) -> str:
    """Форматирует статус подписки для отображения."""
    icons = {
        "active": "✅ Активна",
        "inactive": "❌ Неактивна",
        "expired": "⏰ Истекла",
        "none": "➖ Нет подписки",
    }
    return icons.get(status, f"❓ {status}")


def _format_expires_at(expires_at_iso: str | None) -> str:
    """Форматирует дату окончания подписки."""
    if not expires_at_iso:
        return "—"
    try:
        dt = datetime.fromisoformat(expires_at_iso)
        return dt.strftime("%d.%m.%Y %H:%M МСК")
    except ValueError:
        return expires_at_iso


def _build_account_text(user, data: dict) -> str:
    """
    Формирует текст личного кабинета: профиль + устройства, без подписки.
    Используется как обработчиком reply-кнопки здесь, так и инлайн-обработчиком
    в bot/handlers/start.py (одна и та же карточка из разных точек входа).
    """
    devices_count = data.get("devices_count", 0)
    max_devices = data.get("max_devices", 3)
    username = data.get("username") or data.get("first_name") or "Пользователь"

    filled = "🟩" * devices_count
    empty = "⬜" * (max_devices - devices_count)
    devices_bar = filled + empty

    return (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"👋 <b>{username}</b>\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📱 <b>Устройства:</b> {devices_count} / {max_devices}\n"
        f"    {devices_bar}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💡 Статус подписки смотрите в разделе <b>💳 Подписка</b>."
    )


@router.message(F.text == "👤 Личный кабинет")
async def handle_account(message: Message) -> None:
    """
    Отображает личный кабинет пользователя (профиль + устройства).
    Кнопка «Мои устройства» и переход к «Подписка» доступны прямо отсюда.

    Примечание: эта reply-кнопка больше не на главном меню — раздел теперь
    открывается из ⚙️ Ещё → 👤 Личный кабинет, но обработчик сохранён
    для прямых текстовых команд/совместимости.
    """
    user = message.from_user
    if not user:
        return

    try:
        data = await api_client.get_account(telegram_id=user.id)
        text = _build_account_text(user, data)

    except BackendAPIError as exc:
        logger.error("Failed to get account for user %d: %s", user.id, exc)
        if exc.status_code == 404:
            text = (
                "❓ Вы ещё не зарегистрированы.\n"
                "Отправьте команду /start для регистрации."
            )
        else:
            text = f"⚠️ Ошибка загрузки данных. Попробуйте позже.\n\n<code>{exc.detail}</code>"
    except Exception as exc:
        logger.error("Unexpected error in account handler for user %d: %s", user.id, exc, exc_info=True)
        text = "⚠️ Произошла ошибка. Попробуйте позже."

    await message.answer(
        text=text,
        parse_mode="HTML",
        reply_markup=account_menu_keyboard(),
    )
