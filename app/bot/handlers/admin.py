import asyncio
import os
import sys
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from app.bot.filters.admin import admin_filter
from app.bot.ui.keyboards import get_admin_dashboard_keyboard
from app.bot.ui.messages import get_stats_card
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.database.database import Database
from app.database.repository import JobRepository, StatsRepository, UserRepository
from app.download.filesystem import fs_manager
from app.utils.filesize import format_filesize

logger = get_logger("admin_handlers")


def register_admin_handlers(app: Client, db: Database) -> None:
    stats_repo = StatsRepository(db)
    user_repo = UserRepository(db)
    job_repo = JobRepository(db)

    @app.on_message(filters.command(["admin", "stats"]) & admin_filter)
    async def admin_dashboard_handler(client: Client, message: Message):
        stats = await stats_repo.get_stats()
        text = get_stats_card(stats)
        await message.reply_text(
            text,
            reply_markup=get_admin_dashboard_keyboard()
        )

    @app.on_message(filters.command("metrics") & admin_filter)
    async def admin_metrics_handler(client: Client, message: Message):
        text = metrics.format_dashboard()
        await message.reply_text(
            text,
            reply_markup=get_admin_dashboard_keyboard()
        )

    @app.on_message(filters.command("jobs") & admin_filter)
    async def admin_jobs_handler(client: Client, message: Message):
        recent_jobs = await job_repo.get_recent_jobs(limit=15)
        if not recent_jobs:
            await message.reply_text("ℹ️ No recent jobs found.", reply_markup=get_admin_dashboard_keyboard())
            return

        lines = ["📋 **Recent Jobs (Last 15):**\n"]
        for j in recent_jobs:
            size_str = format_filesize(j.filesize) if j.filesize else "Unknown"
            status_icon = {
                "COMPLETED": "✅",
                "FAILED": "❌",
                "CANCELLED": "🛑",
                "DOWNLOADING": "⬇️",
                "UPLOADING": "⬆️",
                "QUEUED": "⏳"
            }.get(j.status, "⚙️")

            lines.append(
                f"{status_icon} `#{j.id}` | User: `{j.user_id}`\n"
                f"   📄 `{j.filename or 'Unnamed'}` ({size_str})\n"
                f"   🌐 {j.service} | Status: `{j.status}`\n"
            )
        await message.reply_text("\n".join(lines), reply_markup=get_admin_dashboard_keyboard(), disable_web_page_preview=True)

    @app.on_message(filters.command("users") & admin_filter)
    async def admin_users_handler(client: Client, message: Message):
        total_users = await user_repo.count_users()
        recent_users = await user_repo.get_all_users(limit=10)

        lines = [f"👥 **Total Registered Users:** `{total_users}`\n\n**Recent Users:**"]
        for u in recent_users:
            uname = f"@{u.username}" if u.username else "No username"
            status = "⛔ Banned" if u.is_banned else "✅ Active"
            lines.append(f"• `{u.telegram_id}` - {u.first_name or 'Unknown'} ({uname}) [{status}]")

        await message.reply_text("\n".join(lines), reply_markup=get_admin_dashboard_keyboard())

    @app.on_message(filters.command("ban") & admin_filter)
    async def admin_ban_handler(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.reply_text("❌ Usage: `/ban <telegram_user_id>`")
            return
        target_id = int(parts[1].strip())
        success = await user_repo.ban_user(target_id, is_banned=True)
        if success:
            await message.reply_text(f"⛔ User `{target_id}` has been banned.")
        else:
            await message.reply_text(f"❌ User `{target_id}` not found in database.")

    @app.on_message(filters.command("unban") & admin_filter)
    async def admin_unban_handler(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.reply_text("❌ Usage: `/unban <telegram_user_id>`")
            return
        target_id = int(parts[1].strip())
        success = await user_repo.ban_user(target_id, is_banned=False)
        if success:
            await message.reply_text(f"✅ User `{target_id}` has been unbanned.")
        else:
            await message.reply_text(f"❌ User `{target_id}` not found in database.")

    @app.on_message(filters.command("broadcast") & admin_filter)
    async def admin_broadcast_handler(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.reply_text("❌ Usage: `/broadcast <your message>`")
            return

        broadcast_text = parts[1].strip()
        status_msg = await message.reply_text("📢 Starting broadcast...")

        users = await user_repo.get_all_users(limit=5000)
        success_count = 0
        fail_count = 0

        for user in users:
            try:
                await client.send_message(user.telegram_id, broadcast_text)
                success_count += 1
                await asyncio.sleep(0.05)  # Throttle to prevent FloodWait
            except Exception:
                fail_count += 1

        await status_msg.edit_text(
            f"📢 **Broadcast Complete!**\n\n"
            f"✅ Sent: `{success_count}`\n"
            f"❌ Failed: `{fail_count}`"
        )

    @app.on_message(filters.command("clearcache") & admin_filter)
    async def admin_clearcache_handler(client: Client, message: Message):
        purged = fs_manager.purge_orphaned_directories()
        await message.reply_text(f"🧹 Cache cleared! Removed `{purged}` orphaned temporary items.")

    @app.on_message(filters.command("restart") & admin_filter)
    async def admin_restart_handler(client: Client, message: Message):
        await message.reply_text("🔄 Restarting bot process...")
        logger.info("Admin triggered restart. Exiting process with code 0...")
        sys.exit(0)

    # Callback Query Router for Admin Dashboard Tabs
    @app.on_callback_query(filters.regex(r"^admin_tab:"))
    async def admin_tab_callback_handler(client: Client, callback_query: CallbackQuery):
        user = callback_query.from_user
        if not user or not is_admin_user(user.id):
            await callback_query.answer("⛔ Unauthorized.", show_alert=True)
            return

        tab = callback_query.data.split(":", 1)[1]

        if tab == "metrics":
            text = metrics.format_dashboard()
            await callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_keyboard())
            await callback_query.answer()

        elif tab == "jobs":
            recent_jobs = await job_repo.get_recent_jobs(limit=10)
            if not recent_jobs:
                text = "ℹ️ No recent jobs found."
            else:
                lines = ["📋 **Recent Jobs:**\n"]
                for j in recent_jobs:
                    size_str = format_filesize(j.filesize) if j.filesize else "Unknown"
                    lines.append(f"• `#{j.id}` | {j.service} | Status: `{j.status}` ({size_str})")
                text = "\n".join(lines)
            await callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_keyboard())
            await callback_query.answer()

        elif tab == "users":
            total_users = await user_repo.count_users()
            recent_users = await user_repo.get_all_users(limit=8)
            lines = [f"👥 **Total Registered Users:** `{total_users}`\n\n**Recent Users:**"]
            for u in recent_users:
                uname = f"@{u.username}" if u.username else "No username"
                lines.append(f"• `{u.telegram_id}` - {u.first_name or 'Unknown'} ({uname})")
            await callback_query.edit_message_text("\n".join(lines), reply_markup=get_admin_dashboard_keyboard())
            await callback_query.answer()

        elif tab == "clearcache":
            purged = fs_manager.purge_orphaned_directories()
            await callback_query.answer(f"🧹 Removed {purged} temporary files!", show_alert=True)

        elif tab == "refresh":
            stats = await stats_repo.get_stats()
            text = get_stats_card(stats)
            await callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_keyboard())
            await callback_query.answer("🔄 Refreshed!")
