"""
app/api/routers/subscription.py — публичная выдача подписки.

GET /sub/{token} — намеренно без авторизации (сам токен и есть секрет,
как и в исходном 3X-UI subId). Никакой сетевой активности к панелям
серверов на этом пути — только чтение из БД платформы и локальная
генерация vless-ссылок, поэтому эндпоинт быстрый и устойчив к
недоступности отдельных серверов/панелей.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.services.subscription_service import SubscriptionNotFound, SubscriptionService

router = APIRouter(tags=["subscription"])


@router.get("/sub/{token}")
def get_subscription(token: str, db: Session = Depends(get_db_session)) -> Response:
    service = SubscriptionService(db)
    try:
        user = service.get_by_token(token)
    except SubscriptionNotFound:
        # 404 без деталей — не подтверждаем/опровергаем существование токена
        raise HTTPException(status_code=404)

    payload = service.build_subscription(user)

    return Response(
        content=payload.body_base64,
        media_type="text/plain; charset=utf-8",
        headers={
            "Subscription-Userinfo": payload.userinfo_header,
            "Profile-Update-Interval": "12",
            "Content-Disposition": 'attachment; filename="subscription"',
        },
    )
