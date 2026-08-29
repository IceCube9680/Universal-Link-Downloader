from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from app.bot.ui.keyboards import (
    get_settings_keyboard,
    get_start_keyboard
)
from app.bot.ui.messages import (
    get_help_message,
    get_start_message
)
from app.database.database import Database
from app.database.repository import UserRepository
from app.queue.manager import job_queue
from app.utils.filesize import format_filesize


def register_callback_handlers(app: Client, db: Database) -> None:
    user_repo = UserRepository(db)

    @app.on_callback_query()
    async def callback_router(client: Client, callback_query: CallbackQuery):
        data = callback_query.data or ""
        user = callback_query.from_user
        if not user:
            await callback_query.answer()
            return

        # 1. Cancel download
        if data.startswith("dl_cancel:"):
            job_id = data.split(":", 1)[1]
            success = job_queue.cancel_job(job_id, user_id=user.id)
            if success:
                await callback_query.answer("🛑 Job cancelled!", show_alert=True)
                await callback_query.edit_message_text(f"🛑 **Job `#{job_id}` was cancelled.**")
            else:
                await callback_query.answer("❌ Job not found or already completed.", show_alert=True)

        # 2. Toggle Upload Mode
        elif data.startswith("set_mode:"):
            new_mode = data.split(":", 1)[1]
            await user_repo.update_upload_mode(user.id, new_mode)
            await callback_query.answer(f"✅ Upload mode set to {new_mode.title()}!")
            await callback_query.edit_message_reply_markup(
                reply_markup=get_settings_keyboard(new_mode)
            )

        # 3. View Settings
        elif data == "settings:view":
            db_user = await user_repo.get_or_create(user.id, user.username, user.first_name)
            current_mode = db_user.upload_mode or "DOCUMENT"
            text = (
                "⚙️ **Bot Settings**\n\n"
                "Choose your preferred upload format for media files:\n\n"
                "• **Document:** Send all files as Telegram documents (preserves raw quality).\n"
                "• **Media:** Automatically send videos and audio with streaming players and thumbnails."
            )
            await callback_query.edit_message_text(
                text,
                reply_markup=get_settings_keyboard(current_mode)
            )
            await callback_query.answer()

        # 4. View Help
        elif data == "help:view":
            await callback_query.edit_message_text(
                get_help_message(),
                reply_markup=get_start_keyboard(),
                disable_web_page_preview=True
            )
            await callback_query.answer()

        # 5. View Start
        elif data == "start:view":
            text = get_start_message(user.first_name or "User")
            await callback_query.edit_message_text(
                text,
                reply_markup=get_start_keyboard(),
                disable_web_page_preview=True
            )
            await callback_query.answer()

        # 6. View Status
        elif data == "status:view":
            active_jobs = job_queue.get_user_active_jobs(user.id)
            if not active_jobs:
                await callback_query.answer("ℹ️ No active downloads.", show_alert=True)
                return

            lines = ["📊 **Your Active Downloads:**\n"]
            for job in active_jobs:
                size_str = format_filesize(job.filesize) if job.filesize else "Calculating..."
                lines.append(
                    f"• **Job ID:** `{job.job_id}`\n"
                    f"  📄 `{job.filename or 'Resolving...'}` ({size_str})\n"
                    f"  ⚡ Status: `{job.status.value}`\n"
                )
            await callback_query.edit_message_text(
                "\n".join(lines),
                reply_markup=get_start_keyboard(),
                disable_web_page_preview=True
            )
            await callback_query.answer()

        else:
            await callback_query.answer()
