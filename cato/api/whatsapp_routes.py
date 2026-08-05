"""
cato/api/whatsapp_routes.py — WhatsApp webhook and message API endpoints.

Handles incoming webhooks from WhatsApp and provides message send endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiohttp import web

logger = logging.getLogger(__name__)

# Global WhatsApp client (initialized on first request)
_whatsapp_client = None

# Deduplication: track message IDs seen in the last hour to prevent duplicates
_seen_messages: dict[str, datetime] = {}


def _get_whatsapp_client():
    """Lazy-load WhatsApp client on first use."""
    global _whatsapp_client
    if _whatsapp_client is None:
        try:
            from cato.config import CatoConfig
            from cato.channels.whatsapp import WhatsAppClient
            from cato.vault import Vault

            config = CatoConfig.load()
            vault = Vault.open()

            phone_number_id = vault.get("WHATSAPP_PHONE_ID", "")
            access_token = vault.get("WHATSAPP_TOKEN", "")
            webhook_verify_token = vault.get("WHATSAPP_WEBHOOK_VERIFY", "")

            if phone_number_id and access_token and webhook_verify_token:
                _whatsapp_client = WhatsAppClient(
                    phone_number_id=phone_number_id,
                    access_token=access_token,
                    webhook_verify_token=webhook_verify_token,
                )
                logger.info("Initialized WhatsApp client")
            else:
                logger.warning("WhatsApp credentials not configured in vault")
                _whatsapp_client = None
        except Exception as e:
            logger.error(f"Failed to initialize WhatsApp client: {e}")
            _whatsapp_client = None

    return _whatsapp_client


async def whatsapp_webhook(request: web.Request) -> web.Response:
    """
    GET /api/whatsapp/webhook — Webhook verification endpoint.
    POST /api/whatsapp/webhook — Receive incoming messages.
    """
    if request.method == "GET":
        # Webhook verification (GET during subscription setup)
        try:
            token = request.query.get("hub.verify_token", "")
            challenge = request.query.get("hub.challenge", "")

            client = _get_whatsapp_client()
            if not client:
                return web.Response(status=403, text="WhatsApp not configured")

            from cato.channels.whatsapp import WhatsAppClient
            result = WhatsAppClient.validate_webhook(
                token=token,
                challenge=challenge,
                verify_token=client.webhook_verify_token,
                signature="",
                body="",
            )

            if result:
                return web.Response(status=200, text=result)
            else:
                return web.Response(status=403, text="Invalid token")
        except Exception as e:
            logger.error(f"Webhook verification error: {e}")
            return web.Response(status=500, text=str(e))

    else:  # POST
        # Incoming message webhook
        try:
            body = await request.json()

            client = _get_whatsapp_client()
            if not client:
                return web.json_response({"success": False, "error": "WhatsApp not configured"}, status=503)

            from cato.channels.whatsapp import WhatsAppClient
            event = WhatsAppClient.parse_webhook_event(body)

            if not event:
                # Not a message event, just return 200
                return web.json_response({"success": True, "processed": False})

            message_id = event.get("message_id", "")
            from_phone = event.get("from_phone", "")
            message_text = event.get("message_text", "")

            # Deduplication: check if we've seen this message ID recently
            global _seen_messages
            now = datetime.now()
            if message_id in _seen_messages:
                age = (now - _seen_messages[message_id]).total_seconds()
                if age < 3600:  # Within last hour
                    logger.debug(f"Duplicate message skipped: {message_id}")
                    return web.json_response({"success": True, "duplicate": True})

            # Record message
            _seen_messages[message_id] = now

            # Clean up old entries (older than 1 hour)
            cutoff = now - timedelta(hours=1)
            _seen_messages = {
                mid: dt for mid, dt in _seen_messages.items()
                if dt > cutoff
            }

            # Route message to agent loop
            # TODO: Integrate with agent_loop for message processing
            logger.info(f"WhatsApp message from {from_phone}: {message_text}")

            return web.json_response({
                "success": True,
                "processed": True,
                "message_id": message_id,
                "from": from_phone,
            })

        except Exception as e:
            logger.exception(f"Error processing WhatsApp webhook: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)


async def send_whatsapp_message(request: web.Request) -> web.Response:
    """POST /api/whatsapp/send — Send a message via WhatsApp."""
    try:
        body = await request.json()
        to_phone = body.get("to_phone", "").strip()
        message_text = body.get("message_text", "").strip()

        if not to_phone or not message_text:
            return web.json_response({
                "success": False,
                "error": "to_phone and message_text are required"
            }, status=400)

        client = _get_whatsapp_client()
        if not client:
            return web.json_response({
                "success": False,
                "error": "WhatsApp not configured"
            }, status=503)

        result = await client.send_message(to_phone, message_text)

        if "error" in result:
            return web.json_response({
                "success": False,
                "error": result.get("error")
            }, status=400)

        return web.json_response({
            "success": True,
            "message_id": result.get("messages", [{}])[0].get("id"),
        })

    except Exception as e:
        logger.exception(f"Error sending WhatsApp message: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


async def whatsapp_config(request: web.Request) -> web.Response:
    """GET /api/whatsapp/config — Get WhatsApp configuration status."""
    try:
        client = _get_whatsapp_client()
        if not client:
            return web.json_response({
                "success": True,
                "configured": False,
            })

        return web.json_response({
            "success": True,
            "configured": True,
            "phone_number_id": client.phone_number_id,
        })
    except Exception as e:
        logger.exception(f"Error getting WhatsApp config: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)


def register_routes(app: web.Application) -> None:
    """Register WhatsApp routes with the aiohttp Application."""
    app.router.add_get("/api/whatsapp/webhook", whatsapp_webhook)
    app.router.add_post("/api/whatsapp/webhook", whatsapp_webhook)
    app.router.add_post("/api/whatsapp/send", send_whatsapp_message)
    app.router.add_get("/api/whatsapp/config", whatsapp_config)
    logger.info("WhatsApp routes registered")
