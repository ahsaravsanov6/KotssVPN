"""
bot/handlers/vpn.py — Обработчики раздела «Мой VPN» (per-device, vpn_platform).

Модель осталась прежней с точки зрения пользователя: одно устройство —
один ключ/ссылка. Изменилось только то, что происходит "под капотом" —
см. bot/services/api_client.py и vpn_platform/app/providers/xui/client.py:
один и тот же UUID устройства теперь реплицируется во все активные
панели (по числу серверов), а ссылка, которую видит пользователь
(GET /sub/<token>/<device_id> на стороне платформы), уже сама включает
записи со всех этих серверов.

Раньше (public_html/backend) конфиг устройства запрашивался отдельным
эндпоинтом /vpn/config/{tid}/{device_id}. Сейчас ссылка уже приходит
вместе со списком устройств (api_client.get_devices), отдельный запрос
не нужен — экран просто берёт нужное устройство из уже полученного списка.
"""

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.keyboards.keyboards import (
    back_to_vpn_keyboard,
    confirm_regenerate_keyboard,
    device_link_keyboard,
    device_select_keyboard,
    devices_menu_keyboard,
    instructions_keyboard,
    vpn_menu_keyboard,
)
from bot.services.api_client import BackendAPIError, api_client
from bot.services.subscription_guard import require_subscription

logger = logging.getLogger(__name__)

router = Router(name="vpn")


async def _safe_edit_text(message, **kwargs) -> None:
    """Обёртка над message.edit_text, тихо проглатывающая "message is not modified"."""
    try:
        await message.edit_text(**kwargs)
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            logger.debug("edit_text skipped: content unchanged (%s)", message.message_id)
            return
        raise


def _get_instruction_url(device_name: str) -> str | None:
    from bot.keyboards.keyboards import (
        INSTRUCTION_URL_ANDROID,
        INSTRUCTION_URL_IPHONE_MACOS,
        INSTRUCTION_URL_WINDOWS,
    )
    if "🍎" in device_name or "iOS" in device_name:
        return INSTRUCTION_URL_IPHONE_MACOS
    if "🤖" in device_name or "Android" in device_name:
        return INSTRUCTION_URL_ANDROID
    if "💻" in device_name or "Desktop" in device_name:
        return INSTRUCTION_URL_WINDOWS
    return None


@router.message(F.text == "🔑 Мой VPN")
async def handle_vpn_menu(message: Message) -> None:
    if not await require_subscription(message):
        return

    await message.answer(
        text="🔑 <b>Мой VPN</b>\n\nВыберите действие:",
        reply_markup=vpn_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:vpn")
async def callback_vpn_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await _safe_edit_text(
            callback.message,
            text="🔑 <b>Мой VPN</b>\n\nВыберите действие:",
            reply_markup=vpn_menu_keyboard(),
            parse_mode="HTML",
        )


# ── Выбор устройства ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "vpn:select_device")
async def callback_select_device(callback: CallbackQuery) -> None:
    """Показывает список устройств пользователя для выбора, чью ссылку показать."""
    await callback.answer()

    user = callback.from_user
    if not user or not callback.message:
        return

    try:
        data = await api_client.get_devices(telegram_id=user.id)
        devices = data.get("devices", [])
    except BackendAPIError as exc:
        logger.error("vpn: API error getting devices for user %d: %s", user.id, exc)
        await _safe_edit_text(
            callback.message,
            text=f"⚠️ Ошибка загрузки устройств.\n\n<code>{exc.detail}</code>",
            reply_markup=back_to_vpn_keyboard(),
            parse_mode="HTML",
        )
        return
    except Exception as exc:
        logger.error("vpn: unexpected error getting devices for user %d: %s", user.id, exc, exc_info=True)
        await _safe_edit_text(
            callback.message,
            text="⚠️ Произошла ошибка. Попробуйте позже.",
            reply_markup=back_to_vpn_keyboard(),
        )
        return

    if not devices:
        await _safe_edit_text(
            callback.message,
            text=(
                "📭 <b>У вас пока нет добавленных устройств</b>\n\n"
                "Чтобы получить VPN-ключ, сначала добавьте устройство — "
                "у каждого устройства будет свой отдельный ключ."
            ),
            reply_markup=devices_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    await _safe_edit_text(
        callback.message,
        text="🔑 <b>Мои ключи</b>\n\nВыберите устройство, чтобы получить его ключ:",
        reply_markup=device_select_keyboard(devices, action="get_link"),
        parse_mode="HTML",
    )


# ── Получение ссылки конкретного устройства ────────────────────────────────────

@router.callback_query(F.data.startswith("vpn:get_link:"))
async def callback_get_link(callback: CallbackQuery) -> None:
    """Показывает ссылку подписки конкретного устройства."""
    await callback.answer("🔄 Загружаю ключ...")

    user = callback.from_user
    if not user:
        return

    device_id = int(callback.data.split(":")[-1])
    await _send_device_link(callback, user.id, device_id)


async def _send_device_link(callback: CallbackQuery, telegram_id: int, device_id: int) -> None:
    """
    Берёт список устройств (там уже лежит персональная sub_url на каждое)
    и показывает ссылку/QR для конкретного device_id.
    """
    try:
        data = await api_client.get_devices(telegram_id=telegram_id)
        devices = {d["id"]: d for d in data.get("devices", [])}
        device = devices.get(device_id)

        if not device:
            await _safe_edit_text(
                callback.message,
                text="❌ Устройство не найдено. Возможно, оно было удалено.",
                reply_markup=back_to_vpn_keyboard(),
            )
            return

        sub_url = device.get("sub_url", "")
        device_name = device.get("device_name", "устройство")

        if not sub_url:
            await _safe_edit_text(
                callback.message,
                text=(
                    "❌ <b>Ключ недоступен</b>\n\n"
                    "Убедитесь, что у вас активная подписка."
                ),
                reply_markup=back_to_vpn_keyboard(),
                parse_mode="HTML",
            )
            return

        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={sub_url}"

        text = (
            f"🔑 <b>Ключ для устройства: {device_name}</b>\n\n"
            f"📋 <b>Ссылка на подписку:</b>\n"
            f"<a href=\"{sub_url}\">{sub_url}</a>\n\n"
            f"📱 Нажмите на ссылку выше, чтобы открыть её в браузере и "
            f"добавить подписку в приложение, либо отсканируйте QR-код.\n\n"
            f"🔗 <a href=\"{qr_url}\">Открыть QR-код</a>\n"
        )

        instruction_url = _get_instruction_url(device_name)
        if instruction_url:
            text += f"\n\n📖 <a href=\"{instruction_url}\">Как подключиться?</a> — инструкция для вашей платформы."

        text += (
            f"\n\n<i>Поддерживаемые приложения: Happ, v2rayNG, Hiddify, Streisand, Nekoray</i>\n\n"
            f"⚠️ <i>Эта ссылка предназначена для устройства «{device_name}» и ограничена "
            f"одним одновременным подключением. Для другого устройства используйте "
            f"его собственную ссылку из раздела «Мои устройства».</i>"
        )

        await _safe_edit_text(
            callback.message,
            text=text,
            reply_markup=device_link_keyboard(device_id),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        logger.info("VPN link sent to user %d for device %d", telegram_id, device_id)

    except BackendAPIError as exc:
        logger.error("API error getting link for user %d device %d: %s", telegram_id, device_id, exc)
        await _safe_edit_text(
            callback.message,
            text=f"⚠️ Ошибка сервера: {exc.detail}",
            reply_markup=back_to_vpn_keyboard(),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Unexpected error in get_link for user %d device %d: %s", telegram_id, device_id, exc, exc_info=True)
        await _safe_edit_text(
            callback.message,
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
        await _safe_edit_text(
            callback.message,
            text=(
                "♻️ <b>Перегенерация ключа</b>\n\n"
                "⚠️ <b>Внимание!</b> После перегенерации:\n"
                "• Текущий конфиг этого устройства перестанет работать на всех серверах\n"
                "• Нужно будет заново импортировать ссылку в приложение на этом устройстве\n\n"
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
        await api_client.regenerate_device(telegram_id=user.id, device_id=device_id)

        await _safe_edit_text(
            callback.message,
            text=(
                f"✅ <b>Ключ успешно перегенерирован!</b>\n\n"
                f"Ключ обновлён сразу на всех серверах, где было это устройство.\n\n"
                f"Получите новую ссылку для этого устройства ниже.\n\n"
                f"⚠️ Старая ссылка этого устройства больше не работает!"
            ),
            reply_markup=device_link_keyboard(device_id),
            parse_mode="HTML",
        )

        logger.info("VPN key regenerated for user %d device %d", user.id, device_id)

    except BackendAPIError as exc:
        logger.error("API error regenerating key for user %d device %d: %s", user.id, device_id, exc)
        await _safe_edit_text(
            callback.message,
            text=f"⚠️ Ошибка сервера: {exc.detail}",
            reply_markup=back_to_vpn_keyboard(),
        )
    except Exception as exc:
        logger.error("Unexpected error regenerating key for user %d device %d: %s", user.id, device_id, exc, exc_info=True)
        await _safe_edit_text(
            callback.message,
            text="⚠️ Произошла ошибка. Попробуйте позже.",
            reply_markup=back_to_vpn_keyboard(),
        )


# ── Инструкция ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "vpn:instructions")
async def callback_vpn_instructions(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await _safe_edit_text(
            callback.message,
            text="📖 <b>Инструкция по подключению</b>\n\nВыберите вашу платформу:",
            reply_markup=instructions_keyboard(),
            parse_mode="HTML",
        )
