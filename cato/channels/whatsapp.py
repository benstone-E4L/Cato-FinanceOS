"""
cato/channels/whatsapp.py — WhatsApp Cloud API integration.

Handles incoming and outgoing WhatsApp messages via Meta's Cloud API.
Supports webhook validation, message receipt, and state synchronization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# WhatsApp Cloud API base URL
WHATSAPP_API_BASE = "https://graph.instagram.com/v18.0"


class WhatsAppClient:
    """WhatsApp Cloud API client for message handling."""

    def __init__(self, phone_number_id: str, access_token: str, webhook_verify_token: str):
        """
        Initialize WhatsApp client.

        Args:
            phone_number_id: WhatsApp Business Account phone number ID
            access_token: WhatsApp Cloud API access token
            webhook_verify_token: Verification token for webhook validation
        """
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.webhook_verify_token = webhook_verify_token
        self._session: Optional[aiohttp.ClientSession] = None

    async def close(self) -> None:
        """Close aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    def validate_webhook(
        token: str,
        challenge: str,
        verify_token: str,
        signature: str,
        body: str,
    ) -> Optional[str]:
        """
        Validate incoming webhook request from WhatsApp.

        Args:
            token: Token from webhook subscription setup
            challenge: Challenge string from WhatsApp
            verify_token: Stored verification token
            signature: Signature header for body validation
            body: Raw request body

        Returns:
            Challenge string if valid, None otherwise.
        """
        # Verify token matches
        if token != verify_token:
            logger.warning("Webhook token mismatch")
            return None

        # Verify body signature (HMAC-SHA256) — only if signature provided
        if signature:
            try:
                expected_signature = "sha256=" + hmac.new(
                    verify_token.encode(),
                    body.encode() if isinstance(body, str) else body,
                    hashlib.sha256
                ).hexdigest()

                if not hmac.compare_digest(signature.replace("sha256=", ""), expected_signature.replace("sha256=", "")):
                    logger.warning("Webhook signature mismatch")
                    return None
            except Exception as e:
                logger.error(f"Webhook validation error: {e}")
                return None

        return challenge

    async def send_message(
        self,
        to_phone: str,
        message_text: str,
    ) -> dict:
        """
        Send a text message via WhatsApp Cloud API.

        Args:
            to_phone: Recipient phone number (with country code, no +)
            message_text: Message body

        Returns:
            API response dict with 'messages' containing message ID.
        """
        if not self._session:
            import socket as _socket
            _connector = aiohttp.TCPConnector(
                family=_socket.AF_INET,
                resolver=aiohttp.ThreadedResolver(),
            )
            self._session = aiohttp.ClientSession(connector=_connector)

        url = f"{WHATSAPP_API_BASE}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": message_text},
        }

        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                data = await resp.json()
                if resp.status in (200, 201):
                    logger.info(f"Message sent to {to_phone}")
                    return data
                else:
                    logger.error(f"Failed to send message: {resp.status} {data}")
                    return {"error": data}
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return {"error": str(e)}

    @staticmethod
    def parse_webhook_event(body: dict) -> dict:
        """
        Parse incoming webhook event from WhatsApp.

        Args:
            body: Parsed JSON body from webhook

        Returns:
            Dict with keys: message_id, from_phone, message_text, timestamp
            Returns empty dict if not a message event.
        """
        try:
            # WhatsApp webhook structure:
            # {
            #   "object": "whatsapp_business_account",
            #   "entry": [{
            #     "id": "...",
            #     "changes": [{
            #       "value": {
            #         "messages": [{
            #           "from": "1234567890",
            #           "id": "wamid...",
            #           "timestamp": "1234567890",
            #           "text": {"body": "Hello"}
            #         }]
            #       }
            #     }]
            #   }]
            # }

            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})

                    for message in value.get("messages", []):
                        from_phone = message.get("from", "")
                        message_id = message.get("id", "")
                        timestamp = message.get("timestamp", "")
                        text = message.get("text", {})
                        message_text = text.get("body", "")

                        if message_text:
                            return {
                                "message_id": message_id,
                                "from_phone": from_phone,
                                "message_text": message_text,
                                "timestamp": timestamp,
                            }

            return {}
        except Exception as e:
            logger.error(f"Error parsing webhook event: {e}")
            return {}
