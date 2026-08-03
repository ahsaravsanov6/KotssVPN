"""
app/api/routers/subscription.py — публичная выдача подписки.

GET /sub/{token}              — подписка на ВСЕ устройства пользователя
                                 сразу (сохранено для отладки/обратной
                                 совместимости).
GET /sub/{token}/{device_id}  — персональная подписка ОДНОГО устройства —
                                 именно эту ссылку бот выдаёт пользователю
                                 на кнопку "получить ключ" конкретного
                                 устройства (см. app/api/routers/internal.py).

Оба эндпоинта — без авторизации (сам токен и есть секрет, как и в
исходном 3X-UI subId). Никакой сетевой активности к панелям серверов на
этом пути — только чтение из БД платформы и локальная генерация
vless-ссылок.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.services.subscription_service import SubscriptionNotFound, SubscriptionService

router = APIRouter(tags=["subscription"])


def _response(body_base64: str, userinfo_header: str) -> Response:
    return Response(
        content=body_base64,
        media_type="text/plain; charset=utf-8",
        headers={
            "Subscription-Userinfo": userinfo_header,
            "Profile-Update-Interval": "12",
            "Content-Disposition": 'attachment; filename="subscription"',
        },
    )


@router.get("/sub/{token}")
def get_subscription(token: str, db: Session = Depends(get_db_session)) -> Response:
    service = SubscriptionService(db)
    try:
        user = service.get_by_token(token)
    except SubscriptionNotFound:
        raise HTTPException(status_code=404)

    payload = service.build_subscription(user)
    return _response(payload.body_base64, payload.userinfo_header)


@router.get("/sub/{token}/{device_id}")
def get_device_subscription(token: str, device_id: int, db: Session = Depends(get_db_session)) -> Response:
    """Подписка ОДНОГО устройства (охватывает все сервера, куда оно провижинено)."""
    service = SubscriptionService(db)
    try:
        user = service.get_by_token(token)
    except SubscriptionNotFound:
        raise HTTPException(status_code=404)

    try:
        payload = service.build_device_subscription(user, device_id)
    except SubscriptionNotFound:
        # Токен валиден, но устройство не найдено/не принадлежит этому
        # пользователю — 404 без деталей, как и для несуществующего токена.
        raise HTTPException(status_code=404)

    return _response(payload.body_base64, payload.userinfo_header)
