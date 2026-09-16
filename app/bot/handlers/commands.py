from pyrogram import Client, filters
from pyrogram.types import Message

from app.bot.ui.keyboards import (
    get_cancel_keyboard,
    get_settings_keyboard,
    get_start_keyboard
)
from app.bot.ui.messages import get_help_message, get_start_message
from app.bot.handlers.messages import check_user_access
from app.database.database import Database
from app.database.repository import UserRepository
from app.queue.manager import job_queue
from app.utils.filesize import format_filesize


def register_command_handlers(app: Client, db: Database) -> None:
    user_repo = UserRepository(db)

    @app.on_message(filters.command("start") & filters.private)
    async def start_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return
        allowed, err_text, markup, db_user = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        text = get_start_message(user.first_name or "User")
        await message.reply_text(
            text,
            reply_markup=get_start_keyboard(),
            disable_web_page_preview=True
        )

    @app.on_message(filters.command("help") & filters.private)
    async def help_handler(client: Client, message: Message):
        user = message.from_user
        if user:
            allowed, err_text, markup, _ = await check_user_access(
                client, user_repo, user.id, user.username, user.first_name
            )
            if not allowed:
                await message.reply_text(err_text, reply_markup=markup)
                return

        await message.reply_text(
            get_help_message(),
            disable_web_page_preview=True
        )

    @app.on_message(filters.command("settings") & filters.private)
    async def settings_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return
        allowed, err_text, markup, db_user = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        current_mode = db_user.upload_mode or "DOCUMENT"
        text = (
            "⚙️ **Bot Settings**\n\n"
            "Choose your preferred upload format for media files:\n\n"
            "• **Document:** Send all files as Telegram documents (preserves raw quality).\n"
            "• **Media:** Automatically send videos and audio with streaming players and thumbnails."
        )
        await message.reply_text(
            text,
            reply_markup=get_settings_keyboard(current_mode)
        )

    @app.on_message(filters.command("status") & filters.private)
    async def status_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return
        allowed, err_text, markup, _ = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        active_jobs = job_queue.get_user_active_jobs(user.id)
        if not active_jobs:
            await message.reply_text("ℹ️ You currently have no active or queued downloads.")
            return

        lines = ["📊 **Your Active Downloads:**\n"]
        for job in active_jobs:
            size_str = format_filesize(job.filesize) if job.filesize else "Calculating..."
            lines.append(
                f"• **Job ID:** `{job.job_id}`\n"
                f"  📄 **File:** `{job.filename or 'Resolving...'}`\n"
                f"  📦 **Size:** `{size_str}`\n"
                f"  ⚡ **Status:** `{job.status.value}`\n"
                f"  🛑 Cancel: `/cancel {job.job_id}`\n"
            )
        await message.reply_text("\n".join(lines), disable_web_page_preview=True)

    @app.on_message(filters.command("cancel") & filters.private)
    async def cancel_handler(client: Client, message: Message):
        user = message.from_user
        if not user:
            return
        allowed, err_text, markup, _ = await check_user_access(
            client, user_repo, user.id, user.username, user.first_name
        )
        if not allowed:
            await message.reply_text(err_text, reply_markup=markup)
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            target_job_id = parts[1].strip()
            if target_job_id.upper().startswith("BULK-") or target_job_id.lower().startswith("bulk_"):
                from app.queue.bulk_manager import bulk_manager
                success = await bulk_manager.cancel_bulk_job(target_job_id, user_id=user.id)
                if success:
                    await message.reply_text(f"🛑 Successfully cancelled Bulk Job `#{target_job_id}`.")
                else:
                    await message.reply_text(f"❌ Bulk Job `#{target_job_id}` not found or not active.")
                return

            success = job_queue.cancel_job(target_job_id, user_id=user.id)
            if success:
                await message.reply_text(f"🛑 Successfully cancelled Job `#{target_job_id}`.")
            else:
                await message.reply_text(f"❌ Job `#{target_job_id}` not found or not active.")
            return

        active_jobs = job_queue.get_user_active_jobs(user.id)
        if not active_jobs:
            await message.reply_text("ℹ️ You have no active jobs to cancel.")
            return

        # Cancel the most recent active job
        latest_job = active_jobs[-1]
        job_queue.cancel_job(latest_job.job_id, user_id=user.id)
        await message.reply_text(f"🛑 Cancelled latest Job `#{latest_job.job_id}`.")
