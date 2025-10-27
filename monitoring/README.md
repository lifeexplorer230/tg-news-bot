# Система мониторинга и алертов

Полноценная система мониторинга для Telegram News Bot, включающая алерты, метрики и health checks.

## Компоненты

### 1. AlertManager (`alerts.py`)

Система алертов с отправкой уведомлений в Telegram.

#### Возможности:
- 4 уровня критичности: INFO, WARNING, ERROR, CRITICAL
- Rate limiting для предотвращения спама
- Форматирование с emoji и контекстом
- Асинхронная очередь для отправки
- Graceful degradation при ошибках

#### Использование:

```python
from monitoring import init_alert_manager, get_alert_manager

# Инициализация
alert_manager = init_alert_manager(
    client=telegram_client,
    target_chat="Soft Status",
    bot_name="News Bot",
    enabled=True,
)

# Запуск worker
await alert_manager.start()

# Отправка алертов
await alert_manager.info("Service Started", "Bot successfully started")
await alert_manager.warning("High Memory", "Memory usage above 80%", {"memory_gb": 7.5})
await alert_manager.error("API Error", "Gemini API timeout", {"timeout_seconds": 10})
await alert_manager.critical("Service Down", "Database connection lost")

# Остановка worker
await alert_manager.stop()
```

#### Rate Limits:
- INFO: 10/час, мин. 60 сек между сообщениями
- WARNING: 20/час, мин. 30 сек между сообщениями
- ERROR: 50/час, мин. 10 сек между сообщениями
- CRITICAL: 100/час, мин. 5 сек между сообщениями

### 2. MetricsCollector (`metrics.py`)

Система сбора метрик с поддержкой Prometheus формата.

#### Типы метрик:
- **Counter**: Монотонно растущее значение (например, количество обработанных сообщений)
- **Gauge**: Текущее значение, может увеличиваться и уменьшаться (например, использование памяти)
- **Histogram**: Распределение значений (например, время выполнения запросов)

#### Использование:

```python
from monitoring import get_metrics_collector, timer

metrics = get_metrics_collector()

# Counter
messages_counter = metrics.counter("messages_processed_total", "Total messages processed")
messages_counter.inc(labels={"channel": "news"})

# Gauge
memory_gauge = metrics.gauge("memory_usage_bytes", "Current memory usage")
memory_gauge.set(1024 * 1024 * 512)  # 512 MB

# Histogram
api_histogram = metrics.histogram("api_request_duration_seconds", "API request duration")
api_histogram.observe(0.234, labels={"endpoint": "/users"})

# Context manager для таймеров
with timer("database_query_duration_seconds", labels={"query": "SELECT"}):
    result = await db.query("SELECT * FROM messages")

# Shortcuts
metrics.inc_counter("requests_total", labels={"method": "GET"})
metrics.set_gauge("active_connections", 42)
metrics.observe_histogram("response_time_seconds", 0.156)

# Экспорт в Prometheus формат
prometheus_text = metrics.export_prometheus()

# Краткая сводка
summary = metrics.get_summary()
```

### 3. HealthChecker (`healthcheck.py`)

Сервис для проверки здоровья всех компонентов системы.

#### Проверяемые компоненты:
- Database (подключение, производительность, наличие таблиц)
- Telegram API (доступность, latency)
- Gemini API (доступность, количество моделей)
- Disk space (свободное место)
- Memory (использование памяти)
- Listener heartbeat (проверка живости listener)

#### Использование:

```python
from monitoring import HealthChecker

# Инициализация
checker = HealthChecker(
    db_path="./data/news.db",
    telegram_client=client,
    gemini_api_key="your-api-key",
    heartbeat_path="./data/heartbeat.txt",
    heartbeat_max_age=180,
)

# Проверка всех компонентов
health = await checker.check_all()

print(f"Status: {health.status}")  # healthy, degraded, или unhealthy

for component in health.components:
    print(f"{component.component}: {component.status}")
    print(f"  Message: {component.message}")
    if component.latency_ms:
        print(f"  Latency: {component.latency_ms:.2f}ms")

# JSON для API
json_data = health.to_dict()
```

## Интеграция с существующими сервисами

### TelegramListener

Добавьте в `services/telegram_listener.py`:

```python
from monitoring import init_alert_manager

class TelegramListener:
    def __init__(self, config):
        # ... existing code ...

        # Инициализация AlertManager
        self.alert_manager = init_alert_manager(
            client=self.client,
            target_chat=config.get("monitoring.alert_chat", "Soft Status"),
            bot_name=config.get("status.bot_name", "News Bot"),
            enabled=config.get("monitoring.alerts_enabled", True),
        )

    async def start(self):
        await self.alert_manager.start()

        await self.alert_manager.info(
            "Listener Started",
            "Telegram listener successfully started",
            {"profile": self.config.profile},
        )

        # ... existing code ...

    async def handle_error(self, error: Exception):
        await self.alert_manager.error(
            "Listener Error",
            f"Error processing message: {str(error)}",
            {"error_type": type(error).__name__},
        )
```

### NewsProcessor

Добавьте в `services/news_processor.py`:

```python
from monitoring import get_metrics_collector, timer

class NewsProcessor:
    def __init__(self, config):
        # ... existing code ...

        self.metrics = get_metrics_collector()

        # Регистрация метрик
        self.metrics.counter("news_processor_runs_total", "Total processor runs")
        self.metrics.counter("news_processed_total", "Total news processed")
        self.metrics.histogram("processor_duration_seconds", "Processor run duration")

    async def run(self):
        self.metrics.inc_counter("news_processor_runs_total")

        with timer("processor_duration_seconds"):
            await self._process_news()

    async def _process_news(self):
        messages = await self.db.get_unprocessed_messages()

        self.metrics.set_gauge("news_unprocessed_count", len(messages))

        for message in messages:
            with timer("news_processing_duration_seconds",
                      labels={"category": message.category}):
                await self._process_message(message)

            self.metrics.inc_counter("news_processed_total",
                                    labels={"category": message.category})
```

## HTTP Endpoints для мониторинга

Для запуска HTTP сервера с endpoints для мониторинга:

```python
from monitoring.examples import run_health_check_server

# В main.py или отдельном процессе
asyncio.create_task(run_health_check_server(config, port=8080))
```

Доступные endpoints:
- `GET /health` - Полная информация о здоровье системы (JSON)
- `GET /metrics` - Метрики в Prometheus формате (text/plain)
- `GET /summary` - Краткая сводка метрик (JSON)

### Пример ответа `/health`:

```json
{
  "status": "healthy",
  "timestamp": "2025-10-27T12:00:00.000000",
  "components": [
    {
      "component": "database",
      "status": "healthy",
      "message": "Database operational",
      "latency_ms": 5.23,
      "details": {
        "channels": 45,
        "messages": 12340
      }
    },
    {
      "component": "telegram_api",
      "status": "healthy",
      "message": "Telegram API operational",
      "latency_ms": 123.45
    }
  ]
}
```

### Пример ответа `/metrics` (Prometheus):

```
# HELP news_processed_total Total number of news processed
# TYPE news_processed_total counter
news_processed_total{category="ozon"} 1234
news_processed_total{category="wildberries"} 5678

# HELP processor_duration_seconds Duration of processor run in seconds
# TYPE processor_duration_seconds histogram
processor_duration_seconds_bucket{le="0.005"} 0
processor_duration_seconds_bucket{le="0.01"} 0
processor_duration_seconds_bucket{le="10.0"} 42
processor_duration_seconds_sum 123.45
processor_duration_seconds_count 42
```

## Конфигурация

Добавьте в `config/base.yaml`:

```yaml
monitoring:
  # Алерты
  alerts_enabled: true
  alert_chat: "Soft Status"  # Чат для отправки алертов

  # Health check
  healthcheck_port: 8080
  healthcheck_enabled: true

  # Метрики
  metrics_enabled: true
```

## Standalone Health Check

Для запуска отдельной проверки здоровья:

```bash
python -m monitoring.examples
```

Это выполнит полную проверку всех компонентов и выведет результаты в консоль.

Exit codes:
- 0 - healthy (все компоненты работают)
- 1 - degraded (некоторые компоненты работают с предупреждениями)
- 2 - unhealthy (есть неработающие компоненты)

## Примеры использования

См. `monitoring/examples.py` для полных примеров интеграции:
- Интеграция AlertManager в TelegramListener
- Сбор метрик в NewsProcessor
- Запуск HTTP сервера для health checks
- Standalone health check скрипт

## Best Practices

### Алерты:
1. Используйте INFO для информационных сообщений (старт/стоп)
2. WARNING для потенциальных проблем (высокая нагрузка)
3. ERROR для ошибок, которые можно обработать
4. CRITICAL только для критичных ситуаций (сервис упал)
5. Добавляйте контекст для упрощения диагностики

### Метрики:
1. Используйте осмысленные имена метрик (с суффиксами `_total`, `_seconds`, `_bytes`)
2. Добавляйте labels для группировки (category, channel, endpoint)
3. Не создавайте слишком много уникальных комбинаций labels (cardinality)
4. Используйте context manager `timer()` для измерения времени
5. Регистрируйте метрики в `__init__`, а не при каждом использовании

### Health Checks:
1. Настройте healthcheck_max_age под ваш heartbeat interval
2. Мониторьте disk space и memory для предотвращения проблем
3. Используйте health check endpoint для внешнего мониторинга (Prometheus, Grafana)
4. Проверяйте критичные зависимости (БД, API)

## Troubleshooting

### Алерты не отправляются
- Проверьте `alerts_enabled` в конфигурации
- Убедитесь, что `alert_manager.start()` вызван
- Проверьте rate limits (возможно, достигнут лимит)
- Проверьте логи на ошибки отправки в Telegram

### Метрики не обновляются
- Убедитесь, что используете глобальный `get_metrics_collector()`
- Проверьте, что метрики регистрируются в `__init__`
- Для histogram убедитесь, что вызываете `observe()`

### Health check показывает unhealthy
- Проверьте логи конкретного компонента
- Убедитесь, что сервисы запущены (listener, БД)
- Проверьте heartbeat файл и его возраст
- Проверьте доступность API (Telegram, Gemini)

## Roadmap

Планируемые улучшения:
- [ ] Grafana dashboards для визуализации метрик
- [ ] Интеграция с Sentry для error tracking
- [ ] Distributed tracing (OpenTelemetry)
- [ ] Slack/Discord интеграция для алертов
- [ ] Автоматическое обнаружение аномалий
- [ ] Historical metrics storage
