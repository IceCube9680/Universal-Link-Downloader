from pyrogram import filters
from pyrogram.types import Message, CallbackQuery
from typing import Union
from app.core.config import settings


def is_admin_user(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


async def admin_filter_func(_, __, update: Union[Message, CallbackQuery]) -> bool:
    user = update.from_user
    if not user:
        return False
    return is_admin_user(user.id)


admin_filter = filters.create(admin_filter_func)
