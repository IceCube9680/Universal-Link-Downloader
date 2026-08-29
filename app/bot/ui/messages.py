from app.core.config import settings
from app.database.models import BotStats
from app.utils.filesize import format_filesize


def get_start_message(first_name: str) -> str:
    return (
        f"👋 **Hello {first_name}!**\n\n"
        "Welcome to the **Universal Link Downloader Bot** 🚀\n\n"
        "Send me any direct or supported link, and I will fetch the file and upload it directly to Telegram for you.\n\n"
        "⚡ **Features:**\n"
        "• High-speed streaming downloads\n"
        "• Support for direct HTTP/HTTPS files\n"
        "• Video streaming & thumbnail generation\n"
        "• Document & Archive uploads\n"
        "• Secure SSRF protected network engine\n\n"
        "💡 _Just paste your URL below to start downloading!_"
    )


def get_help_message() -> str:
    max_size_str = format_filesize(settings.max_download_bytes)
    return (
        "📖 **How to Use the Bot**\n\n"
        "1. **Send a Link:** Simply paste any valid download URL into this chat.\n"
        "2. **Auto Detection:** The bot resolves the link, verifies security, and checks file size.\n"
        "3. **Progress Bar:** Watch live download and upload status.\n"
        "4. **Delivery:** The completed file will be sent back directly to your chat.\n\n"
        "📋 **Available Commands:**\n"
        "• `/start` - Start the bot & welcome menu\n"
        "• `/help` - View this help guide\n"
        "• `/settings` - Configure upload mode (Document vs Media)\n"
        "• `/status` - View your active and queued downloads\n"
        "• `/cancel [id]` - Cancel a running download\n\n"
        f"📏 **Maximum File Size:** `{max_size_str}`\n"
        f"⚡ **Concurrent Jobs Per User:** `{settings.MAX_ACTIVE_JOBS_PER_USER}`\n"
    )


def get_detected_link_card(service_name: str, filename: str, filesize_bytes: int | None, url: str) -> str:
    size_str = format_filesize(filesize_bytes) if filesize_bytes else "Calculating..."
    return (
        "🔎 **Link Detected**\n\n"
        f"🌐 **Service:** `{service_name}`\n"
        f"📄 **File:** `{filename}`\n"
        f"📦 **Size:** `{size_str}`\n\n"
        "⏳ _Queuing job..._"
    )


def get_stats_card(stats: BotStats) -> str:
    down_str = format_filesize(stats.total_downloaded_bytes)
    up_str = format_filesize(stats.total_uploaded_bytes)
    return (
        "📊 **Universal Bot Statistics**\n\n"
        f"👥 **Total Users:** `{stats.total_users}`\n"
        f"📥 **Total Jobs Created:** `{stats.total_jobs}`\n"
        f"✅ **Completed Jobs:** `{stats.completed_jobs}`\n"
        f"❌ **Failed Jobs:** `{stats.failed_jobs}`\n"
        f"🛑 **Cancelled Jobs:** `{stats.cancelled_jobs}`\n"
        f"⚡ **Active Running Jobs:** `{stats.active_jobs}`\n"
        f"⏳ **Jobs In Queue:** `{stats.queued_jobs}`\n\n"
        f"⬇️ **Total Downloaded:** `{down_str}`\n"
        f"⬆️ **Total Uploaded:** `{up_str}`"
    )
