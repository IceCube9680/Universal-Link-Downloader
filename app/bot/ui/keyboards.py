from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.core.constants import UploadMode


def get_start_keyboard() -> InlineKeyboardMarkup:
    """Main start greeting inline buttons."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings:view"),
            InlineKeyboardButton("ℹ️ Help & Formats", callback_data="help:view")
        ],
        [
            InlineKeyboardButton("📊 My Status", callback_data="status:view")
        ]
    ])


def get_settings_keyboard(current_upload_mode: str) -> InlineKeyboardMarkup:
    """Settings keyboard to toggle upload format."""
    is_doc = current_upload_mode == UploadMode.DOCUMENT.value
    doc_text = "🔘 Document (Selected)" if is_doc else "⚪ Document"
    media_text = "⚪ Media (Video/Audio)" if is_doc else "🔘 Media (Selected)"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(doc_text, callback_data=f"set_mode:{UploadMode.DOCUMENT.value}"),
            InlineKeyboardButton(media_text, callback_data=f"set_mode:{UploadMode.MEDIA.value}")
        ],
        [
            InlineKeyboardButton("🔙 Back to Start", callback_data="start:view")
        ]
    ])


def get_confirm_download_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Confirmation keyboard before starting download if AUTO_PROCESS is False."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ Download Now", callback_data=f"dl_start:{job_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"dl_cancel:{job_id}")
        ]
    ])


def get_cancel_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """Cancel button while download/upload is running."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Cancel Job", callback_data=f"dl_cancel:{job_id}")
        ]
    ])


def get_bulk_cancel_keyboard(bulk_id: str) -> InlineKeyboardMarkup:
    """Cancel button for bulk download tasks."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛑 Cancel Bulk Download", callback_data=f"bulk_cancel:{bulk_id}")
        ]
    ])


def get_admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Interactive Admin Dashboard navigation keyboard with multi-tab support."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Overview", callback_data="admin_tab:overview"),
            InlineKeyboardButton("📈 Live Metrics", callback_data="admin_tab:metrics")
        ],
        [
            InlineKeyboardButton("📋 Jobs Queue", callback_data="admin_tab:jobs"),
            InlineKeyboardButton("👥 User Manager", callback_data="admin_tab:users")
        ],
        [
            InlineKeyboardButton("🖥️ Worker Nodes", callback_data="admin_tab:workers"),
            InlineKeyboardButton("🔒 Whitelist / Auth", callback_data="admin_tab:whitelist")
        ],
        [
            InlineKeyboardButton("📜 System Logs", callback_data="admin_tab:logs"),
            InlineKeyboardButton("📡 Backup Channel", callback_data="admin_tab:backup")
        ],
        [
            InlineKeyboardButton("🔒 Toggle Private", callback_data="admin_tab:toggle_private"),
            InlineKeyboardButton("🧹 Clear Cache", callback_data="admin_tab:clearcache")
        ],
        [
            InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="admin_tab:refresh")
        ]
    ])


def get_admin_backup_channel_keyboard() -> InlineKeyboardMarkup:
    """Interactive management keyboard for Backup/Dump Channel settings."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Set / Change Channel", callback_data="admin_backup:prompt"),
            InlineKeyboardButton("🔄 Test Connection", callback_data="admin_backup:test")
        ],
        [
            InlineKeyboardButton("🗑️ Remove Setting", callback_data="admin_backup:clear"),
            InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_tab:overview")
        ]
    ])


def get_admin_backup_cancel_keyboard() -> InlineKeyboardMarkup:
    """Keyboard to cancel active backup channel prompt."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Cancel", callback_data="admin_backup:cancel_prompt")
        ]
    ])
