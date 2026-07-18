"""
app/db/repositories/user_repository.py

Репозитории намеренно "тупые": никакой бизнес-логики (проверка лимитов,
начисление бонусов и т.д.) — это Services. Здесь только CRUD-запросы,
чтобы сервисы не были завязаны на конкретный ORM/диалект SQL.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        return self.db.get(User, user_id)

    def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        return self.db.scalar(select(User).where(User.telegram_id == telegram_id))

    def get_by_sub_token(self, sub_token: str) -> Optional[User]:
        return self.db.scalar(select(User).where(User.sub_token == sub_token))

    def create(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        referrer_id: int | None,
        tariff: str,
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            referrer_id=referrer_id,
            tariff=tariff,
        )
        self.db.add(user)
        self.db.flush()  # чтобы получить user.id/uuid/sub_token до коммита вызывающим кодом
        return user

    def list_active(self) -> list[User]:
        return list(self.db.scalars(select(User).where(User.is_active.is_(True))))

    def save(self, user: User) -> None:
        self.db.add(user)
        self.db.flush()
