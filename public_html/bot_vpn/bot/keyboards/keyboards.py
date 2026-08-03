"""
bot/keyboards/keyboards.py — Клавиатуры (InlineKeyboard и ReplyKeyboard) для бота.
"""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import settings

# ── Ссылки на инструкции (telegra.ph) ──────────────────────────────────────
INSTRUCTION_URL_IPHONE_MACOS = "https://telegra.ph/IPhone-03-02-5"
INSTRUCTION_URL_WINDOWS = "https://telegra.ph/Podklyuchenie-VPN-na-Windows-01-12"
INSTRUCTION_URL_ANDROID = "https://telegra.ph/Podklyuchenie-VPN-na-Android-01-12"


# ── Главное меню ──────────────────────────────────────────────────────────────

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🔑 Мой VPN"),
        KeyboardButton(text="💳 Подписка"),
    )
    builder.row(
        KeyboardButton(text="⚙️ Ещё"),
    )
    return builder.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Выберите раздел...",
    )


# ── Раздел "Ещё" ────────────────────────────────────────────────────────────

def more_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👤 Личный кабинет", callback_data="menu:account"))
    builder.row(InlineKeyboardButton(text="👥 Пригласить друга", callback_data="menu:referral"))
    builder.row(
        InlineKeyboardButton(text="📢 Новостной канал", callback_data="menu:news"),
        InlineKeyboardButton(text="🆘 Поддержка", callback_data="menu:support"),
    )
    builder.row(InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu:about"))
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))
    return builder.as_markup()


def back_to_more_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:more"))
    return builder.as_markup()


# ── Раздел "Мой VPN" ─────────────────────────────────────────────────────────

def vpn_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔑 Мои ключи", callback_data="vpn:select_device"))
    builder.row(InlineKeyboardButton(text="📖 Инструкция", callback_data="vpn:instructions"))
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))
    return builder.as_markup()


def instructions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📱 iPhone", url=INSTRUCTION_URL_IPHONE_MACOS),
        InlineKeyboardButton(text="💻 macOS", url=INSTRUCTION_URL_IPHONE_MACOS),
    )
    builder.row(
        InlineKeyboardButton(text="🤖 Android", url=INSTRUCTION_URL_ANDROID),
        InlineKeyboardButton(text="🖥 Windows", url=INSTRUCTION_URL_WINDOWS),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад к VPN", callback_data="menu:vpn"))
    return builder.as_markup()


# ── Выбор устройства для ключа/перегенерации ──────────────────────────────────
#
# Модель не изменилась по сути: один UUID на устройство. Изменилось только
# то, что этот UUID теперь существует одновременно в нескольких панелях
# (по числу активных серверов) — для пользователя разницы нет, он всё так
# же выбирает конкретное устройство и получает именно его ссылку/ключ.

def device_select_keyboard(devices: list[dict], action: str) -> InlineKeyboardMarkup:
    """
    devices: список словарей с ключами 'id' и 'device_name'
    action:  "get_link" или "regenerate" — что делать после выбора
    """
    builder = InlineKeyboardBuilder()

    for device in devices:
        builder.row(
            InlineKeyboardButton(
                text=f"{device['device_name']}",
                callback_data=f"vpn:{action}:{device['id']}",
            )
        )

    builder.row(InlineKeyboardButton(text="➕ Добавить новое устройство", callback_data="account:devices"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:vpn"))
    return builder.as_markup()


def device_link_keyboard(device_id: int) -> InlineKeyboardMarkup:
    """Клавиатура экрана с ссылкой конкретного устройства."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="♻️ Перегенерировать этот ключ", callback_data=f"vpn:regenerate:{device_id}"))
    builder.row(InlineKeyboardButton(text="◀️ К списку устройств", callback_data="vpn:select_device"))
    return builder.as_markup()


def confirm_regenerate_keyboard(device_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, перегенерировать", callback_data=f"vpn:confirm_regenerate:{device_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"vpn:get_link:{device_id}"),
    )
    return builder.as_markup()


# ── Раздел "Подписка" ──────────────────────────────────────────────────────

def buy_subscription_keyboard(
    has_active_subscription: bool = False,
    trial_available: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if trial_available and not has_active_subscription:
        days = getattr(settings, "TRIAL_DAYS", 3)
        builder.row(
            InlineKeyboardButton(
                text=f"🎁 {days} {_ru_days_word(days)} бесплатно",
                callback_data="subscription:trial",
            )
        )

    if has_active_subscription:
        builder.row(InlineKeyboardButton(text="♻️ Продлить подписку", callback_data="subscription:offer"))
        builder.row(InlineKeyboardButton(text="🔑 Перейти в Мой VPN", callback_data="menu:vpn"))
    else:
        builder.row(InlineKeyboardButton(text="✅ Оплатить", callback_data="subscription:offer"))

    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))
    return builder.as_markup()


def _ru_days_word(n: int) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"


# ── Раздел "Личный кабинет" ───────────────────────────────────────────────────

def account_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📱 Мои устройства", callback_data="account:devices"))
    builder.row(InlineKeyboardButton(text="💳 Подписка", callback_data="menu:subscription"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:more"))
    return builder.as_markup()


# ── Раздел "Мои устройства" ───────────────────────────────────────────────────

def devices_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить устройство", callback_data="devices:add"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить устройство", callback_data="devices:remove_list"))
    builder.row(InlineKeyboardButton(text="◀️ Личный кабинет", callback_data="menu:account"))
    return builder.as_markup()


def buy_device_slot_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Докупить место", callback_data="device_slot:confirm"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="devices:back"))
    return builder.as_markup()


def device_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🍎 iOS", callback_data="devices:type:ios"),
        InlineKeyboardButton(text="🤖 Android", callback_data="devices:type:android"),
    )
    builder.row(
        InlineKeyboardButton(text="💻 Desktop", callback_data="devices:type:desktop"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="devices:back"))
    return builder.as_markup()


def devices_remove_keyboard(devices: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for device in devices:
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {device['device_name']}",
                callback_data=f"devices:delete:{device['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="devices:back"))
    return builder.as_markup()


def confirm_delete_device_keyboard(device_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"devices:confirm_delete:{device_id}",
        ),
        InlineKeyboardButton(text="❌ Отмена", callback_data="devices:back"),
    )
    return builder.as_markup()


# ── Навигационные кнопки ──────────────────────────────────────────────────────

def back_to_vpn_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад к VPN", callback_data="menu:vpn"))
    return builder.as_markup()


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))
    return builder.as_markup()


def back_to_account_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Личный кабинет", callback_data="menu:account"))
    return builder.as_markup()


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ── Реферальная система ────────────────────────────────────────────────────────

def referral_keyboard(bot_username: str, ref_link: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📤 Поделиться ссылкой",
            url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся%20к%20VPN%20боту!",
        )
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:more"))
    return builder.as_markup()


# ── Раздел "О нас" ─────────────────────────────────────────────────────────────

def about_keyboard(privacy_policy_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔒 Политика конфиденциальности",
            url=privacy_policy_url,
        )
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:more"))
    return builder.as_markup()


# ── Подтверждение оферты перед оплатой ─────────────────────────────────────────

def offer_confirmation_keyboard(offer_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📄 Читать оферту", url=offer_url)
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Согласен, перейти к оплате",
            callback_data="subscription:confirm",
        )
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main"))
    return builder.as_markup()


# ── После успешной оплаты ──────────────────────────────────────────────────────

def payment_success_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔑 Получить ключ", callback_data="vpn:select_device"))
    return builder.as_markup()
