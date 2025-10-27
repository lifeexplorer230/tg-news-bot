"""
Тесты для системы мониторинга

Проверяет работоспособность:
- AlertManager
- MetricsCollector
- HealthChecker
"""

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Тесты MetricsCollector
# ============================================================================


def test_counter_basic():
    """Тест базовой функциональности counter"""
    from monitoring.metrics import MetricsCollector

    metrics = MetricsCollector()
    counter = metrics.counter("test_counter", "Test counter")

    # Увеличиваем
    counter.inc()
    assert counter.get() == 1.0

    counter.inc(value=5.0)
    assert counter.get() == 6.0


def test_counter_with_labels():
    """Тест counter с labels"""
    from monitoring.metrics import MetricsCollector

    metrics = MetricsCollector()
    counter = metrics.counter("test_counter", "Test counter")

    # Разные labels
    counter.inc(labels={"method": "GET"})
    counter.inc(labels={"method": "POST"})
    counter.inc(labels={"method": "GET"})

    assert counter.get(labels={"method": "GET"}) == 2.0
    assert counter.get(labels={"method": "POST"}) == 1.0


def test_gauge_basic():
    """Тест базовой функциональности gauge"""
    from monitoring.metrics import MetricsCollector

    metrics = MetricsCollector()
    gauge = metrics.gauge("test_gauge", "Test gauge")

    # Set
    gauge.set(10.0)
    assert gauge.get() == 10.0

    # Inc
    gauge.inc(value=5.0)
    assert gauge.get() == 15.0

    # Dec
    gauge.dec(value=3.0)
    assert gauge.get() == 12.0


def test_histogram_basic():
    """Тест базовой функциональности histogram"""
    from monitoring.metrics import MetricsCollector

    metrics = MetricsCollector()
    histogram = metrics.histogram(
        "test_histogram",
        "Test histogram",
        buckets=[0.1, 0.5, 1.0, 5.0],
    )

    # Добавляем наблюдения
    histogram.observe(0.05)
    histogram.observe(0.3)
    histogram.observe(0.7)
    histogram.observe(2.0)

    stats = histogram.get_stats()
    assert stats["count"] == 4
    assert stats["sum"] == 3.05
    assert abs(stats["avg"] - 0.7625) < 0.001


def test_timer_context_manager():
    """Тест context manager для таймера"""
    from monitoring.metrics import MetricsCollector

    metrics = MetricsCollector()

    with metrics.timer("test_duration"):
        time.sleep(0.1)

    histogram = metrics.histogram("test_duration")
    stats = histogram.get_stats()

    assert stats["count"] == 1
    assert stats["avg"] >= 0.1


def test_prometheus_export():
    """Тест экспорта в Prometheus формат"""
    from monitoring.metrics import MetricsCollector

    metrics = MetricsCollector()

    # Создаем метрики
    counter = metrics.counter("http_requests_total", "Total HTTP requests")
    counter.inc(labels={"method": "GET", "status": "200"}, value=100)

    gauge = metrics.gauge("memory_usage_bytes", "Memory usage")
    gauge.set(1024 * 1024 * 512)

    # Экспортируем
    output = metrics.export_prometheus()

    # Проверяем формат
    assert "# HELP http_requests_total Total HTTP requests" in output
    assert "# TYPE http_requests_total counter" in output
    assert 'http_requests_total{method="GET",status="200"} 100' in output

    assert "# HELP memory_usage_bytes Memory usage" in output
    assert "# TYPE memory_usage_bytes gauge" in output
    assert "memory_usage_bytes 536870912" in output


def test_metrics_summary():
    """Тест получения краткой сводки"""
    from monitoring.metrics import MetricsCollector

    metrics = MetricsCollector()

    metrics.counter("requests_total").inc(value=100)
    metrics.gauge("active_users").set(42)
    metrics.histogram("response_time").observe(0.5)

    summary = metrics.get_summary()

    assert summary["counters"]["requests_total"] == 100
    assert summary["gauges"]["active_users"] == 42
    assert summary["histograms"]["response_time"]["count"] == 1


# ============================================================================
# Тесты AlertManager
# ============================================================================


@pytest.mark.asyncio
async def test_alert_manager_basic():
    """Тест базовой функциональности AlertManager"""
    from monitoring.alerts import AlertLevel, AlertManager

    # Mock Telegram client
    mock_client = AsyncMock()

    manager = AlertManager(
        client=mock_client,
        target_chat="test_chat",
        bot_name="Test Bot",
        enabled=True,
    )

    await manager.start()

    # Отправляем алерт
    await manager.info("Test Title", "Test message")

    # Даем время на обработку
    await asyncio.sleep(0.5)

    await manager.stop()

    # Проверяем, что сообщение отправлено
    assert mock_client.send_message.called


@pytest.mark.asyncio
async def test_alert_formatting():
    """Тест форматирования алертов"""
    from monitoring.alerts import Alert, AlertLevel, AlertManager

    mock_client = AsyncMock()
    manager = AlertManager(mock_client, "test_chat")

    alert = Alert(
        level=AlertLevel.ERROR,
        title="Database Error",
        message="Connection timeout",
        context={"timeout_seconds": 30, "retry_count": 3},
    )

    formatted = manager._format_alert(alert)

    # Проверяем наличие ключевых элементов
    assert "❌" in formatted  # ERROR emoji
    assert "ERROR" in formatted
    assert "Database Error" in formatted
    assert "Connection timeout" in formatted
    assert "Context:" in formatted
    assert "timeout_seconds" in formatted
    assert "30" in formatted


@pytest.mark.asyncio
async def test_alert_rate_limiting():
    """Тест rate limiting"""
    from monitoring.alerts import AlertLevel, AlertManager

    mock_client = AsyncMock()
    manager = AlertManager(mock_client, "test_chat")

    # Проверяем начальное состояние
    should_send, reason = manager._should_send_alert(AlertLevel.INFO)
    assert should_send is True

    # Симулируем отправку
    state = manager._rate_limits[AlertLevel.INFO]
    state.last_sent = time.time()
    state.count_in_window = 1
    state.window_start = time.time()

    # Сразу после отправки не должно пройти (min_interval)
    should_send, reason = manager._should_send_alert(AlertLevel.INFO)
    assert should_send is False
    assert "min_interval" in reason


@pytest.mark.asyncio
async def test_alert_disabled():
    """Тест отключенных алертов"""
    from monitoring.alerts import AlertManager

    mock_client = AsyncMock()
    manager = AlertManager(
        client=mock_client,
        target_chat="test_chat",
        enabled=False,
    )

    # Отправка алерта не должна ничего делать
    await manager.info("Test", "Test message")

    # Проверяем, что worker не запущен
    await manager.start()
    assert manager._worker_task is None


# ============================================================================
# Тесты HealthChecker
# ============================================================================


@pytest.mark.asyncio
async def test_healthcheck_database_success():
    """Тест успешной проверки БД"""
    from monitoring.healthcheck import HealthChecker

    # Создаем временную БД
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        # Создаем таблицы
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE channels (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE raw_messages (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        checker = HealthChecker(db_path=db_path)
        status = await checker.check_database()

        assert status.status == "healthy"
        assert status.component == "database"
        assert status.latency_ms is not None

    finally:
        Path(db_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_healthcheck_database_missing():
    """Тест проверки несуществующей БД"""
    from monitoring.healthcheck import HealthChecker

    checker = HealthChecker(db_path="/nonexistent/path/db.sqlite")
    status = await checker.check_database()

    assert status.status == "unhealthy"
    assert "does not exist" in status.message


@pytest.mark.asyncio
async def test_healthcheck_telegram_api():
    """Тест проверки Telegram API"""
    from monitoring.healthcheck import HealthChecker

    # Mock Telegram client
    mock_client = AsyncMock()
    mock_client.is_connected.return_value = True

    mock_user = MagicMock()
    mock_user.id = 12345
    mock_user.username = "test_user"
    mock_client.get_me.return_value = mock_user

    checker = HealthChecker(telegram_client=mock_client)
    status = await checker.check_telegram_api()

    assert status.status == "healthy"
    assert status.component == "telegram_api"
    assert status.details["user_id"] == 12345


@pytest.mark.asyncio
async def test_healthcheck_telegram_api_not_connected():
    """Тест проверки не подключенного Telegram API"""
    from monitoring.healthcheck import HealthChecker

    mock_client = AsyncMock()
    mock_client.is_connected.return_value = False

    checker = HealthChecker(telegram_client=mock_client)
    status = await checker.check_telegram_api()

    assert status.status == "unhealthy"
    assert "not connected" in status.message


@pytest.mark.asyncio
async def test_healthcheck_disk_space():
    """Тест проверки места на диске"""
    from monitoring.healthcheck import HealthChecker

    checker = HealthChecker()
    status = await checker.check_disk_space()

    # Должен быть какой-то статус
    assert status.status in ["healthy", "degraded", "unhealthy"]
    assert status.component == "disk_space"
    assert "free_percent" in status.details


@pytest.mark.asyncio
async def test_healthcheck_heartbeat_fresh():
    """Тест проверки свежего heartbeat"""
    from monitoring.healthcheck import HealthChecker

    # Создаем временный heartbeat файл
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
        tmp.write("alive")
        heartbeat_path = tmp.name

    try:
        checker = HealthChecker(
            heartbeat_path=heartbeat_path,
            heartbeat_max_age=60,
        )
        status = await checker.check_listener_heartbeat()

        assert status.status == "healthy"
        assert status.details["age_seconds"] < 60

    finally:
        Path(heartbeat_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_healthcheck_heartbeat_old():
    """Тест проверки старого heartbeat"""
    from monitoring.healthcheck import HealthChecker

    # Создаем временный heartbeat файл
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
        tmp.write("alive")
        heartbeat_path = tmp.name

    try:
        # Меняем mtime на старое значение
        old_time = time.time() - 200
        Path(heartbeat_path).touch()
        import os

        os.utime(heartbeat_path, (old_time, old_time))

        checker = HealthChecker(
            heartbeat_path=heartbeat_path,
            heartbeat_max_age=60,
        )
        status = await checker.check_listener_heartbeat()

        assert status.status == "unhealthy"
        assert "too old" in status.message

    finally:
        Path(heartbeat_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_healthcheck_all():
    """Тест проверки всех компонентов"""
    from monitoring.healthcheck import HealthChecker

    checker = HealthChecker()
    health = await checker.check_all()

    assert health.status in ["healthy", "degraded", "unhealthy"]
    assert len(health.components) > 0

    # Проверяем формат JSON
    json_data = health.to_dict()
    assert "status" in json_data
    assert "timestamp" in json_data
    assert "components" in json_data


# ============================================================================
# Integration тесты
# ============================================================================


@pytest.mark.asyncio
async def test_integration_metrics_and_alerts():
    """Интеграционный тест: метрики + алерты"""
    from monitoring.alerts import AlertManager
    from monitoring.metrics import get_metrics_collector

    mock_client = AsyncMock()
    manager = AlertManager(mock_client, "test_chat")
    await manager.start()

    metrics = get_metrics_collector()

    # Симулируем обработку запросов
    for i in range(10):
        with metrics.timer("request_duration"):
            time.sleep(0.01)

        metrics.inc_counter("requests_total")

        if i == 5:
            # На 5-м запросе отправляем алерт
            await manager.warning(
                "High Load",
                "Processing many requests",
                {"count": i},
            )

    await asyncio.sleep(0.5)
    await manager.stop()

    # Проверяем метрики
    summary = metrics.get_summary()
    assert summary["counters"]["requests_total"] == 10
    assert summary["histograms"]["request_duration"]["count"] == 10

    # Проверяем, что алерт отправлен
    assert mock_client.send_message.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
