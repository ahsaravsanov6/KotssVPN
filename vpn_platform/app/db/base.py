"""
app/db/base.py — engine и session factory для БД платформы.

Один engine на процесс, создаётся лениво. Схема — Postgres в проде,
SQLite допустим для дев-окружения (DATABASE_URL из .env решает).
"""

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Общий базовый класс для всех ORM-моделей платформы."""


_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: одна сессия на запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Iterator[Session]:
    """Обычный контекст-менеджер для использования вне FastAPI (боты, скрипты)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all_tables() -> None:
    """
    Используется только в dev/тестах. В проде — только через Alembic
    (alembic upgrade head), см. alembic/.

    ВАЖНО: Base.metadata заполняется только когда модули с моделями
    реально импортированы python-интерпретатором. Импорт здесь, внутри
    функции, — не косметика: без него при вызове create_all_tables() до
    того, как что-то ещё импортировало app.db.models, метод отработает
    без единой ошибки и не создаст ни одной таблицы (SQLAlchemy просто
    сгенерирует пустой список DDL) — молчаливый и коварный баг, если
    полагаться на порядок импортов вызывающего кода.
    """
    import app.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
