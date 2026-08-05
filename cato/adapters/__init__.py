"""cato/adapters/__init__.py — Channel adapter registry."""

from .base import BaseAdapter
from .telegram import TelegramAdapter
from .whatsapp import WhatsAppAdapter

__all__ = ["TelegramAdapter", "WhatsAppAdapter", "BaseAdapter"]
