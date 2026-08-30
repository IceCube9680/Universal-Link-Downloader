import asyncio
import os
import sys
from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, Message

from app.bot.filters.admin import admin_filter, is_admin_user
from app.bot.ui.keyboards import get_admin_dashboard_keyboard
from app.bot.ui.messages import get_stats_card
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.database.database import Database
from app.database.repository import JobRepository, StatsRepository, UserRepository
from app.download.filesystem import fs_manager
from app.queue.manager import job_queue
from app.queue.redis_queue import redis_manager
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
        workers = await redis_manager.get_active_workers() if redis_manager.is_connected else []
        worker_count = max(1, len(workers))
        text = metrics.format_dashboard(active_workers_count=worker_count)
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

    @app.on_message(filters.command("workers") & admin_filter)
    async def admin_workers_handler(client: Client, message: Message):
        if not redis_manager.is_connected:
            await message.reply_text("ℹ️ Bot is running in standalone mode (no distributed Redis cluster connected).")
            return

        workers = await redis_manager.get_active_workers()
        if not workers:
            await message.reply_text("ℹ️ No active worker nodes registered in Redis.")
            return

        lines = [f"🖥️ **Active Cluster Workers ({len(workers)} Online):**\n"]
        for w in workers:
            lines.append(
                f"• **Node:** `{w.get('worker_id')}`\n"
                f"  └ Host: `{w.get('hostname')}` | PID: `{w.get('pid')}`\n"
                f"  └ Active Jobs: `{w.get('active_jobs', 0)}`"
            )
        await message.reply_text("\n".join(lines), reply_markup=get_admin_dashboard_keyboard())

    @app.on_message(filters.command("user") & admin_filter)
    async def admin_user_info_handler(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.reply_text("❌ Usage: `/user <telegram_user_id>`")
            return
        target_id = int(parts[1].strip())
        target_user = await user_repo.get_by_telegram_id(target_id)
        if not target_user:
            await message.reply_text(f"❌ User `{target_id}` not found in database.")
            return

        daily_completed = await job_repo.get_user_daily_completed_count(target_id)
        user_jobs = await job_repo.get_user_jobs(target_id, limit=5)
        status = "⛔ Banned" if target_user.is_banned else "✅ Active"
        uname = f"@{target_user.username}" if target_user.username else "None"

        text = (
            f"👤 **User Profile:** `{target_user.telegram_id}`\n\n"
            f"• **Name:** {target_user.first_name or 'Unknown'}\n"
            f"• **Username:** {uname}\n"
            f"• **Status:** {status}\n"
            f"• **Upload Mode:** `{target_user.upload_mode}`\n"
            f"• **Today's Completed Downloads:** `{daily_completed}`\n"
            f"• **Joined:** `{target_user.created_at[:19] if target_user.created_at else 'Unknown'}`\n"
        )
        if user_jobs:
            text += "\n**Recent Jobs:**\n" + "\n".join([f"• `#{j.id}` | {j.service} | `{j.status}`" for j in user_jobs])

        await message.reply_text(text)

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

    @app.on_message(filters.command("auth") & admin_filter)
    async def admin_auth_handler(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.reply_text("❌ Usage: `/auth <telegram_user_id>`")
            return
        target_id = int(parts[1].strip())
        await user_repo.get_or_create(target_id)
        success = await user_repo.set_whitelist(target_id, is_whitelisted=True)
        if success:
            await message.reply_text(f"🔒 User `{target_id}` has been authorized (whitelisted)!")
        else:
            await message.reply_text(f"❌ Failed to authorize user `{target_id}`.")

    @app.on_message(filters.command("unauth") & admin_filter)
    async def admin_unauth_handler(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.reply_text("❌ Usage: `/unauth <telegram_user_id>`")
            return
        target_id = int(parts[1].strip())
        success = await user_repo.set_whitelist(target_id, is_whitelisted=False)
        if success:
            await message.reply_text(f"🔓 User `{target_id}` has been removed from authorized whitelist.")
        else:
            await message.reply_text(f"❌ User `{target_id}` not found in database.")

    @app.on_message(filters.command("whitelist") & admin_filter)
    async def admin_whitelist_handler(client: Client, message: Message):
        whitelisted = await user_repo.get_whitelisted_users()
        mode_status = "🔒 **Enabled (Restricted)**" if settings.PRIVATE_MODE else "🌐 **Disabled (Public)**"
        lines = [f"🛡️ **Private Mode:** {mode_status}\n\n**Authorized / Whitelisted Users ({len(whitelisted)}):**"]
        for u in whitelisted:
            uname = f"@{u.username}" if u.username else "No username"
            lines.append(f"• `{u.telegram_id}` - {u.first_name or 'Unknown'} ({uname})")
        if not whitelisted:
            lines.append("• No whitelisted users yet. Use `/auth <id>` to add.")
        await message.reply_text("\n".join(lines), reply_markup=get_admin_dashboard_keyboard())

    @app.on_message(filters.command(["private", "privatemode"]) & admin_filter)
    async def admin_private_mode_handler(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) > 1:
            arg = parts[1].lower()
            if arg in ["on", "enable", "true", "1"]:
                settings.PRIVATE_MODE = True
            elif arg in ["off", "disable", "false", "0"]:
                settings.PRIVATE_MODE = False
            else:
                await message.reply_text("❌ Usage: `/private on` | `/private off` | `/private` (toggle)")
                return
        else:
            settings.PRIVATE_MODE = not settings.PRIVATE_MODE

        mode_status = "🔒 **Enabled (Restricted to Admins & Whitelist)**" if settings.PRIVATE_MODE else "🌐 **Disabled (Public Access)**"
        await message.reply_text(
            f"🛡️ **Private Mode Updated**\n\nStatus: {mode_status}\n\n"
            f"• When Enabled: Only Admins and `/auth` whitelisted users can use the bot.\n"
            f"• When Disabled: Anyone can use the bot publicly.",
            reply_markup=get_admin_dashboard_keyboard()
        )

    @app.on_message(filters.command(["logs", "log"]) & admin_filter)
    async def admin_logs_handler(client: Client, message: Message):
        parts = message.text.split()
        log_file = os.path.join(settings.LOG_DIR, "bot.log")

        if len(parts) > 1 and parts[1].lower() == "clear":
            if os.path.exists(log_file):
                open(log_file, "w").close()
                await message.reply_text("🧹 `bot.log` has been cleared.")
            else:
                await message.reply_text("ℹ️ Log file does not exist.")
            return

        num_lines = 30
        if len(parts) > 1 and parts[1].isdigit():
            num_lines = min(200, max(5, int(parts[1])))

        if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
            await message.reply_text("ℹ️ Log file `bot.log` is currently empty or not found.")
            return

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()

            tail_lines = all_lines[-num_lines:]
            snippet = "".join(tail_lines).strip()
            if len(snippet) > 3500:
                snippet = snippet[-3500:]

            caption = f"📜 **Latest Bot Logs (Last {len(tail_lines)} lines):**\n\n```{snippet}```"
            await message.reply_text(caption, disable_web_page_preview=True)

            # Send complete log document if available
            if os.path.getsize(log_file) > 0:
                await client.send_document(
                    chat_id=message.chat.id,
                    document=log_file,
                    caption=f"📄 **Full System Logs** (`bot.log` - {format_filesize(os.path.getsize(log_file))})"
                )
        except Exception as e:
            logger.error("Failed to read or send logs: %s", e)
            await message.reply_text(f"❌ Error reading logs: {e}")

    @app.on_message(filters.command("backup") & admin_filter)
    async def admin_backup_handler(client: Client, message: Message):
        if not settings.BACKUP_CHANNEL_ID:
            await message.reply_text(
                "⚠️ **Backup Channel Not Configured**\n\n"
                "Set `BACKUP_CHANNEL_ID` in `.env` (e.g. `-1001234567890` or `@channel_name`) to automatically dump copies of all downloaded files.",
                reply_markup=get_admin_dashboard_keyboard()
            )
            return

        status_msg = await message.reply_text(
            f"📡 **Testing Backup Channel Access...**\n\nTarget: `{settings.BACKUP_CHANNEL_ID}`"
        )
        try:
            ping_msg = await client.send_message(
                chat_id=settings.BACKUP_CHANNEL_ID,
                text=f"🔔 **Backup Channel Health Check**\n\nBot is successfully connected and authorized to dump downloaded files!"
            )
            await status_msg.edit_text(
                f"✅ **Backup Channel Connected!**\n\n"
                f"• Channel ID: `{settings.BACKUP_CHANNEL_ID}`\n"
                f"• Test Message ID: `{ping_msg.id}`\n\n"
                f"All downloaded files will automatically be forwarded to this channel.",
                reply_markup=get_admin_dashboard_keyboard()
            )
        except Exception as e:
            logger.warning("Backup channel test failed for %s: %s", settings.BACKUP_CHANNEL_ID, e)
            await status_msg.edit_text(
                f"❌ **Backup Channel Connection Failed**\n\n"
                f"Target: `{settings.BACKUP_CHANNEL_ID}`\n"
                f"Error: `{str(e)}`\n\n"
                f"⚠️ Make sure the bot is an **Administrator** with 'Post Messages' permission in the channel.",
                reply_markup=get_admin_dashboard_keyboard()
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

        try:
            if tab == "overview" or tab == "refresh":
                stats = await stats_repo.get_stats()
                text = get_stats_card(stats)
                await callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_keyboard())
                await callback_query.answer("🔄 Refreshed!" if tab == "refresh" else None)

            elif tab == "metrics":
                workers = await redis_manager.get_active_workers() if redis_manager.is_connected else []
                worker_count = max(1, len(workers))
                text = metrics.format_dashboard(active_workers_count=worker_count)
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
                        status_icon = "✅" if j.status == "COMPLETED" else "⏳"
                        lines.append(f"{status_icon} `#{j.id}` | {j.service} | Status: `{j.status}` ({size_str})")
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

            elif tab == "workers":
                if not redis_manager.is_connected:
                    text = "🖥️ **Cluster Workers:**\n\n• Standalone Node (Local queue active)\n• Redis Cluster: `Not configured`"
                else:
                    workers = await redis_manager.get_active_workers()
                    if not workers:
                        text = "🖥️ **Cluster Workers:**\n\n• No external workers currently connected."
                    else:
                        lines = [f"🖥️ **Cluster Workers ({len(workers)} Active):**\n"]
                        for w in workers:
                            lines.append(f"• `{w.get('worker_id')}` ({w.get('hostname')}) - {w.get('active_jobs', 0)} active tasks")
                        text = "\n".join(lines)
                await callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_keyboard())
                await callback_query.answer()

            elif tab == "whitelist":
                whitelisted = await user_repo.get_whitelisted_users(limit=10)
                mode_status = "🔒 `Enabled (Restricted)`" if settings.PRIVATE_MODE else "🌐 `Disabled (Public)`"
                lines = [f"🛡️ **Private Mode:** {mode_status}\n\n**Whitelisted Users ({len(whitelisted)}):**"]
                for u in whitelisted:
                    uname = f"@{u.username}" if u.username else "No username"
                    lines.append(f"• `{u.telegram_id}` - {u.first_name or 'Unknown'} ({uname})")
                if not whitelisted:
                    lines.append("• No whitelisted users. Use `/auth <id>`.")
                await callback_query.edit_message_text(text="\n".join(lines), reply_markup=get_admin_dashboard_keyboard())
                await callback_query.answer()

            elif tab == "toggle_private":
                settings.PRIVATE_MODE = not settings.PRIVATE_MODE
                mode_status = "🔒 `Enabled (Restricted)`" if settings.PRIVATE_MODE else "🌐 `Disabled (Public)`"
                await callback_query.answer(f"Private Mode: {'Enabled' if settings.PRIVATE_MODE else 'Disabled'}!", show_alert=True)
                whitelisted = await user_repo.get_whitelisted_users(limit=10)
                lines = [f"🛡️ **Private Mode:** {mode_status}\n\n**Whitelisted Users ({len(whitelisted)}):**"]
                for u in whitelisted:
                    uname = f"@{u.username}" if u.username else "No username"
                    lines.append(f"• `{u.telegram_id}` - {u.first_name or 'Unknown'} ({uname})")
                if not whitelisted:
                    lines.append("• No whitelisted users. Use `/auth <id>`.")
                await callback_query.edit_message_text(text="\n".join(lines), reply_markup=get_admin_dashboard_keyboard())

            elif tab == "logs":
                log_file = os.path.join(settings.LOG_DIR, "bot.log")
                if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
                    text = "📜 **Bot Logs:**\n\n_Log file is currently empty._"
                else:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        lines_all = f.readlines()
                    tail = "".join(lines_all[-15:]).strip()
                    if len(tail) > 3000:
                        tail = tail[-3000:]
                    text = f"📜 **Latest Bot Logs (Last 15 lines):**\n\n```{tail}```\n\n💡 _Use `/logs` to download full log file._"
                await callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_keyboard())
                await callback_query.answer()

            elif tab == "backup":
                b_chan = settings.BACKUP_CHANNEL_ID or "Not Configured"
                status_icon = "✅ Active" if settings.BACKUP_CHANNEL_ID else "⚪ Disabled"
                text = (
                    f"📡 **Backup / Dump Channel Status:**\n\n"
                    f"• Status: `{status_icon}`\n"
                    f"• Target Channel: `{b_chan}`\n\n"
                    f"💡 _All downloaded media files are automatically copied/forwarded to this channel with indexing metadata tags._\n\n"
                    f"Use `/backup` to perform a live connection health check."
                )
                await callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_keyboard())
                await callback_query.answer()

            elif tab == "clearcache":
                purged = fs_manager.purge_orphaned_directories()
                await callback_query.answer(f"🧹 Removed {purged} temporary files!", show_alert=True)
                stats = await stats_repo.get_stats()
                await callback_query.edit_message_text(get_stats_card(stats), reply_markup=get_admin_dashboard_keyboard())

        except MessageNotModified:
            try:
                await callback_query.answer()
            except Exception:
                pass
