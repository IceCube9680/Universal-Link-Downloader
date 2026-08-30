from typing import Optional
from app.core.config import settings
from app.database.models import BotStats
from app.download.progress import render_progress_bar
from app.utils.filesize import format_eta, format_filesize, format_speed


def get_task_process_card(
    job_id: str,
    stage: str,
    service_name: Optional[str] = None,
    upload_mode: str = "DOCUMENT",
    filename: Optional[str] = None,
    filesize_bytes: Optional[int] = None,
    url: Optional[str] = None,
    progress_pct: float = 0.0,
    transferred_bytes: int = 0,
    total_bytes: Optional[int] = None,
    speed: float = 0.0,
    eta: Optional[float] = None,
    duration: Optional[float] = None,
    error: Optional[str] = None,
    priority: int = 5
) -> str:
    """
    Generate unified multi-step task process card showing all stages in one view:
    Resolving ➔ Downloading ➔ Uploading ➔ Completed.
    """
    svc_display = service_name or "Detecting..."
    mode_display = upload_mode.upper() if upload_mode else "DOCUMENT"
    stage_upper = stage.upper()

    lines = [
        f"⚡ **Task `#{job_id}`**",
        f"🌐 **Source:** `{svc_display}` | 📦 **Mode:** `{mode_display}`"
    ]

    effective_size = filesize_bytes or total_bytes
    if filename:
        lines.append(f"📄 **File:** `{filename}`")
    if effective_size and effective_size > 0:
        lines.append(f"📊 **Size:** `{format_filesize(effective_size)}`")
    elif url and not filename:
        short_url = url if len(url) <= 55 else f"{url[:52]}..."
        lines.append(f"🔗 **Link:** `{short_url}`")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if stage_upper == "QUEUED":
        lines.extend([
            f"⏳ **Status:** `In Download Queue (Priority: {priority})...`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "⏳ [1/3] 🔎 Link Resolution",
            "⏳ [2/3] ⬇️ Download from Source",
            "⏳ [3/3] ⬆️ Upload to Telegram",
            f"\n🛑 `/cancel {job_id}`"
        ])

    elif stage_upper == "RESOLVING":
        lines.extend([
            "🔄 **Status:** `Resolving & Inspecting link...`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🔄 [1/3] 🔎 Link Resolution",
            "⏳ [2/3] ⬇️ Download from Source",
            "⏳ [3/3] ⬆️ Upload to Telegram",
            f"\n🛑 `/cancel {job_id}`"
        ])

    elif stage_upper == "DOWNLOADING":
        bar = render_progress_bar(progress_pct)
        cur_str = format_filesize(transferred_bytes)
        tot_str = format_filesize(total_bytes or effective_size, default="Calculating...")
        spd_str = format_speed(speed)
        eta_str = format_eta(eta)
        lines.extend([
            "⬇️ **Status:** `Downloading from source...`",
            f"`{bar}`",
            f"⚡ **Speed:** `{spd_str}` | ⏱️ **ETA:** `{eta_str}`",
            f"📦 **Progress:** `{cur_str} / {tot_str}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "✅ [1/3] 🔎 Link Resolved",
            "🔄 [2/3] ⬇️ Downloading",
            "⏳ [3/3] ⬆️ Upload to Telegram",
            f"\n🛑 `/cancel {job_id}`"
        ])

    elif stage_upper == "DOWNLOADED":
        lines.extend([
            "📦 **Status:** `Download finished. Initializing Telegram upload...`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "✅ [1/3] 🔎 Link Resolved",
            "✅ [2/3] ⬇️ Download Complete",
            "🔄 [3/3] ⬆️ Upload to Telegram",
            f"\n🛑 `/cancel {job_id}`"
        ])

    elif stage_upper == "UPLOADING":
        bar = render_progress_bar(progress_pct)
        cur_str = format_filesize(transferred_bytes)
        tot_str = format_filesize(total_bytes or effective_size, default="Calculating...")
        spd_str = format_speed(speed)
        eta_str = format_eta(eta)
        lines.extend([
            "⬆️ **Status:** `Uploading to Telegram...`",
            f"`{bar}`",
            f"⚡ **Speed:** `{spd_str}` | ⏱️ **ETA:** `{eta_str}`",
            f"📦 **Uploaded:** `{cur_str} / {tot_str}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "✅ [1/3] 🔎 Link Resolved",
            "✅ [2/3] ⬇️ Download Complete",
            "🔄 [3/3] ⬆️ Uploading to Telegram",
            f"\n🛑 `/cancel {job_id}`"
        ])

    elif stage_upper == "COMPLETED":
        dur_str = f"{int(duration)}s" if duration else "Done"
        lines.extend([
            "✅ **Task Completed & Delivered!**",
            f"⏱️ **Total Time:** `{dur_str}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "✅ [1/3] 🔎 Link Resolved",
            "✅ [2/3] ⬇️ Download Complete",
            "✅ [3/3] ⬆️ Upload Complete"
        ])

    elif stage_upper == "CANCELLED":
        lines.extend([
            "🛑 **Task Cancelled by User**",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🛑 Job `#{job_id}` cancelled."
        ])

    elif stage_upper == "FAILED":
        err_msg = (error or "Unknown error")[:120]
        lines.extend([
            "❌ **Task Failed**",
            f"⚠️ `{err_msg}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "❌ Process interrupted."
        ])

    return "\n".join(lines)


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

