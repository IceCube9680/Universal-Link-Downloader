import pytest
from app.core.metrics import MetricsCollector, render_ascii_bar


def test_metrics_collector():
    collector = MetricsCollector()

    collector.record_job_start("Google Drive")
    collector.record_job_start("Google Drive")
    collector.record_job_start("Mega")

    collector.record_job_complete(downloaded=1048576, uploaded=1048576)
    collector.record_job_fail()
    collector.record_job_cancel()

    assert collector.total_jobs_started == 3
    assert collector.total_jobs_completed == 1
    assert collector.total_jobs_failed == 1
    assert collector.total_jobs_cancelled == 1
    assert collector.total_downloaded_bytes == 1048576
    assert collector.service_usage["Google Drive"] == 2
    assert collector.service_usage["Mega"] == 1

    dashboard_text = collector.format_dashboard(active_workers_count=2)
    assert "Live System & Metrics Telemetry" in dashboard_text
    assert "CPU:" in dashboard_text
    assert "Google Drive" in dashboard_text
    assert "Active Nodes:" in dashboard_text

    prom_text = collector.get_prometheus_metrics()
    assert "bot_jobs_total 3" in prom_text
    assert "bot_jobs_completed_total 1" in prom_text


def test_render_ascii_bar():
    bar_0 = render_ascii_bar(0)
    assert bar_0 == "[░░░░░░░░░░]"

    bar_100 = render_ascii_bar(100)
    assert bar_100 == "[██████████]"

    bar_50 = render_ascii_bar(50)
    assert bar_50 == "[█████░░░░░]"
