import logging
import os
import re
import sys
from typing import Any, MutableMapping, Optional, Tuple


# Regex patterns to sanitize sensitive credentials
SECRET_PATTERNS = [
    re.compile(r'([0-9]{8,10}:[a-zA-Z0-9_-]{35})'),          # Telegram bot tokens
    re.compile(r'(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+'),          # Bearer tokens
    re.compile(r'(?i)(token\s*=\s*)[^\s&]+'),                  # token=...
    re.compile(r'(?i)(password\s*=\s*)[^\s&]+'),               # password=...
    re.compile(r'(?i)(api_key\s*=\s*)[^\s&]+'),                # api_key=...
    re.compile(r'(?i)(secret\s*=\s*)[^\s&]+'),                 # secret=...
    re.compile(r'(?i)(authorization:\s*)[^\r\n]+'),            # Authorization header
    re.compile(r'(?i)(cookie:\s*)[^\r\n]+'),                   # Cookie header
]


class SecretMaskingFilter(logging.Filter):
    """
    Logging filter that redacts sensitive credentials such as bot tokens,
    passwords, and authorization headers from log records.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    self.mask_secrets(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: self.mask_secrets(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True

    @staticmethod
    def mask_secrets(text: str) -> str:
        for pattern in SECRET_PATTERNS:
            text = pattern.sub(r'[REDACTED]', text)
        return text


class JobLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that automatically prefixes log entries with [JOB:<job_id>]
    """
    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> Tuple[Any, MutableMapping[str, Any]]:
        job_id = self.extra.get("job_id") if self.extra else None
        if job_id:
            return f"[JOB:{job_id}] {msg}", kwargs
        return msg, kwargs


def setup_logging(log_level: str = "INFO", log_dir: Optional[str] = "./logs") -> logging.Logger:
    """
    Configure global logging with console and file handlers, formatting,
    and secret masking filters.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    masking_filter = SecretMaskingFilter()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(masking_filter)
    root_logger.addHandler(console_handler)

    # File Handler
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "bot.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(masking_filter)
        root_logger.addHandler(file_handler)

    # Silence noisy 3rd-party loggers
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    logger = logging.getLogger("universal_bot")
    logger.info("Logging initialized with level: %s", log_level.upper())
    return logger


def get_logger(name: str = "universal_bot", job_id: Optional[str] = None) -> logging.LoggerAdapter:
    """
    Get a logger instance optionally tagged with a job_id.
    """
    base_logger = logging.getLogger(name)
    return JobLoggerAdapter(base_logger, {"job_id": job_id})
