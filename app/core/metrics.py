import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional
import psutil
from aiohttp import web

from app.core.logging import get_logger
from app.utils.filesize import format_filesize, format_speed

logger = get_logger("metrics")


def render_ascii_bar(percent: float, length: int = 10) -> str:
    """Generate a clean visual ASCII bar e.g. [████████░░]."""
    clamped = max(0.0, min(100.0, percent))
    filled_len = int(round((clamped / 100.0) * length))
    bar = "█" * filled_len + "░" * (length - filled_len)
    return f"[{bar}]"


class MetricsCollector:
    """
    Real-time system telemetry, throughput metrics, and Prometheus exposition generator.
    """
    def __init__(self):
        self.start_time = time.time()
        self.total_jobs_started = 0
        self.total_jobs_completed = 0
        self.total_jobs_failed = 0
        self.total_jobs_cancelled = 0
        self.total_downloaded_bytes = 0
        self.total_uploaded_bytes = 0
        self.active_downloads = 0
        self.active_uploads = 0
        self.service_usage: Dict[str, int] = defaultdict(int)
        self._http_runner: Optional[web.AppRunner] = None

    def record_job_start(self, service_name: str) -> None:
        self.total_jobs_started += 1
        self.service_usage[service_name] += 1

    def record_job_complete(self, downloaded: int, uploaded: int) -> None:
        self.total_jobs_completed += 1
        self.total_downloaded_bytes += downloaded
        self.total_uploaded_bytes += uploaded

    def record_job_fail(self) -> None:
        self.total_jobs_failed += 1

    def record_job_cancel(self) -> None:
        self.total_jobs_cancelled += 1

    def get_system_telemetry(self) -> Dict[str, Any]:
        """
        Gather CPU, RAM, Disk, and Process stats via psutil.
        """
        process = psutil.Process(os.getpid())
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return {
            "uptime_seconds": int(time.time() - self.start_time),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_used_bytes": ram.used,
            "ram_total_bytes": ram.total,
            "ram_percent": ram.percent,
            "process_ram_bytes": process.memory_info().rss,
            "disk_used_bytes": disk.used,
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
            "disk_percent": disk.percent,
        }

    def format_dashboard(self, active_workers_count: int = 1) -> str:
        """
        Format comprehensive live telemetry report with visual ASCII bars.
        """
        sys_info = self.get_system_telemetry()
        uptime_mins = sys_info["uptime_seconds"] // 60
        uptime_hours = uptime_mins // 60
        uptime_str = f"{uptime_hours}h {uptime_mins % 60}m" if uptime_hours > 0 else f"{uptime_mins}m"

        cpu_bar = render_ascii_bar(sys_info["cpu_percent"])
        ram_bar = render_ascii_bar(sys_info["ram_percent"])
        disk_bar = render_ascii_bar(sys_info["disk_percent"])

        ram_proc = format_filesize(sys_info["process_ram_bytes"])
        ram_sys = f"{format_filesize(sys_info['ram_used_bytes'])} / {format_filesize(sys_info['ram_total_bytes'])}"
        disk_str = f"{format_filesize(sys_info['disk_used_bytes'])} / {format_filesize(sys_info['disk_total_bytes'])}"

        top_services = sorted(self.service_usage.items(), key=lambda x: x[1], reverse=True)[:5]
        services_str = "\n".join([f"  • {s}: `{c}`" for s, c in top_services]) if top_services else "  • None yet"

        return (
            "📈 **Live System & Metrics Telemetry**\n\n"
            "🖥️ **Cluster & Health:**\n"
            f"• **Active Nodes:** `{active_workers_count}`\n"
            f"• **CPU:** `{sys_info['cpu_percent']:.1f}%` {cpu_bar}\n"
            f"• **RAM:** `{sys_info['ram_percent']:.1f}%` {ram_bar}\n"
            f"  └ _Sys: {ram_sys} | Bot: {ram_proc}_\n"
            f"• **Disk:** `{sys_info['disk_percent']:.1f}%` {disk_bar}\n"
            f"  └ _Used: {disk_str}_\n"
            f"• **Uptime:** `{uptime_str}`\n\n"
            "⚡ **Throughput & Bandwidth:**\n"
            f"• **Total Downloaded:** `{format_filesize(self.total_downloaded_bytes)}`\n"
            f"• **Total Uploaded:** `{format_filesize(self.total_uploaded_bytes)}`\n"
            f"• **Completed Jobs:** `{self.total_jobs_completed}`\n"
            f"• **Failed Jobs:** `{self.total_jobs_failed}`\n"
            f"• **Cancelled Jobs:** `{self.total_jobs_cancelled}`\n\n"
            f"🔝 **Top Handlers:**\n{services_str}"
        )

    def get_prometheus_metrics(self) -> str:
        """
        Generate OpenMetrics / Prometheus compatible exposition format.
        """
        sys_info = self.get_system_telemetry()
        lines = [
            "# HELP bot_jobs_total Total number of download jobs started",
            "# TYPE bot_jobs_total counter",
            f"bot_jobs_total {self.total_jobs_started}",
            "# HELP bot_jobs_completed_total Total completed download jobs",
            "# TYPE bot_jobs_completed_total counter",
            f"bot_jobs_completed_total {self.total_jobs_completed}",
            "# HELP bot_jobs_failed_total Total failed jobs",
            "# TYPE bot_jobs_failed_total counter",
            f"bot_jobs_failed_total {self.total_jobs_failed}",
            "# HELP bot_jobs_cancelled_total Total cancelled jobs",
            "# TYPE bot_jobs_cancelled_total counter",
            f"bot_jobs_cancelled_total {self.total_jobs_cancelled}",
            "# HELP bot_downloaded_bytes_total Total bytes downloaded",
            "# TYPE bot_downloaded_bytes_total counter",
            f"bot_downloaded_bytes_total {self.total_downloaded_bytes}",
            "# HELP bot_uploaded_bytes_total Total bytes uploaded",
            "# TYPE bot_uploaded_bytes_total counter",
            f"bot_uploaded_bytes_total {self.total_uploaded_bytes}",
            "# HELP bot_system_cpu_percent System CPU usage percent",
            "# TYPE bot_system_cpu_percent gauge",
            f"bot_system_cpu_percent {sys_info['cpu_percent']}",
            "# HELP bot_system_memory_used_bytes System RAM used bytes",
            "# TYPE bot_system_memory_used_bytes gauge",
            f"bot_system_memory_used_bytes {sys_info['ram_used_bytes']}",
            "# HELP bot_system_disk_used_bytes System Disk used bytes",
            "# TYPE bot_system_disk_used_bytes gauge",
            f"bot_system_disk_used_bytes {sys_info['disk_used_bytes']}",
        ]
        for service, count in self.service_usage.items():
            lines.append(f'bot_service_usage_total{{service="{service}"}} {count}')
        return "\n".join(lines) + "\n"

    async def start_http_exporter(self, host: str = "0.0.0.0", port: int = 9090) -> None:
        """Lightweight HTTP server serving /metrics."""
        try:
            app = web.Application()
            async def metrics_handler(request):
                return web.Response(text=self.get_prometheus_metrics(), content_type="text/plain")
            app.router.add_get("/metrics", metrics_handler)
            app.router.add_get("/health", lambda r: web.Response(text="OK"))

            self._http_runner = web.AppRunner(app)
            await self._http_runner.setup()
            site = web.TCPSite(self._http_runner, host, port)
            await site.start()
            logger.info("Prometheus metrics server running on http://%s:%d/metrics", host, port)
        except Exception as e:
            logger.warning("Could not start Prometheus HTTP exporter on port %d: %s", port, e)

    async def stop_http_exporter(self) -> None:
        if self._http_runner:
            await self._http_runner.cleanup()
            self._http_runner = None


metrics = MetricsCollector()
