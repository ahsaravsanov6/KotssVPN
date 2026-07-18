from typing import Iterator

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import SessionLocal


def get_db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def verify_admin_key(x_api_key: str = Header(...)) -> str:
    """
    Используется и ботом (для /internal/* — регистрация, оплата), и
    админ-скриптами (/admin/servers). В проде стоит разделить на два
    разных ключа с разным объёмом прав — оставлено единым для простоты
    первой итерации, легко расширяется без изменения бизнес-логики.
    """
    if x_api_key != settings.API_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key
