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
    """Клавиатура главного меню."""
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


# ── Раздел "Ещё" (свёрнутые редкие функции) ───────────────────────────────────

def more_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура раздела 'Ещё'.
    Содержит редко используемые разделы, вынесенные с главного меню:
    личный кабинет (профиль + устройства), рефералку, новости, поддержку, о нас.
    """
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
    """Кнопка возврата в раздел 'Ещё' — используется в новостях/поддержке/о нас/рефералке."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:more"))
    return builder.as_markup()


# ── Раздел "Мой VPN" ─────────────────────────────────────────────────────────

def vpn_menu_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура раздела 'Мой VPN'."""
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="🔑 Мои ключи", callback_data="vpn:select_device"))
    builder.row(InlineKeyboardButton(text="📖 Инструкция", callback_data="vpn:instructions"))
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))

    return builder.as_markup()


# ── Инструкция (кнопки-ссылки на telegra.ph) ───────────────────────────────

def instructions_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора платформы для инструкции."""
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


# ── Выбор устройства для получения/перегенерации ключа ───────────────────────
#
# Ключ теперь привязан к конкретному устройству (per-device VLESS-клиент
# в 3X-UI), поэтому "Получить ключ" больше не отдаёт конфиг напрямую —
# сначала нужно выбрать устройство. Это сделано намеренно структурно
# (а не текстовым предупреждением), чтобы пользователь физически не мог
# по привычке получить "просто какой-то" ключ без понимания, для какого
# устройства он предназначен.

def device_select_keyboard(devices: list[dict], action: str) -> InlineKeyboardMarkup:
    """
    Клавиатура выбора устройства.

    Args:
        devices: список словарей с ключами 'id' и 'device_name'
        action:  "get_config" или "regenerate" — что делать после выбора
    """
    builder = InlineKeyboardBuilder()

    for device in devices:
        builder.row(
            InlineKeyboardButton(
                text=f"{device['device_name']}",   # убран лишний "📱 " – имя уже содержит свой эмодзи
                callback_data=f"vpn:{action}:{device['id']}",
            )
        )

    builder.row(InlineKeyboardButton(text="➕ Добавить новое устройство", callback_data="account:devices"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:vpn"))

    return builder.as_markup()


# ── Раздел "Подписка" (единый экран статуса + покупки) ────────────────────────
#
# subscription.py теперь отвечает за ВСЁ, что касается подписки:
# показ статуса (активна/истекла/нет) и переход к оплате/продлению.
# Раньше статус дублировался в account.py — теперь там его нет.

def buy_subscription_keyboard(
    has_active_subscription: bool = False,
    trial_available: bool = False,
) -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура раздела 'Подписка'.

    Args:
        has_active_subscription: если True — пользователь уже имеет активную
            подписку, кнопка ведёт на продление, плюс быстрый переход к VPN.
            Если False — обычная покупка (как раньше).
        trial_available: если True (и подписки активной нет) — сверху
            показывается отдельная кнопка пробного периода. Управляется
            настройками TRIAL_ENABLED в .env бота и тем, использовал ли
            уже пользователь триал (backend сам это проверяет).
    """
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
    """Правильное склонение слова 'день' для русского языка (1 день, 2 дня, 5 дней)."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"


# ── Раздел "Личный кабинет" ───────────────────────────────────────────────────
# Личный кабинет теперь отвечает только за профиль и устройства.
# Статус подписки переехал в единый экран 💳 Подписка (subscription.py),
# чтобы не дублировать одни и те же данные в двух разных местах.

def account_menu_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура личного кабинета."""
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="📱 Мои устройства", callback_data="account:devices"))
    builder.row(InlineKeyboardButton(text="💳 Подписка", callback_data="menu:subscription"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:more"))

    return builder.as_markup()


# ── Раздел "Мои устройства" ───────────────────────────────────────────────────

def devices_menu_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура раздела 'Мои устройства'."""
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="➕ Добавить устройство", callback_data="devices:add"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить устройство", callback_data="devices:remove_list"))
    builder.row(InlineKeyboardButton(text="◀️ Личный кабинет", callback_data="menu:account"))

    return builder.as_markup()


def buy_device_slot_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура экрана "достигнут лимит устройств, хотите докупить место?".
    Кнопка оплаты ведёт в payment.py через тот же выбор способа оплаты,
    что и подписка, но с callback_data, помечающим это как покупку
    доп. устройства (device_slot:confirm), а не подписки.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Докупить место", callback_data="device_slot:confirm"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="devices:back"))
    return builder.as_markup()


def device_type_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура выбора типа устройства при добавлении.
    Вместо свободного текстового ввода пользователь выбирает один из
    трёх готовых вариантов — это и проще для пользователя, и исключает
    мусорные/случайные названия устройств.
    """
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(text="🍎 iOS", callback_data="devices:type:ios"),   # изменён эмодзи
        InlineKeyboardButton(text="🤖 Android", callback_data="devices:type:android"),
    )
    builder.row(
        InlineKeyboardButton(text="💻 Desktop", callback_data="devices:type:desktop"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="devices:back"))

    return builder.as_markup()


def devices_remove_keyboard(devices: list[dict]) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура со списком устройств для удаления."""
    builder = InlineKeyboardBuilder()

    for device in devices:
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {device['device_name']}",   # убран лишний "📱 " – имя уже содержит свой эмодзи
                callback_data=f"devices:delete:{device['id']}",
            )
        )

    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="devices:back"))

    return builder.as_markup()


def confirm_delete_device_keyboard(device_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления устройства."""
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
    """Кнопка возврата в меню VPN."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад к VPN", callback_data="menu:vpn"))
    return builder.as_markup()


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))
    return builder.as_markup()


def back_to_account_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в личный кабинет."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Личный кабинет", callback_data="menu:account"))
    return builder.as_markup()


def confirm_regenerate_keyboard(device_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения перегенерации ключа конкретного устройства."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, перегенерировать", callback_data=f"vpn:confirm_regenerate:{device_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"vpn:get_config:{device_id}"),
    )
    return builder.as_markup()


def device_key_keyboard(device_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура экрана с конфигом конкретного устройства.
    Перегенерация и возврат к списку устройств привязаны именно к device_id,
    чтобы пользователь не потерял контекст, для какого устройства он сейчас
    смотрит ключ.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="♻️ Перегенерировать этот ключ", callback_data=f"vpn:regenerate:{device_id}"))
    builder.row(InlineKeyboardButton(text="◀️ К списку устройств", callback_data="vpn:select_device"))
    return builder.as_markup()


def remove_keyboard() -> ReplyKeyboardRemove:
    """Удаляет Reply-клавиатуру."""
    return ReplyKeyboardRemove()


# ── Реферальная система ────────────────────────────────────────────────────────

def referral_keyboard(bot_username: str, ref_link: str) -> InlineKeyboardMarkup:
    """Клавиатура раздела 'Пригласить друга'."""
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
    """Клавиатура раздела 'О нас' со ссылкой на политику конфиденциальности."""
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
    """
    Клавиатура с подтверждением ознакомления с публичной офертой.
    Показывается перед переходом к выбору способа оплаты.
    """
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
    """
    Клавиатура сообщения об успешной оплате (отправляется из вебхука).
    Ведёт на выбор устройства, а не сразу на конфиг — теперь ключ привязан
    к конкретному устройству, поэтому без выбора (или автовыбора, если
    устройство уже одно, или предложения добавить, если их нет) ключ
    показать нельзя. См. vpn.py callback_select_device.
    """
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔑 Получить ключ", callback_data="vpn:select_device"))
    return builder.as_markup()