from pyrogram import filters
from pyrogram.types import Message, CallbackQuery
from typing import Union
from app.core.config import settings


def is_admin_user(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


async def admin_filter_func(*args, **kwargs) -> bool:
    update = None
    for arg in args:
        if isinstance(arg, (Message, CallbackQuery)) or hasattr(arg, "from_user"):
            update = arg
    if update is None:
        update = kwargs.get("update")
    if not update:
        return False
    user = getattr(update, "from_user", None)
    if not user:
        return False
    return is_admin_user(user.id)


admin_filter = filters.create(admin_filter_func)
