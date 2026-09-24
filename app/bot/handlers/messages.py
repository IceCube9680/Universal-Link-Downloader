import asyncio
import os
import shutil
import uuid
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.ui.messages import get_task_process_card
from app.core.backup_channel import backup_channel_provider
from app.core.config import settings
from app.core.exceptions import DownloaderError, SSRFError, UserLimitExceededError
from app.core.logging import get_logger
from app.database.database import Database
from app.database.repository import UserRepository
from app.discovery.service import discovery_service
from app.queue.bulk_manager import bulk_manager
from app.queue.manager import job_queue
from app.upload.telegram import telegram_uploader
from app.utils.container import is_container_url, extract_links_from_container
from app.utils.filesize import format_filesize
from app.utils.mime import is_gif
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

        from app.bot.handlers.admin import is_pending_cookie_admin
        if is_pending_cookie_admin(user.id):
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

        # Cap max input URLs per message
        if len(raw_urls) > settings.MAX_URLS_PER_MESSAGE:
            raw_urls = raw_urls[:settings.MAX_URLS_PER_MESSAGE]

        allowed, err_text, markup, db_user = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        upload_mode = db_user.upload_mode or "DOCUMENT"

        # Check if input requires bulk/discovery pipeline:
        # Multiple URLs OR at least one webpage/container URL
        is_multi = len(raw_urls) > 1
        has_webpage = any(discovery_service.is_likely_webpage(u) for u in raw_urls)

        if settings.BULK_DISCOVERY_ENABLED and (is_multi or has_webpage):
            # Send initial scanning card
            scan_msg = await message.reply_text(
                "🔎 **Scanning page and links for downloadable files...**",
                disable_web_page_preview=True
            )

            try:
                discovery_result = await discovery_service.discover(raw_urls)

                if not discovery_result.supported_links:
                    errors = [l.metadata["error"] for l in discovery_result.unsupported_links if "error" in l.metadata]
                    if errors:
                        summary_text = (
                            f"⚠️ **Webpage Could Not Be Loaded**\n\n"
                            f"• **Target:** `{raw_urls[0]}`\n"
                            f"• **Status:** `{errors[0]}`\n\n"
                            f"The article or page was not found, was deleted, or could not be accessed. Please check that the link is active and valid."
                        )
                    else:
                        summary_text = (
                            f"⚠️ **No supported download links found.**\n\n"
                            f"Discovered `{discovery_result.total_discovered}` link(s), but none matched supported download services.\n"
                            f"Unsupported: `{discovery_result.total_unsupported}` | Duplicates skipped: `{discovery_result.duplicates_count}`"
                        )
                    await scan_msg.edit_text(summary_text, disable_web_page_preview=True)
                    return

                # If exactly 1 supported link was found from a single direct link, submit as standard job
                if len(discovery_result.supported_links) == 1 and len(raw_urls) == 1 and not has_webpage:
                    single_link = discovery_result.supported_links[0].url
                    init_text = get_task_process_card(
                        job_id="Q01",
                        stage="QUEUED",
                        upload_mode=upload_mode,
                        url=single_link
                    )
                    await scan_msg.edit_text(init_text, disable_web_page_preview=True)
                    await job_queue.submit_job(
                        user_id=user.id,
                        chat_id=message.chat.id,
                        message_id=scan_msg.id,
                        url=single_link,
                        upload_mode=upload_mode
                    )
                    return

                # Multiple supported links -> Launch Bulk Job Manager
                asyncio.create_task(
                    bulk_manager.execute_bulk_job(
                        client=client,
                        user_id=user.id,
                        chat_id=message.chat.id,
                        message_id=scan_msg.id,
                        discovery_result=discovery_result,
                        upload_mode=upload_mode
                    )
                )
                return

            except Exception as e:
                logger.error("Error during bulk discovery for user %d: %s", user.id, e, exc_info=True)
                await scan_msg.edit_text(f"❌ Failed to process links: `{str(e)[:150]}`")
                return

        # Direct single-URL pipeline
        target_url = raw_urls[0]
        try:
            if settings.SSRF_PROTECTION_ENABLED:
                await validate_url_security(target_url)

            init_text = get_task_process_card(
                job_id="Q01",
                stage="QUEUED",
                upload_mode=upload_mode,
                url=target_url
            )
            status_msg = await message.reply_text(init_text, disable_web_page_preview=True)

            await job_queue.submit_job(
                user_id=user.id,
                chat_id=message.chat.id,
                message_id=status_msg.id,
                url=target_url,
                upload_mode=upload_mode
            )

        except SSRFProtectionError as ssrf_err:
            logger.warning("SSRF blocked for user %d on URL %s: %s", user.id, target_url, ssrf_err)
            await message.reply_text(
                f"❌ **Security Violation:**\n`{target_url}`\nAccess to internal or restricted network addresses is blocked."
            )
        except UserLimitExceededError as limit_err:
            logger.info("User limit reached for %d: %s", user.id, limit_err)
            await message.reply_text(f"⚠️ **Queue Limit:** {limit_err.user_message}")
        except DownloaderError as de:
            logger.warning("Downloader error for user %d on URL %s: %s", user.id, target_url, de)
            await message.reply_text(f"⚠️ **Error:** {de.user_message}")
        except Exception as e:
            logger.error("Unexpected error submitting job for URL %s: %s", target_url, e, exc_info=True)
            await message.reply_text(f"❌ Failed to process link: `{str(e)[:150]}`")

    @app.on_message((filters.animation | filters.document | filters.video) & filters.private)
    async def direct_media_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return

        from app.bot.handlers.admin import is_pending_cookie_admin
        if is_pending_cookie_admin(user.id):
            return

        allowed, err_text, markup, db_user = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        # Determine file attributes
        file_name = "media.gif" if message.animation else None
        file_size = 0

        if message.animation:
            file_name = message.animation.file_name or "animation.gif"
            file_size = message.animation.file_size or 0
        elif message.document:
            file_name = message.document.file_name or "document"
            file_size = message.document.file_size or 0
        elif message.video:
            file_name = message.video.file_name or "video.mp4"
            file_size = message.video.file_size or 0

        job_id = f"M{uuid.uuid4().hex[:5].upper()}"
        status_msg = await message.reply_text(
            f"⚡ **Task `#{job_id}`**\n"
            f"📄 **File:** `{file_name}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⬇️ **Status:** `Downloading media from Telegram...`"
        )

        job_dir = os.path.join(settings.DOWNLOAD_DIR, f"media_{job_id}")
        os.makedirs(job_dir, exist_ok=True)
        local_path = os.path.join(job_dir, file_name)

        try:
            downloaded_path = await message.download(file_name=local_path)
            if not downloaded_path or not os.path.exists(downloaded_path):
                raise Exception("Failed to download media file from Telegram.")

            await status_msg.edit_text(
                f"⚡ **Task `#{job_id}`**\n"
                f"📄 **File:** `{file_name}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⬆️ **Status:** `Processing and uploading to Backup Channel...`"
            )

            backup_target = backup_channel_provider.get_backup_channel()
            if not backup_target:
                raise Exception("No Backup Channel configured. Please set /setbackup or configure backup channel.")

            caption = (
                f"📄 **{file_name}**\n"
                f"📦 **Size:** {format_filesize(file_size)}\n"
                f"👤 **User:** `{user.id}`\n"
                f"🆔 **Job:** `#{job_id}`\n\n"
            )

            await telegram_uploader.upload_file(
                client=client,
                chat_id=backup_target,
                file_path=downloaded_path,
                filename=file_name,
                caption=caption,
                upload_mode=db_user.upload_mode or "DOCUMENT"
            )

            await status_msg.edit_text(
                f"✅ **Task `#{job_id}` Completed!**\n"
                f"📄 **File:** `{file_name}`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🎉 _Uploaded successfully in MP4 format!_"
            )

        except Exception as e:
            logger.error("Error processing direct media message for user %d: %s", user.id, e, exc_info=True)
            await status_msg.edit_text(f"❌ **Error:** `{str(e)[:150]}`")
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
