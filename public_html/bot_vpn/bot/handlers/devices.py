"""
bot/handlers/devices.py — Обработчики раздела «Мои устройства».

Раздел теперь доступен из Личного кабинета, а не из главного меню.

Добавление устройства больше не требует текстового ввода названия —
пользователь выбирает тип устройства кнопками (iOS / Android / Desktop),
поэтому отдельный FSM-стейт здесь больше не нужен.
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.keyboards import (
    back_to_account_keyboard,
    buy_device_slot_keyboard,
    confirm_delete_device_keyboard,
    device_key_keyboard,
    device_type_keyboard,
    devices_menu_keyboard,
    devices_remove_keyboard,
    main_menu_keyboard,
)
from bot.services.api_client import BackendAPIError, api_client
from bot.services.subscription_guard import require_subscription
from config import settings

logger = logging.getLogger(__name__)

router = Router(name="devices")


# ── Типы устройств, доступные при добавлении ──────────────────────────────────
# Ключ совпадает с суффиксом callback_data "devices:type:<key>",
# значение — отображаемое название устройства, которое уходит в backend.

DEVICE_TYPES: dict[str, str] = {
    "ios": "🍎 iOS",          # изменён эмодзи
    "android": "🤖 Android",
    "desktop": "💻 Desktop",
}


async def _build_unique_device_name(telegram_id: int, base_name: str) -> str:
    """
    Возвращает имя устройства, уникальное среди уже добавленных пользователем.

    Если у пользователя ещё нет устройства с таким именем — возвращает
    base_name как есть. Если есть — добавляет порядковый номер
    ("🍎 iOS" → "🍎 iOS #2"), чтобы в списке устройств не было неотличимых
    друг от друга записей одного типа.
    """
    try:
        data = await api_client.get_devices(telegram_id=telegram_id)
        existing_names = {d.get("device_name", "") for d in data.get("devices", [])}
    except Exception as exc:
        # Если не удалось получить список — не блокируем добавление,
        # просто не нумеруем (backend всё равно создаст устройство с уникальным id).
        logger.warning("Could not fetch existing devices for naming, user %d: %s", telegram_id, exc)
        return base_name

    if base_name not in existing_names:
        return base_name

    index = 2
    while f"{base_name} #{index}" in existing_names:
        index += 1
    return f"{base_name} #{index}"


# ── Главное меню устройств (открывается из Личного кабинета) ──────────────────

@router.callback_query(F.data == "account:devices")
async def callback_devices_from_account(callback: CallbackQuery) -> None:
    """Открывает раздел устройств из личного кабинета."""
    if not await require_subscription(callback):
        return

    user = callback.from_user
    if not user:
        return

    await callback.answer()

    try:
        data = await api_client.get_devices(telegram_id=user.id)
        text = _build_devices_text(data)
    except BackendAPIError as exc:
        logger.error("API error getting devices for user %d: %s", user.id, exc)
        text = f"⚠️ Ошибка загрузки устройств.\n\n<code>{exc.detail}</code>"
    except Exception as exc:
        logger.error("Error in devices menu for user %d: %s", user.id, exc, exc_info=True)
        text = "⚠️ Произошла ошибка. Попробуйте позже."

    await callback.message.edit_text(
        text=text,
        reply_markup=devices_menu_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "devices:back")
async def callback_devices_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в меню устройств."""
    await state.clear()
    await callback.answer()

    user = callback.from_user
    if not user:
        return

    try:
        data = await api_client.get_devices(telegram_id=user.id)
        text = _build_devices_text(data)
    except Exception:
        text = "📱 <b>Мои устройства</b>\n\nВыберите действие:"

    await callback.message.edit_text(
        text=text,
        reply_markup=devices_menu_keyboard(),
        parse_mode="HTML",
    )


def _build_devices_text(data: dict) -> str:
    """Формирует текст списка устройств."""
    devices = data.get("devices", [])
    devices_count = data.get("devices_count", 0)
    max_devices = data.get("max_devices", 3)

    if devices:
        devices_list = "\n".join(
            f"  {i + 1}. {d['device_name']}"   # убран лишний "📱 " – имя уже содержит свой эмодзи
            + ("" if d.get("has_vpn_key", True) else " ⚠️ <i>ключ не создан</i>")
            for i, d in enumerate(devices)
        )
    else:
        devices_list = "  <i>Устройства не добавлены</i>"

    return (
        f"📱 <b>Мои устройства</b>\n\n"
        f"<b>Зарегистрировано:</b> {devices_count} / {max_devices}\n\n"
        f"{devices_list}\n\n"
        f"Выберите действие:"
    )


# ── Добавление устройства ─────────────────────────────────────────────────────

@router.callback_query(F.data == "devices:add")
async def callback_add_device_start(callback: CallbackQuery) -> None:
    """Показывает кнопки выбора типа устройства."""
    await callback.answer()

    if callback.message:
        await callback.message.edit_text(
            text=(
                "➕ <b>Добавление устройства</b>\n\n"
                "Выберите тип устройства, для которого нужен ключ:"
            ),
            reply_markup=device_type_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("devices:type:"))
async def callback_add_device_by_type(callback: CallbackQuery) -> None:
    """Добавляет устройство выбранного типа (iOS / Android / Desktop)."""
    user = callback.from_user
    if not user:
        return

    type_key = callback.data.split(":")[-1]
    base_name = DEVICE_TYPES.get(type_key)

    if not base_name:
        await callback.answer("❌ Неизвестный тип устройства", show_alert=True)
        return

    await callback.answer("➕ Добавляю устройство...")

    device_name = await _build_unique_device_name(user.id, base_name)

    try:
        data = await api_client.add_device(
            telegram_id=user.id,
            device_name=device_name,
        )

        if not data.get("success"):
            if data.get("limit_reached"):
                max_devices = data.get("max_devices", "—")
                if callback.message:
                    await callback.message.edit_text(
                        text=(
                            f"📵 <b>Достигнут лимит устройств</b>\n\n"
                            f"У вас уже {max_devices} из {max_devices} доступных устройств.\n\n"
                            f"Вы можете докупить дополнительное место за "
                            f"<b>{settings.EXTRA_DEVICE_PRICE:.0f} ₽</b> — оно добавляется "
                            f"навсегда, без ограничения по сроку.\n\n"
                            f"Либо удалите одно из текущих устройств в разделе "
                            f"«🗑 Удалить устройство», чтобы освободить место бесплатно."
                        ),
                        reply_markup=buy_device_slot_keyboard(),
                        parse_mode="HTML",
                    )
                return

            msg = data.get("message", "Неизвестная ошибка")
            if callback.message:
                await callback.message.edit_text(
                    text=f"❌ <b>Ошибка добавления</b>\n\n{msg}",
                    reply_markup=devices_menu_keyboard(),
                    parse_mode="HTML",
                )
            return

        config_text = data.get("config_text", "")
        qr_url = data.get("qr_code_url", "")
        device_id = data.get("device_id")

        if config_text:
            text = (
                f"✅ <b>Устройство добавлено!</b>\n\n"
                f"{device_name}\n\n"
                f"🔑 Вот ключ для этого устройства:\n\n"
                f"📋 <b>Ссылка на подписку:</b>\n"
                f"<a href=\"{config_text}\">{config_text}</a>\n\n"
                f"🔗 <a href=\"{qr_url}\">Открыть QR-код</a>\n\n"
                f"<i>Поддерживаемые приложения: Happ, v2rayNG, Hiddify, Streisand, Nekoray</i>\n\n"
                f"⚠️ <i>Этот ключ предназначен именно для «{device_name}». "
                f"Для другого устройства используйте его собственный ключ.</i>"
            )
            keyboard = device_key_keyboard(device_id) if device_id else devices_menu_keyboard()
        else:
            # Устройство создано, но конфиг почему-то не пришёл сразу —
            # пользователь всегда может получить его через "Мои ключи"
            text = (
                f"✅ <b>Устройство добавлено!</b>\n\n"
                f"{device_name}\n\n"
                f"Получить ключ для этого устройства можно в разделе 🔑 Мой VPN → Мои ключи."
            )
            keyboard = devices_menu_keyboard()

        if callback.message:
            await callback.message.edit_text(
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        logger.info("Device '%s' added for user %d", device_name, user.id)

    except BackendAPIError as exc:
        logger.error("API error adding device for user %d: %s", user.id, exc)
        if callback.message:
            await callback.message.edit_text(
                text=f"⚠️ Ошибка сервера: {exc.detail}",
                reply_markup=devices_menu_keyboard(),
                parse_mode="HTML",
            )
    except Exception as exc:
        logger.error("Unexpected error adding device for user %d: %s", user.id, exc, exc_info=True)
        if callback.message:
            await callback.message.edit_text(
                text="⚠️ Произошла ошибка. Попробуйте позже.",
                reply_markup=devices_menu_keyboard(),
            )


# ── Удаление устройства ───────────────────────────────────────────────────────

@router.callback_query(F.data == "devices:remove_list")
async def callback_remove_list(callback: CallbackQuery) -> None:
    """Показывает список устройств для удаления."""
    await callback.answer()

    user = callback.from_user
    if not user:
        return

    try:
        data = await api_client.get_devices(telegram_id=user.id)
        devices = data.get("devices", [])

        if not devices:
            await callback.message.edit_text(
                text="📭 <b>Нет устройств для удаления</b>\n\nСначала добавьте устройство.",
                reply_markup=devices_menu_keyboard(),
                parse_mode="HTML",
            )
            return

        await callback.message.edit_text(
            text=(
                "🗑 <b>Удаление устройства</b>\n\n"
                "Выберите устройство для удаления:"
            ),
            reply_markup=devices_remove_keyboard(devices),
            parse_mode="HTML",
        )

    except BackendAPIError as exc:
        logger.error("API error getting devices for removal, user %d: %s", user.id, exc)
        await callback.message.edit_text(
            text=f"⚠️ Ошибка загрузки устройств: {exc.detail}",
            reply_markup=devices_menu_keyboard(),
        )


@router.callback_query(F.data.startswith("devices:delete:"))
async def callback_delete_confirm(callback: CallbackQuery) -> None:
    """Запрашивает подтверждение удаления устройства."""
    await callback.answer()

    device_id = int(callback.data.split(":")[-1])

    if callback.message:
        await callback.message.edit_text(
            text=(
                "⚠️ <b>Подтверждение удаления</b>\n\n"
                "Вы уверены, что хотите удалить это устройство?\n\n"
                "VPN на этом устройстве перестанет работать, пока вы не добавите его заново."
            ),
            reply_markup=confirm_delete_device_keyboard(device_id),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("devices:confirm_delete:"))
async def callback_do_delete(callback: CallbackQuery) -> None:
    """Выполняет удаление устройства после подтверждения."""
    await callback.answer("🗑 Удаляю устройство...")

    user = callback.from_user
    if not user:
        return

    device_id = int(callback.data.split(":")[-1])

    try:
        data = await api_client.remove_device(
            telegram_id=user.id,
            device_id=device_id,
        )

        if not data.get("success"):
            await callback.message.edit_text(
                text=f"❌ Ошибка удаления: {data.get('message', 'Неизвестная ошибка')}",
                reply_markup=devices_menu_keyboard(),
                parse_mode="HTML",
            )
            return

        await callback.message.edit_text(
            text=(
                f"✅ <b>Устройство удалено</b>\n\n"
                f"{data.get('message', '')}"
            ),
            reply_markup=devices_menu_keyboard(),
            parse_mode="HTML",
        )

        logger.info("Device %d removed for user %d", device_id, user.id)

    except BackendAPIError as exc:
        logger.error("API error removing device %d for user %d: %s", device_id, user.id, exc)
        await callback.message.edit_text(
            text=f"⚠️ Ошибка сервера: {exc.detail}",
            reply_markup=devices_menu_keyboard(),
        )
    except Exception as exc:
        logger.error(
            "Unexpected error removing device %d for user %d: %s",
            device_id, user.id, exc, exc_info=True,
        )
        await callback.message.edit_text(
            text="⚠️ Произошла ошибка. Попробуйте позже.",
            reply_markup=devices_menu_keyboard(),
        )