"""Handlers package."""
from app.bot.handlers.commands import register_command_handlers
from app.bot.handlers.admin import register_admin_handlers
from app.bot.handlers.messages import register_message_handlers

__all__ = [
    "register_command_handlers",
    "register_admin_handlers",
    "register_message_handlers",
]
