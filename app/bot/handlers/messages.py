from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.config import settings
from app.core.exceptions import DownloaderError, SSRFError, UserLimitExceededError
from app.core.logging import get_logger
from app.database.database import Database
from app.database.repository import UserRepository
from app.queue.manager import job_queue
from app.utils.security import SSRFProtectionError, validate_url_security
from app.utils.url import extract_urls

logger = get_logger("message_handler")


async def check_user_access(
    client: Client,
    user_repo: UserRepository,
    user_id: int,
    username: str = None,
    first_name: str = None
):
    """
    Check if user is authorized to use the bot (banned check, private mode, force subscription).
    Returns (is_allowed, error_text, reply_markup, db_user).
    """
    db_user = await user_repo.get_or_create(user_id, username, first_name)
    is_admin = user_id in settings.ADMIN_IDS

    if db_user.is_banned:
        return False, "⛔ Your account has been restricted.", None, db_user

    # Private mode check
    if settings.PRIVATE_MODE and not is_admin and not db_user.is_whitelisted:
        return False, "🔒 **Private Mode Active**\n\nThis bot is restricted to authorized users. Please contact an administrator for access.", None, db_user

    # Force subscription check
    if settings.FORCE_SUB_CHANNEL and not is_admin:
        try:
            member = await client.get_chat_member(settings.FORCE_SUB_CHANNEL, user_id)
            if member.status in ["kicked", "left"]:
                raise UserNotParticipant()
        except Exception:
            channel_target = str(settings.FORCE_SUB_CHANNEL)
            channel_url = f"https://t.me/{channel_target.lstrip('@')}" if channel_target.startswith("@") else None
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join Required Channel", url=channel_url)]
            ]) if channel_url else None
            return False, "⚠️ **Channel Subscription Required**\n\nPlease join our updates channel before sending links.", kb, db_user

    return True, None, None, db_user


def register_message_handlers(app: Client, db: Database) -> None:
    user_repo = UserRepository(db)

    @app.on_message(filters.text & filters.private & ~filters.regex(r"^/"))
    async def url_message_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return

        text = message.text.strip()
        urls = extract_urls(text)

        if not urls:
            await message.reply_text(
                "❌ **No valid link detected.**\n\n"
                "Please send a valid `http://` or `https://` download URL.",
                disable_web_page_preview=True
            )
            return

        allowed, err_text, markup, db_user = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        # Process detected URLs (start with first URL)
        for url in urls[:1]:  # Process one URL safely per message initially
            try:
                # SSRF Pre-flight check
                if settings.SSRF_PROTECTION_ENABLED:
                    await validate_url_security(url)

                # Send initial status message
                status_msg = await message.reply_text(
                    "🔎 **Detecting link & queueing download...**\n\n"
                    f"🔗 `{url}`",
                    disable_web_page_preview=True
                )

                # Submit to queue
                await job_queue.submit_job(
                    user_id=user.id,
                    chat_id=message.chat.id,
                    message_id=status_msg.id,
                    url=url,
                    upload_mode=db_user.upload_mode or "DOCUMENT"
                )

            except SSRFProtectionError as ssrf_err:
                logger.warning("SSRF blocked for user %d on URL %s: %s", user.id, url, ssrf_err)
                await message.reply_text(
                    "❌ **Security Violation:** Access to internal, private, or local network addresses is strictly blocked."
                )
            except UserLimitExceededError as limit_err:
                logger.info("User limit exceeded for %d: %s", user.id, limit_err)
                await message.reply_text(f"⚠️ {limit_err.user_message}")
            except DownloaderError as de:
                logger.warning("Downloader error for user %d: %s", user.id, de)
                await message.reply_text(de.user_message)
            except Exception as e:
                logger.error("Unexpected error submitting job for URL %s: %s", url, e, exc_info=True)
                await message.reply_text(f"❌ Failed to process URL: {str(e)[:150]}")
