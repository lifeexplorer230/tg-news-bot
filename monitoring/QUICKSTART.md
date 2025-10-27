# Quick Start - Система мониторинга

Быстрое руководство по началу работы с системой мониторинга.

## Установка

Установите дополнительные зависимости:

```bash
pip install -r requirements.txt
```

Зависимости для мониторинга:
- `aiohttp` - для HTTP сервера health check

## Быстрый старт

### 1. Проверка здоровья системы

Выполните проверку всех компонентов:

```bash
python scripts/check_health.py --profile marketplace
```

Вывод:
```
================================================================================
✅ SYSTEM HEALTH CHECK - HEALTHY
================================================================================
Profile:   marketplace
Timestamp: 2025-10-27T12:00:00.000000
================================================================================

✅ DATABASE
  Status:  healthy
  Message: Database operational
  Latency: 5.23ms
  Details:
    - channels: 45
    - messages: 12340
    - path: ./data/marketplace_news.db

✅ TELEGRAM_API
  Status:  healthy
  Message: Telegram API operational
  Latency: 123.45ms

...
```

### 2. Запуск HTTP сервера для мониторинга

Запустите health check сервер:

```bash
python scripts/run_healthcheck_server.py --port 8080 --profile marketplace
```

Доступные endpoints:
- http://localhost:8080/ping - Простая проверка живости
- http://localhost:8080/health - Полная информация о здоровье
- http://localhost:8080/metrics - Метрики в Prometheus формате
- http://localhost:8080/summary - Краткая сводка метрик

### 3. Интеграция алертов в код

Добавьте в ваш сервис:

```python
from monitoring import init_alert_manager

# В __init__ вашего сервиса
self.alert_manager = init_alert_manager(
    client=telegram_client,
    target_chat="Soft Status",
    bot_name="News Bot",
    enabled=True,
)

# В start() методе
await self.alert_manager.start()
await self.alert_manager.info(
    "Service Started",
    "Service successfully started",
    {"profile": "marketplace"},
)

# При ошибках
await self.alert_manager.error(
    "Processing Error",
    f"Failed to process message: {error}",
    {"error_type": type(error).__name__},
)

# В stop() методе
await self.alert_manager.stop()
```

### 4. Сбор метрик

Добавьте сбор метрик:

```python
from monitoring import get_metrics_collector, timer

metrics = get_metrics_collector()

# Счетчики
metrics.inc_counter("messages_processed_total")
metrics.inc_counter("errors_total", labels={"type": "network"})

# Gauges
metrics.set_gauge("active_connections", 42)
metrics.set_gauge("queue_size", 100)

# Таймеры (автоматический histogram)
with timer("api_request_duration_seconds", labels={"endpoint": "/users"}):
    result = await api.get_users()
```

### 5. Просмотр метрик

#### Prometheus формат:

```bash
curl http://localhost:8080/metrics
```

Вывод:
```
# HELP messages_processed_total Total messages processed
# TYPE messages_processed_total counter
messages_processed_total 1234

# HELP api_request_duration_seconds API request duration
# TYPE api_request_duration_seconds histogram
api_request_duration_seconds_bucket{endpoint="/users",le="0.1"} 42
api_request_duration_seconds_sum{endpoint="/users"} 123.45
api_request_duration_seconds_count{endpoint="/users"} 42
```

#### JSON сводка:

```bash
curl http://localhost:8080/summary
```

Вывод:
```json
{
  "counters": {
    "messages_processed_total": 1234,
    "errors_total": 5
  },
  "gauges": {
    "active_connections": 42,
    "queue_size": 100
  },
  "histograms": {
    "api_request_duration_seconds": {
      "sum": 123.45,
      "count": 42,
      "avg": 2.94
    }
  }
}
```

## Примеры использования

### Пример 1: Listener с алертами

```python
class TelegramListener:
    def __init__(self, config):
        self.alert_manager = init_alert_manager(
            client=self.client,
            target_chat="Soft Status",
            bot_name="Listener",
        )

    async def start(self):
        await self.alert_manager.start()
        await self.alert_manager.info("Listener Started", "Ready to receive messages")

        try:
            await self._listen_loop()
        except Exception as e:
            await self.alert_manager.critical(
                "Listener Crashed",
                f"Critical error: {str(e)}",
            )
            raise

    async def stop(self):
        await self.alert_manager.info("Listener Stopped", "Graceful shutdown")
        await self.alert_manager.stop()
```

### Пример 2: Processor с метриками

```python
class NewsProcessor:
    def __init__(self, config):
        self.metrics = get_metrics_collector()

    async def run(self):
        self.metrics.inc_counter("processor_runs_total")

        with timer("processor_duration_seconds"):
            messages = await self.db.get_unprocessed()

            for msg in messages:
                with timer("message_processing_seconds"):
                    await self.process(msg)

                self.metrics.inc_counter(
                    "messages_processed_total",
                    labels={"category": msg.category},
                )
```

### Пример 3: Standalone health check

```python
# health_check.py
from monitoring import HealthChecker
from utils.config import load_config

async def main():
    config = load_config()
    checker = HealthChecker(db_path=config.db_path)

    health = await checker.check_all()
    print(f"Status: {health.status}")

    for component in health.components:
        print(f"{component.component}: {component.status}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Тестирование

Запустите тесты:

```bash
pytest monitoring/test_monitoring.py -v
```

Или с coverage:

```bash
pytest monitoring/test_monitoring.py -v --cov=monitoring --cov-report=html
```

## Конфигурация

Добавьте в `config.yaml`:

```yaml
monitoring:
  alerts:
    enabled: true
    target_chat: "Soft Status"
    bot_name: "News Bot"

  healthcheck:
    enabled: true
    port: 8080
```

## Docker интеграция

Добавьте в `docker-compose.yml`:

```yaml
services:
  healthcheck:
    build: .
    command: python scripts/run_healthcheck_server.py --port 8080
    ports:
      - "8080:8080"
    environment:
      - PROFILE=marketplace
```

Теперь можно проверять здоровье через:
```bash
curl http://localhost:8080/health
```

## Prometheus интеграция

Добавьте в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'news-bot'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

## Grafana dashboards

Создайте dashboard с панелями:

1. **Counters** - Line graph для счетчиков
   - Query: `rate(messages_processed_total[5m])`

2. **Gauges** - Gauge panel для текущих значений
   - Query: `active_connections`

3. **Histograms** - Heatmap для распределения времени
   - Query: `api_request_duration_seconds_bucket`

4. **Health Status** - Stat panel
   - Query: Custom query к /health endpoint

## Troubleshooting

### Алерты не отправляются

Проверьте:
1. `alerts_enabled: true` в конфигурации
2. `alert_manager.start()` был вызван
3. Rate limits не достигнуты
4. Telegram client подключен

### Метрики не обновляются

Проверьте:
1. Используете глобальный `get_metrics_collector()`
2. Метрики регистрируются в `__init__`
3. Для histograms вызывается `observe()`

### Health check показывает unhealthy

Проверьте:
1. Сервисы запущены (listener, БД)
2. Heartbeat файл существует и свежий
3. API ключи корректные
4. Достаточно места на диске

## Дальнейшие шаги

1. Настройте Grafana для визуализации метрик
2. Добавьте Prometheus для сбора метрик
3. Настройте алерты в Prometheus/Alertmanager
4. Добавьте дополнительные custom метрики
5. Интегрируйте с CI/CD для автоматических health checks

## Полезные ссылки

- [Полная документация](README.md)
- [Примеры интеграции](examples.py)
- [Тесты](test_monitoring.py)
- [Prometheus документация](https://prometheus.io/docs/)
- [Grafana документация](https://grafana.com/docs/)
