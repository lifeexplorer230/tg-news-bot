"""
Monitoring module для Telegram News Bot

Включает:
- alerts: Система алертов для отправки уведомлений в Telegram
- metrics: Сбор метрик (counters, gauges, histograms) с экспортом в Prometheus
- healthcheck: Health check сервис для проверки состояния системы
"""

from monitoring.alerts import (
    Alert,
    AlertLevel,
    AlertManager,
    get_alert_manager,
    init_alert_manager,
)
from monitoring.healthcheck import HealthChecker, HealthStatus, SystemHealth
from monitoring.metrics import (
    CounterMetric,
    GaugeMetric,
    HistogramMetric,
    MetricsCollector,
    counter,
    gauge,
    get_metrics_collector,
    histogram,
    timer,
)

__all__ = [
    # Alerts
    "Alert",
    "AlertLevel",
    "AlertManager",
    "init_alert_manager",
    "get_alert_manager",
    # Metrics
    "MetricsCollector",
    "CounterMetric",
    "GaugeMetric",
    "HistogramMetric",
    "get_metrics_collector",
    "counter",
    "gauge",
    "histogram",
    "timer",
    # Health Check
    "HealthChecker",
    "HealthStatus",
    "SystemHealth",
]
