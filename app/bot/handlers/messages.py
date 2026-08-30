import asyncio
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.ui.messages import get_task_process_card
from app.core.config import settings
from app.core.exceptions import DownloaderError, SSRFError, UserLimitExceededError
from app.core.logging import get_logger
from app.database.database import Database
from app.database.repository import UserRepository
from app.queue.manager import job_queue
from app.utils.container import is_container_url, extract_links_from_container
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
        raw_urls = extract_urls(text)

        if not raw_urls:
            await message.reply_text(
                "❌ **No valid link detected.**\n\n"
                "Please send a valid `http://` or `https://` download URL or article link (e.g. Graph.org).",
                disable_web_page_preview=True
            )
            return

        allowed, err_text, markup, db_user = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        # 1. Expand container links (e.g. Graph.org, Telegraph, Pastebin)
        target_urls = []
        containers_expanded = []

        for raw_url in raw_urls:
            if is_container_url(raw_url):
                containers_expanded.append(raw_url)
                try:
                    extracted = await extract_links_from_container(raw_url)
                    if extracted:
                        for eu in extracted:
                            if eu not in target_urls:
                                target_urls.append(eu)
                    else:
                        if raw_url not in target_urls:
                            target_urls.append(raw_url)
                except Exception as ce:
                    logger.warning("Failed to extract links from container %s: %s", raw_url, ce)
                    if raw_url not in target_urls:
                        target_urls.append(raw_url)
            else:
                if raw_url not in target_urls:
                    target_urls.append(raw_url)

        if not target_urls:
            await message.reply_text(
                "⚠️ **No download links found.**\n\nCould not find any downloadable links in the provided message or article.",
                disable_web_page_preview=True
            )
            return

        # 2. Inform user about batch/container detection if multiple links
        if containers_expanded:
            await message.reply_text(
                f"📑 **Container Article Detected**\n\n"
                f"Extracted **{len(target_urls)}** download link(s) from article page.\n"
                f"🚀 _Queueing tasks..._",
                disable_web_page_preview=True
            )
        elif len(target_urls) > 1:
            await message.reply_text(
                f"📦 **Batch Processing: {len(target_urls)} Links Detected**\n\n"
                f"🚀 _Queueing all download tasks..._",
                disable_web_page_preview=True
            )

        # 3. Queue all target URLs
        upload_mode = db_user.upload_mode or "DOCUMENT"
        queued_count = 0

        for idx, url in enumerate(target_urls, 1):
            try:
                # SSRF Pre-flight check
                if settings.SSRF_PROTECTION_ENABLED:
                    await validate_url_security(url)

                # Send initial unified task status message
                temp_task_id = f"Q{idx:02d}"
                init_text = get_task_process_card(
                    job_id=temp_task_id,
                    stage="QUEUED",
                    upload_mode=upload_mode,
                    url=url
                )
                status_msg = await message.reply_text(
                    init_text,
                    disable_web_page_preview=True
                )

                # Submit to queue
                job_ctx = await job_queue.submit_job(
                    user_id=user.id,
                    chat_id=message.chat.id,
                    message_id=status_msg.id,
                    url=url,
                    upload_mode=upload_mode
                )
                queued_count += 1

                # Small delay to prevent Telegram flood rate limits on large batches
                if len(target_urls) > 1:
                    await asyncio.sleep(0.2)

            except SSRFProtectionError as ssrf_err:
                logger.warning("SSRF blocked for user %d on URL %s: %s", user.id, url, ssrf_err)
                await message.reply_text(
                    f"❌ **Security Violation on link #{idx}:**\n`{url}`\nAccess to internal or restricted network addresses is blocked."
                )
            except UserLimitExceededError as limit_err:
                logger.info("User limit reached for %d: %s", user.id, limit_err)
                await message.reply_text(
                    f"⚠️ **Queue Limit Reached:**\n{limit_err.user_message}\n\n"
                    f"✅ **{queued_count}** of **{len(target_urls)}** task(s) successfully queued."
                )
                break
            except DownloaderError as de:
                logger.warning("Downloader error for user %d on URL %s: %s", user.id, url, de)
                await message.reply_text(f"⚠️ **Link #{idx} Error:** {de.user_message}")
            except Exception as e:
                logger.error("Unexpected error submitting job for URL %s: %s", url, e, exc_info=True)
                await message.reply_text(f"❌ Failed to process link #{idx}: `{str(e)[:150]}`")
