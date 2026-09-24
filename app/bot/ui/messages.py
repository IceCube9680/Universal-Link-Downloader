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
        err_msg = str(error or "Unknown error").strip()
        if len(err_msg) > 500:
            err_msg = f"{err_msg[:497]}..."
        lines.extend([
            "❌ **Task Failed**",
            f"⚠️ {err_msg}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "❌ Process interrupted."
        ])

    return "\n".join(lines)


def get_start_message(first_name: str) -> str:
    return (
        f"👋 **Hello {first_name}!**\n\n"
        "Welcome to the **Universal Link Downloader Bot** 🚀\n\n"
        "Send me any direct or supported link, and I will download the file and upload it to the configured Backup Channel.\n\n"
        "⚡ **Features:**\n"
        "• High-speed streaming downloads\n"
        "• Direct upload to Backup / Dump Channel\n"
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
        "4. **Delivery:** The completed file is uploaded directly to the configured Backup Channel.\n\n"
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


def get_bulk_process_card(
    bulk_id: str,
    stage: str,
    total_links: int,
    completed: int = 0,
    downloading: int = 0,
    uploading: int = 0,
    queued: int = 0,
    failed: int = 0,
    unsupported: int = 0,
    duplicates: int = 0,
    total_downloaded_bytes: int = 0,
    active_filename: Optional[str] = None,
    elapsed_seconds: Optional[float] = None,
    active_state: Optional[str] = None,
    active_progress_pct: Optional[float] = None,
    active_transferred_bytes: Optional[int] = None,
    active_total_bytes: Optional[int] = None,
    active_speed: Optional[float] = None,
    active_eta: Optional[float] = None,
    active_item_index: Optional[int] = None
) -> str:
    """
    Generate live progress card for aggregated multi-link or container downloads,
    displaying both overall bulk progress bar and active item file processing bar.
    """
    pct = (completed / total_links * 100.0) if total_links > 0 else 0.0
    bulk_bar = render_progress_bar(pct)
    transferred_str = format_filesize(total_downloaded_bytes)

    lines = [
        f"📦 **Bulk Download `#{bulk_id}`**",
        f"📊 **Bulk Progress:** `{bulk_bar}` **{completed}/{total_links}** ({pct:.1f}%)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⬇️ **Active:** `{downloading}` | ⬆️ **Uploading:** `{uploading}` | ⏳ **Queued:** `{queued}`",
        f"✅ **Done:** `{completed}` | ❌ **Failed:** `{failed}` | ⚠️ **Unsupported:** `{unsupported}`",
        f"📥 **Total Volume:** `{transferred_str}`"
    ]

    # Individual active file processing bar section
    if active_filename or active_state:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        idx_prefix = f"({active_item_index}/{total_links}) " if active_item_index else ""
        if active_filename:
            short_fn = active_filename if len(active_filename) <= 45 else f"{active_filename[:42]}..."
            lines.append(f"📄 **Current File:** `{idx_prefix}{short_fn}`")
        elif active_item_index:
            lines.append(f"📄 **Current File:** `Item {active_item_index}/{total_links}`")

        state_badge = "⚡ **File Progress:**"
        if active_state:
            st_up = str(active_state).upper()
            if "DOWNLOADING" in st_up:
                state_badge = "⬇️ **Downloading:**"
            elif "UPLOADING" in st_up:
                state_badge = "⬆️ **Uploading:**"

        file_pct = active_progress_pct if active_progress_pct is not None else 0.0
        file_bar = render_progress_bar(file_pct)
        lines.append(f"{state_badge} `{file_bar}`")

        # Telemetry: size, speed, ETA
        info_parts = []
        if active_transferred_bytes is not None or active_total_bytes is not None:
            cur_b = format_filesize(active_transferred_bytes or 0)
            tot_b = format_filesize(active_total_bytes, default="Calculating...") if active_total_bytes else "Calculating..."
            info_parts.append(f"📦 `{cur_b} / {tot_b}`")

        if active_speed is not None and active_speed > 0:
            info_parts.append(f"⚡ `{format_speed(active_speed)}`")

        if active_eta is not None and active_eta > 0:
            info_parts.append(f"⏱️ `{format_eta(active_eta)}`")

        if info_parts:
            lines.append(" | ".join(info_parts))

    if elapsed_seconds is not None and elapsed_seconds > 0:
        lines.append(f"⏱️ **Elapsed:** `{int(elapsed_seconds)}s`")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if stage.upper() == "DISCOVERING":
        lines.append("🔎 _Scanning page and extracting links..._")
    elif stage.upper() == "RUNNING":
        lines.append(f"🚀 _Processing downloads safely with controlled concurrency..._\n🛑 `/cancel {bulk_id}`")
    elif stage.upper() == "CANCELLED":
        lines.append("🛑 _Bulk download cancelled by user._")
    elif stage.upper() == "COMPLETED":
        lines.append("🎉 _All discovered items processed!_")

    return "\n".join(lines)


def get_bulk_summary_card(
    bulk_id: str,
    total_discovered: int,
    processed: int,
    successful: int,
    failed: int,
    unsupported: int,
    duplicates: int,
    total_bytes: int,
    duration_seconds: float,
    failed_details: Optional[list] = None
) -> str:
    """
    Generate clean completion summary report for bulk download jobs.
    """
    vol_str = format_filesize(total_bytes)
    dur_str = f"{int(duration_seconds)}s" if duration_seconds < 60 else f"{int(duration_seconds // 60)}m {int(duration_seconds % 60)}s"

    lines = [
        "✅ **Bulk Download Completed**",
        f"🆔 **Job ID:** `#{bulk_id}`",
        f"⏱️ **Duration:** `{dur_str}`",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔎 **Total Discovered:** `{total_discovered}`",
        f"🚀 **Processed:** `{processed}`",
        f"✅ **Successful Files:** `{successful}`",
        f"❌ **Failed:** `{failed}`",
        f"⚠️ **Unsupported Links:** `{unsupported}`",
        f"🔁 **Duplicates Skipped:** `{duplicates}`",
        f"📦 **Total Transferred:** `{vol_str}`",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if failed_details:
        lines.append("⚠️ **Failures Summary:**")
        for err_item in failed_details[:5]:
            lines.append(f"• `{err_item}`")
        if len(failed_details) > 5:
            lines.append(f"• _...and {len(failed_details) - 5} more_")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    lines.append("✨ _All delivered files have been uploaded to the Backup Channel._")
    return "\n".join(lines)

