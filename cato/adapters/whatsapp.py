"""
cato/adapters/whatsapp.py — WhatsApp channel adapter via Twilio WhatsApp API.

Runs a lightweight aiohttp webhook server on 127.0.0.1:8080.
Twilio sends a POST to /whatsapp/webhook for every inbound message.

Setup:
  1. Create a Twilio account and enable the WhatsApp sandbox (or a
     dedicated WhatsApp Business number).
  2. Point the Twilio webhook URL to:
       https://<your-host>/whatsapp/webhook
     For local development use ngrok or Tailscale to expose port 8080.
  3. Store the following credentials in the Vault:
       twilio_account_sid      — Account SID from Twilio console
       twilio_auth_token       — Auth token from Twilio console
       twilio_whatsapp_number  — Your Twilio WhatsApp sender, e.g.
                                 "whatsapp:+14155238886"

Outbound messages are sent via the Twilio Messages REST API.
The adapter splits messages longer than 1500 characters so they
fit within WhatsApp's delivery limits.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import urllib.parse
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web

from .base import BaseAdapter

if TYPE_CHECKING:
    from ..config import CatoConfig
    from ..gateway import Gateway
    from ..vault import Vault

logger = logging.getLogger(__name__)

_WHATSAPP_MAX_LEN = 1500   # Twilio/WhatsApp practical message limit
_WEBHOOK_HOST     = "127.0.0.1"
_WEBHOOK_PORT     = 8080   # separate from WebSocket server on 8081


class WhatsAppAdapter(BaseAdapter):
    """WhatsApp adapter via Twilio WhatsApp API (webhook-based).

    Architecture:
      - aiohttp web server listens for Twilio POST webhooks.
      - Incoming messages are validated (HMAC-SHA1) and forwarded to
        ``gateway.ingest()``.
      - Outbound replies are sent via the Twilio Messages REST API using
        aiohttp's async HTTP client.
    """

    channel_name = "whatsapp"

    def __init__(self, gateway: "Gateway", vault: "Vault", config: "CatoConfig") -> None:
        super().__init__(gateway, vault, config)
        self._app:         web.Application | None = None
        self._runner:      web.AppRunner | None   = None
        self._account_sid: str | None = None
        self._auth_token:  str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Pull credentials from vault, start the aiohttp webhook server."""
        self._account_sid = self.vault.get("TWILIO_ACCOUNT_SID")
        self._auth_token  = self.vault.get("TWILIO_AUTH_TOKEN")

        if not self._account_sid:
            raise ValueError(
                "TWILIO_ACCOUNT_SID not found in vault. Run: cato init"
            )
        if not self._auth_token:
            raise ValueError(
                "TWILIO_AUTH_TOKEN not found in vault. Run: cato init"
            )

        self._app = web.Application()
        self._app.router.add_post("/whatsapp/webhook", self._handle_webhook)
        self._app.router.add_get("/whatsapp/health",   self._health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, _WEBHOOK_HOST, _WEBHOOK_PORT)
        await site.start()

        self.running = True
        logger.info(
            "WhatsAppAdapter started — webhook http://%s:%d/whatsapp/webhook",
            _WEBHOOK_HOST, _WEBHOOK_PORT,
        )

    async def stop(self) -> None:
        """Shut down the aiohttp webhook server."""
        self.running = False
        if self._runner:
            try:
                await self._runner.cleanup()
            except Exception as exc:
                logger.warning("WhatsAppAdapter stop error: %s", exc)
        logger.info("WhatsAppAdapter stopped")

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, session_id: str, text: str) -> None:
        """Send a WhatsApp message to the user via Twilio REST API.

        The user's phone number is extracted from the session_id
        (last colon-delimited segment).  Long messages are split into
        chunks of at most 1500 characters so each chunk is accepted by
        Twilio's WhatsApp gateway.
        """
        from_number = self.vault.get("TWILIO_WHATSAPP_NUMBER")
        if not from_number:
            logger.error("TWILIO_WHATSAPP_NUMBER not in vault — cannot send")
            return

        user_id = session_id.split(":")[-1]
        if user_id == "main":
            logger.debug("send() skipped for pooled session %s", session_id)
            return

        auth_header = "Basic " + base64.b64encode(
            f"{self._account_sid}:{self._auth_token}".encode()
        ).decode()

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{self._account_sid}/Messages.json"
        )

        chunks = [text[i : i + _WHATSAPP_MAX_LEN] for i in range(0, len(text), _WHATSAPP_MAX_LEN)]

        import socket as _socket
        _connector = aiohttp.TCPConnector(
            family=_socket.AF_INET,
            resolver=aiohttp.ThreadedResolver(),
        )
        async with aiohttp.ClientSession(connector=_connector) as session:
            for chunk in chunks:
                try:
                    resp = await session.post(
                        url,
                        data={
                            "From": from_number,
                            "To":   f"whatsapp:{user_id}",
                            "Body": chunk,
                        },
                        headers={"Authorization": auth_header},
                    )
                    if resp.status >= 400:
                        body = await resp.text()
                        logger.error(
                            "Twilio send error %d: %s", resp.status, body[:200]
                        )
                except Exception as exc:
                    logger.error("WhatsApp send error (user=%s): %s", user_id, exc)

    # ------------------------------------------------------------------
    # Inbound webhook handlers
    # ------------------------------------------------------------------

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle an inbound Twilio WhatsApp webhook POST.

        Twilio sends ``application/x-www-form-urlencoded`` data with at
        minimum a ``From`` and ``Body`` field.  The response must be
        valid TwiML — an empty ``<Response/>`` signals that Cato will
        reply asynchronously via the REST API rather than in the webhook
        response body.
        """
        try:
            data = await request.post()
        except Exception as exc:
            logger.warning("WhatsApp webhook: failed to parse POST body: %s", exc)
            return _twiml_ok()

        from_number = data.get("From", "").strip()   # e.g. "whatsapp:+15551234567"
        body        = data.get("Body", "").strip()

        if not from_number or not body:
            logger.debug("WhatsApp webhook: empty From or Body — ignoring")
            return _twiml_ok()

        # Optional: validate Twilio signature in production environments
        if not self._validate_signature(request, dict(data)):
            logger.warning("WhatsApp webhook: invalid Twilio signature — request rejected")
            return web.Response(status=403, text="Forbidden")

        # Strip the "whatsapp:" prefix to get the raw E.164 phone number
        user_id    = from_number.replace("whatsapp:", "")
        session_id = self.make_session_id("whatsapp", user_id)

        # Fire-and-forget: respond to Twilio immediately (within the 15 s window),
        # then process the message asynchronously.
        asyncio.create_task(self.gateway.ingest(session_id, body, "whatsapp"))

        return _twiml_ok()

    async def _health(self, request: web.Request) -> web.Response:
        """Simple liveness probe used by monitoring and ngrok health checks."""
        return web.json_response({"status": "ok", "adapter": "whatsapp"})

    # ------------------------------------------------------------------
    # Signature validation (security)
    # ------------------------------------------------------------------

    def _validate_signature(self, request: web.Request, data: dict) -> bool:
        """Validate the X-Twilio-Signature header using HMAC-SHA1.

        Algorithm (per Twilio docs):
          1. Take the full webhook URL.
          2. Sort POST parameters alphabetically and append key+value pairs.
          3. Compute HMAC-SHA1 over that string with the Auth Token as key.
          4. Base64-encode the result and compare to the header value.

        Returns True when the signature matches or when no Auth Token is
        available (allows unsigned requests only in test environments;
        disable this branch for production deployments).

        Reference: https://www.twilio.com/docs/usage/webhooks/webhooks-security
        """
        if not self._auth_token:
            return True   # No token — allow (test/dev only)

        signature = request.headers.get("X-Twilio-Signature", "")
        if not signature:
            # No signature header present — reject all unsigned requests.
            return False

        url = str(request.url)

        # Build the validation string: URL + sorted key-value pairs
        sorted_params = "".join(
            f"{k}{v}" for k, v in sorted(data.items())
        )
        validation_string = url + sorted_params

        expected = base64.b64encode(
            hmac.new(
                self._auth_token.encode("utf-8"),
                validation_string.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode()

        return hmac.compare_digest(expected, signature)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _twiml_ok() -> web.Response:
    """Return an empty TwiML response that satisfies Twilio's webhook contract."""
    return web.Response(
        text="<?xml version='1.0' encoding='UTF-8'?><Response></Response>",
        content_type="text/xml",
    )
