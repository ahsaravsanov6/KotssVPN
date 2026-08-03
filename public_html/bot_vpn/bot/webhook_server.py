"""
bot/webhook_server.py — Сервер для приёма вебхуков от платёжных систем.
"""

import base64
import hashlib
import json
import logging
from hmac import compare_digest

from aiohttp import web

from config import settings

logger = logging.getLogger(__name__)


def _get_cfg(name: str, default: str = "") -> str:
    return getattr(settings, name, default) or ""


def _heleket_verify(data: dict, sign: str, api_key: str) -> bool:
    sorted_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
    base64_encoded = base64.b64encode(sorted_str.encode()).decode()
    raw = f"{base64_encoded}{api_key}"
    expected = hashlib.md5(raw.encode()).hexdigest()
    return compare_digest(expected, sign)


def create_webhook_app(bot, payment_processor) -> web.Application:
    app = web.Application()

    async def yookassa_webhook(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            logger.info("YooKassa webhook received: event=%s", body.get("event"))

            if body.get("event") == "payment.succeeded":
                obj = body.get("object", {})
                meta = obj.get("metadata", {})

                if meta.get("telegram_id"):
                    meta["payment_method"] = "YooKassa"
                    await payment_processor(bot, meta)

            return web.Response(text="OK")

        except Exception as exc:
            logger.error("YooKassa webhook error: %s", exc, exc_info=True)
            return web.Response(text="Error", status=500)

    async def cryptobot_webhook(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            logger.info("CryptoBot webhook: update_type=%s", body.get("update_type"))

            if body.get("update_type") == "invoice_paid":
                payload_str = body.get("payload", {}).get("payload", "")
                if not payload_str:
                    return web.Response(text="OK")

                parts = payload_str.split(":")
                if len(parts) < 3:
                    logger.error("CryptoBot webhook: bad payload format: %s", payload_str)
                    return web.Response(text="Error", status=400)

                meta = {
                    "telegram_id": parts[0],
                    "days": parts[1],
                    "price": parts[2],
                    "kind": parts[3] if len(parts) > 3 else "subscription",
                    "payment_method": "CryptoBot",
                }
                await payment_processor(bot, meta)

            return web.Response(text="OK")

        except Exception as exc:
            logger.error("CryptoBot webhook error: %s", exc, exc_info=True)
            return web.Response(text="Error", status=500)

    async def heleket_webhook(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            logger.info("Heleket webhook: status=%s", body.get("status"))

            api_key = _get_cfg("HELEKET_API_KEY")
            if not api_key:
                logger.error("Heleket webhook: HELEKET_API_KEY not set")
                return web.Response(text="Error", status=500)

            sign = body.pop("sign", None)
            if not sign:
                return web.Response(text="Forbidden", status=403)

            if not _heleket_verify(body, sign, api_key):
                logger.warning("Heleket webhook: invalid signature")
                return web.Response(text="Forbidden", status=403)

            if body.get("status") in ("paid", "paid_over"):
                meta_str = body.get("description", "")
                if not meta_str:
                    return web.Response(text="Error", status=400)

                meta = json.loads(meta_str)
                meta["payment_method"] = "Heleket"
                await payment_processor(bot, meta)

            return web.Response(text="OK")

        except Exception as exc:
            logger.error("Heleket webhook error: %s", exc, exc_info=True)
            return web.Response(text="Error", status=500)

    app.router.add_post("/yookassa-webhook", yookassa_webhook)
    app.router.add_post("/cryptobot-webhook", cryptobot_webhook)
    app.router.add_post("/heleket-webhook", heleket_webhook)

    return app


async def start_webhook_server(bot) -> None:
    from bot.handlers.payment import process_successful_payment

    host = _get_cfg("WEBHOOK_HOST", "0.0.0.0")
    port = int(getattr(settings, "WEBHOOK_PORT", 8080))

    app = create_webhook_app(bot, process_successful_payment)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info("Webhook server started on %s:%d", host, port)
    logger.info("  POST /yookassa-webhook")
    logger.info("  POST /cryptobot-webhook")
    logger.info("  POST /heleket-webhook")

