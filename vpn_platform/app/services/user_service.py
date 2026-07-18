"""
app/services/user_service.py

Перенос бизнес-правил из public_html/backend/main.py (/users/register,
/subscription/trial, реферальный бонус) в единый сервисный слой, не
завязанный на конкретный веб-фреймворк — им может пользоваться и
FastAPI-роутер, и Telegram-бот напрямую (если решите когда-то слить их
в один процесс), и миграционный скрипт.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.user import User
from app.db.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    def register(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        referrer_telegram_id: int | None = None,
    ) -> tuple[User, bool]:
        """Возвращает (user, is_new). Повторный вызов для существующего
        telegram_id — no-op, как и в исходном /users/register."""
        existing = self.users.get_by_telegram_id(telegram_id)
        if existing:
            return existing, False

        valid_referrer_id = None
        if referrer_telegram_id and referrer_telegram_id != telegram_id:
            referrer = self.users.get_by_telegram_id(referrer_telegram_id)
            if referrer:
                valid_referrer_id = referrer_telegram_id

        user = self.users.create(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            referrer_id=valid_referrer_id,
            tariff=settings.DEFAULT_TARIFF,
        )
        return user, True

    def activate_subscription(self, user: User, days: int) -> None:
        """Продлевает/активирует подписку. Провижининг серверов —
        отдельная ответственность (SubscriptionService), этот метод
        только двигает дату и флаг активности."""
        base = user.subscription_expires_at or datetime.utcnow()
        if base < datetime.utcnow():
            base = datetime.utcnow()
        user.subscription_expires_at = base + timedelta(days=days)
        user.is_active = True
        self.users.save(user)

    def start_trial(self, user: User, days: int | None = None) -> tuple[bool, str]:
        if user.trial_used:
            return False, "Пробный период уже был использован."
        if user.subscription_expires_at is not None:
            return False, "Пробный период доступен только новым пользователям без подписки."

        trial_days = max(1, days or settings.TRIAL_DAYS_DEFAULT)
        user.subscription_expires_at = datetime.utcnow() + timedelta(days=trial_days)
        user.is_active = True
        user.trial_used = True
        self.users.save(user)
        return True, f"Пробный период на {trial_days} дн. активирован."

    def is_first_payment(self, user: User, already_activated: bool) -> bool:
        """Вызывать ДО activate_subscription — иначе subscription_expires_at
        уже перезаписан и определить "первую ли оплату" нельзя (та же
        ловушка, что была прокомментирована в старом main.py)."""
        return not already_activated
