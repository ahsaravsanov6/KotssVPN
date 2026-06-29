"""
bot/handlers/vpn.py — Обработчики раздела «Мой VPN».

Содержит:
- Показ меню VPN (с проверкой подписки)
- Выбор устройства и получение ключа (конфига) для НЕГО конкретно
- Перегенерация ключа конкретного устройства (с подтверждением)
- Инструкция по подключению (теперь через кнопки-ссылки на telegra.ph)
"""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.keyboards.keyboards import (
    INSTRUCTION_URL_ANDROID,
    INSTRUCTION_URL_IPHONE_MACOS,
    INSTRUCTION_URL_WINDOWS,
    back_to_vpn_keyboard,
    confirm_regenerate_keyboard,
    device_key_keyboard,
    device_select_keyboard,
    devices_menu_keyboard,
    instructions_keyboard,
    main_menu_keyboard,
    vpn_menu_keyboard,
)
from bot.services.api_client import BackendAPIError, api_client
from bot.services.subscription_guard import require_subscription

logger = logging.getLogger(__name__)

router = Router(name="vpn")


async def _safe_edit_text(message, **kwargs) -> None:
    """
    Обёртка над message.edit_text, которая тихо проглатывает ошибку
    "message is not modified".
    """
    try:
        await message.edit_text(**kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            logger.debug("edit_text skipped: content unchanged (%s)", message.message_id)
            return
        raise


def _get_instruction_url(device_name: str) -> str | None:
    """
    Возвращает ссылку на инструкцию для платформы, определённой по имени устройства.
    """
    if "🍎" in device_name or "iOS" in device_name:
        return INSTRUCTION_URL_IPHONE_MACOS
    if "🤖" in device_name or "Android" in device_name:
        return INSTRUCTION_URL_ANDROID
    if "💻" in device_name or "Desktop" in device_name:
        return INSTRUCTION_URL_WINDOWS
    return None


@router.message(F.text == "🔑 Мой VPN")
async def handle_vpn_menu(message: Message) -> None:
    """Показывает меню раздела 'Мой VPN'. Требует активную подписку."""
    if not await require_subscription(message):
        return

    await message.answer(
        text=(
            "🔑 <b>Мой VPN</b>\n\n"
            "Выберите действие:"
        ),
        reply_markup=vpn_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:vpn")
async def callback_vpn_menu(callback: CallbackQuery) -> None:
    """Возврат в меню VPN по инлайн-кнопке."""
    await callback.answer()
    if callback.message:
        await _safe_edit_text(callback.message,
            text="🔑 <b>Мой VPN</b>\n\nВыберите действие:",
            reply_markup=vpn_menu_keyboard(),
            parse_mode="HTML",
        )


# ── Выбор устройства (точка входа вместо прямой выдачи ключа) ────────────────

@router.callback_query(F.data == "vpn:select_device")
async def callback_select_device(callback: CallbackQuery) -> None:
    """
    Показывает список устройств пользователя для выбора, чей ключ показать.
    """
    await callback.answer()

    user = callback.from_user
    if not user or not callback.message:
        return

    try:
        data = await api_client.get_devices(telegram_id=user.id)
        devices = data.get("devices", [])
    except BackendAPIError as exc:
        logger.error("vpn: API error getting devices for user %d: %s", user.id, exc)
        await _safe_edit_text(callback.message,
            text=f"⚠️ Ошибка загрузки устройств.\n\n<code>{exc.detail}</code>",
            reply_markup=back_to_vpn_keyboard(),
            parse_mode="HTML",
        )
        return
    except Exception as exc:
        logger.error("vpn: unexpected error getting devices for user %d: %s", user.id, exc, exc_info=True)
        await _safe_edit_text(callback.message,
            text="⚠️ Произошла ошибка. Попробуйте позже.",
            reply_markup=back_to_vpn_keyboard(),
        )
        return

    if not devices:
        await _safe_edit_text(callback.message,
            text=(
                "📭 <b>У вас пока нет добавленных устройств</b>\n\n"
                "Чтобы получить VPN-ключ, сначала добавьте устройство — "
                "у каждого устройства будет свой отдельный ключ."
            ),
            reply_markup=devices_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    await _safe_edit_text(callback.message,
        text="🔑 <b>Мои ключи</b>\n\nВыберите устройство, чтобы получить его ключ:",
        reply_markup=device_select_keyboard(devices, action="get_config"),
        parse_mode="HTML",
    )


# ── Получение ключа конкретного устройства ────────────────────────────────────

@router.callback_query(F.data.startswith("vpn:get_config:"))
async def callback_get_config(callback: CallbackQuery) -> None:
    """Запрашивает VPN конфигурацию конкретного устройства и отправляет пользователю."""
    await callback.answer("🔄 Загружаю конфигурацию...")

    user = callback.from_user
    if not user:
        return

    device_id = int(callback.data.split(":")[-1])
    await _send_device_config(callback, user.id, device_id)


async def _send_device_config(callback: CallbackQuery, telegram_id: int, device_id: int) -> None:
    """Общая логика показа конфига устройства."""
    try:
        data = await api_client.get_vpn_config(telegram_id=telegram_id, device_id=device_id)

        if not data.get("success"):
            msg = data.get("message", "Неизвестная ошибка")
            await _safe_edit_text(callback.message,
                text=(
                    f"❌ <b>Конфигурация недоступна</b>\n\n"
                    f"{msg}\n\n"
                    f"💡 Убедитесь, что у вас активная подписка."
                ),
                reply_markup=back_to_vpn_keyboard(),
                parse_mode="HTML",
            )
            return

        config_text = data.get("config_text", "")
        qr_url = data.get("qr_code_url", "")
        uuid_short = data.get("uuid", "")[:8] if data.get("uuid") else "N/A"
        device_name = data.get("device_name", "устройство")

        text = (
            f"🔑 <b>Ключ для устройства: {device_name}</b>\n\n"
            f"🆔 UUID: <code>{uuid_short}...</code>\n\n"
            f"📋 <b>Ссылка на подписку:</b>\n"
            f"<a href=\"{config_text}\">{config_text}</a>\n\n"
            f"📱 Нажмите на ссылку выше, чтобы открыть её в браузере и "
            f"добавить подписку в приложение, либо отсканируйте QR-код.\n\n"
            f"🔗 <a href=\"{qr_url}\">Открыть QR-код</a>\n"
        )

        # Добавляем ссылку на инструкцию для конкретной платформы
        instruction_url = _get_instruction_url(device_name)
        if instruction_url:
            text += f"\n\n📖 <a href=\"{instruction_url}\">Как подключиться?</a> — инструкция для вашей платформы."

        text += (
            f"\n\n<i>Поддерживаемые приложения: Happ, v2rayNG, Hiddify, Streisand, Nekoray</i>\n\n"
            f"⚠️ <i>Этот ключ предназначен для устройства «{device_name}» и ограничен "
            f"одним одновременным подключением. Для другого устройства используйте "
            f"его собственный ключ из раздела «Мои устройства».</i>"
        )

        await _safe_edit_text(callback.message,
            text=text,
            reply_markup=device_key_keyboard(device_id),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        logger.info("VPN config sent to user %d for device %d", telegram_id, device_id)

    except BackendAPIError as exc:
        logger.error("API error getting config for user %d device %d: %s", telegram_id, device_id, exc)
        await _safe_edit_text(callback.message,
            text=f"⚠️ Ошибка сервера: {exc.detail}",
            reply_markup=back_to_vpn_keyboard(),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Unexpected error in get_config for user %d device %d: %s", telegram_id, device_id, exc, exc_info=True)
        await _safe_edit_text(callback.message,
            text="⚠️ Произошла ошибка. Попробуйте позже.",
            reply_markup=back_to_vpn_keyboard(),
        )


# ── Перегенерация ключа конкретного устройства ────────────────────────────────

@router.callback_query(F.data.startswith("vpn:regenerate:"))
async def callback_regenerate_confirm(callback: CallbackQuery) -> None:
    """Показывает предупреждение перед перегенерацией ключа конкретного устройства."""
    await callback.answer()

    device_id = int(callback.data.split(":")[-1])

    if callback.message:
        await _safe_edit_text(callback.message,
            text=(
                "♻️ <b>Перегенерация ключа</b>\n\n"
                "⚠️ <b>Внимание!</b> После перегенерации:\n"
                "• Текущий конфиг этого устройства перестанет работать\n"
                "• Нужно будет заново импортировать конфиг в приложение на этом устройстве\n\n"
                "Вы уверены, что хотите продолжить?"
            ),
            reply_markup=confirm_regenerate_keyboard(device_id),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("vpn:confirm_regenerate:"))
async def callback_do_regenerate(callback: CallbackQuery) -> None:
    """Выполняет перегенерацию ключа устройства после подтверждения."""
    await callback.answer("🔄 Перегенерирую ключ...")

    user = callback.from_user
    if not user:
        return

    device_id = int(callback.data.split(":")[-1])

    try:
        data = await api_client.regenerate_vpn_key(telegram_id=user.id, device_id=device_id)

        if not data.get("success"):
            await _safe_edit_text(callback.message,
                text=f"❌ Ошибка: {data.get('message', 'Неизвестная ошибка')}",
                reply_markup=back_to_vpn_keyboard(),
                parse_mode="HTML",
            )
            return

        new_uuid_short = data.get("new_uuid", "")[:8] if data.get("new_uuid") else "N/A"

        await _safe_edit_text(callback.message,
            text=(
                f"✅ <b>Ключ успешно перегенерирован!</b>\n\n"
                f"🆔 Новый UUID: <code>{new_uuid_short}...</code>\n\n"
                f"Получите новый ключ для этого устройства ниже.\n\n"
                f"⚠️ Старый конфиг этого устройства больше не работает!"
            ),
            reply_markup=device_key_keyboard(device_id),
            parse_mode="HTML",
        )

        logger.info("VPN key regenerated for user %d device %d", user.id, device_id)

    except BackendAPIError as exc:
        logger.error("API error regenerating key for user %d device %d: %s", user.id, device_id, exc)
        await _safe_edit_text(callback.message,
            text=f"⚠️ Ошибка сервера: {exc.detail}",
            reply_markup=back_to_vpn_keyboard(),
        )
    except Exception as exc:
        logger.error("Unexpected error regenerating key for user %d device %d: %s", user.id, device_id, exc, exc_info=True)
        await _safe_edit_text(callback.message,
            text="⚠️ Произошла ошибка. Попробуйте позже.",
            reply_markup=back_to_vpn_keyboard(),
        )


# ── Инструкция (теперь через кнопки-ссылки) ──────────────────────────────────

@router.callback_query(F.data == "vpn:instructions")
async def callback_vpn_instructions(callback: CallbackQuery) -> None:
    """Инструкция по подключению VPN — показывает кнопки выбора платформы."""
    await callback.answer()

    if callback.message:
        await _safe_edit_text(callback.message,
            text="📖 <b>Инструкция по подключению</b>\n\nВыберите вашу платформу:",
            reply_markup=instructions_keyboard(),
            parse_mode="HTML",
        )