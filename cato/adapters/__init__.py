"""cato/adapters/__init__.py — Channel adapter registry."""

from .base import BaseAdapter
from .telegram import TelegramAdapter

__all__ = ["TelegramAdapter", "BaseAdapter"]
