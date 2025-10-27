# Changelog - Система мониторинга

## [1.0.0] - 2025-10-27

### Добавлено

#### Система алертов (`monitoring/alerts.py`)
- Реализован `AlertManager` для отправки уведомлений в Telegram
- 4 уровня критичности: INFO, WARNING, ERROR, CRITICAL
- Rate limiting для предотвращения спама:
  - INFO: 10/час, минимум 60 сек между сообщениями
  - WARNING: 20/час, минимум 30 сек между сообщениями
  - ERROR: 50/час, минимум 10 сек между сообщениями
  - CRITICAL: 100/час, минимум 5 сек между сообщениями
- Асинхронная очередь для отправки алертов
- Форматирование с emoji и контекстом
- Graceful shutdown с обработкой оставшихся алертов
- FloodWait error handling с автоматическим retry
- Singleton паттерн через `init_alert_manager()` и `get_alert_manager()`

#### Система метрик (`monitoring/metrics.py`)
- Реализован `MetricsCollector` с поддержкой:
  - **Counter**: монотонно растущие значения
  - **Gauge**: текущие значения (могут увеличиваться и уменьшаться)
  - **Histogram**: распределение значений с buckets
- Labels поддержка для группировки метрик
- Context manager `timer()` для удобного измерения времени
- Экспорт в Prometheus формат
- Краткая сводка через `get_summary()`
- Thread-safe операции с Lock
- Стандартные buckets для таймеров (0.005s - 60s)
- Shortcuts для быстрого доступа: `counter()`, `gauge()`, `histogram()`, `timer()`

#### Health Check сервис (`monitoring/healthcheck.py`)
- Реализован `HealthChecker` для проверки всех компонентов:
  - **Database**: подключение, производительность, наличие таблиц
  - **Telegram API**: доступность, latency, user info
  - **Gemini API**: доступность, количество доступных моделей
  - **Disk Space**: свободное место с thresholds (20% warning, 10% critical)
  - **Memory**: использование памяти с thresholds
  - **Listener Heartbeat**: проверка живости listener процесса
- Параллельное выполнение всех проверок через `asyncio.gather()`
- Измерение latency для API проверок
- Структурированные результаты с `HealthStatus` и `SystemHealth`
- JSON export через `to_dict()` для API endpoints

#### Примеры интеграции (`monitoring/examples.py`)
- Пример интеграции AlertManager в TelegramListener
- Пример сбор метрик в NewsProcessor
- HTTP сервер для health check endpoints
- Standalone health check скрипт

#### Скрипты
- `scripts/run_healthcheck_server.py`: Запуск HTTP сервера с endpoints:
  - `/ping` - простая проверка живости
  - `/health` - полная информация о здоровье системы (JSON)
  - `/metrics` - метрики в Prometheus формате (text/plain)
  - `/summary` - краткая сводка метрик (JSON)
- `scripts/check_health.py`: CLI для быстрой проверки здоровья с:
  - Человекочитаемым выводом (по умолчанию)
  - JSON форматом (`--json`)
  - Тихим режимом (`--quiet`)
  - Exit codes: 0 (healthy), 1 (degraded), 2 (unhealthy)

#### Тесты (`monitoring/test_monitoring.py`)
- Unit тесты для MetricsCollector:
  - Counter с/без labels
  - Gauge (set, inc, dec)
  - Histogram с buckets и stats
  - Timer context manager
  - Prometheus export формат
  - Metrics summary
- Unit тесты для AlertManager:
  - Базовая отправка алертов
  - Форматирование сообщений
  - Rate limiting
  - Отключенные алерты
- Unit тесты для HealthChecker:
  - Database проверки (success/missing)
  - Telegram API проверки
  - Disk space проверки
  - Memory проверки
  - Heartbeat проверки (fresh/old)
  - Комплексная проверка всех компонентов
- Integration тесты:
  - Совместная работа метрик и алертов

#### Документация
- `monitoring/README.md`: Полная документация с:
  - Описанием всех компонентов
  - Примерами использования
  - Интеграцией с существующими сервисами
  - HTTP endpoints описанием
  - Конфигурацией
  - Best practices
  - Troubleshooting
  - Roadmap
- `monitoring/QUICKSTART.md`: Быстрое руководство для начала работы
- `monitoring/CHANGELOG.md`: История изменений

#### Конфигурация
- `config/monitoring.yaml`: Конфигурация системы мониторинга:
  - Настройки алертов (enabled, target_chat, rate_limits)
  - Настройки метрик
  - Настройки health check (port, thresholds, timeouts)
  - Интеграция с listener и processor

#### Зависимости
- Добавлен `aiohttp==3.11.11` в requirements.txt для HTTP сервера

### Особенности реализации

#### Архитектура
- Модульная структура с четким разделением ответственности
- Singleton паттерны для глобальных инстансов
- Асинхронная обработка для неблокирующих операций
- Thread-safe операции где необходимо

#### Производительность
- Асинхронная очередь для алертов (неблокирующая отправка)
- Параллельные health checks через `asyncio.gather()`
- Эффективное хранение метрик с `frozenset` для labels
- Minimal overhead для context managers

#### Надежность
- Graceful shutdown для всех компонентов
- Error handling с fallback логикой
- FloodWait handling для Telegram API
- Retry логика для критичных операций
- Rate limiting для предотвращения спама

#### Интеграция
- Простая интеграция через DI container
- Минимальные изменения в существующем коде
- Backward compatible (можно отключить через config)
- Prometheus-compatible формат метрик

### Примеры использования

```python
# Алерты
from monitoring import init_alert_manager

alert_manager = init_alert_manager(client, "Soft Status")
await alert_manager.start()
await alert_manager.error("Error Title", "Error message", {"context": "value"})
await alert_manager.stop()

# Метрики
from monitoring import get_metrics_collector, timer

metrics = get_metrics_collector()
metrics.inc_counter("requests_total", labels={"method": "GET"})
with timer("request_duration_seconds"):
    await process_request()

# Health Check
from monitoring import HealthChecker

checker = HealthChecker(db_path="./data/db.sqlite")
health = await checker.check_all()
print(health.status)  # healthy, degraded, или unhealthy
```

### Roadmap

Планируемые улучшения:
- [ ] Grafana dashboards для визуализации
- [ ] Sentry интеграция для error tracking
- [ ] OpenTelemetry distributed tracing
- [ ] Slack/Discord поддержка для алертов
- [ ] Автоматическое обнаружение аномалий
- [ ] Historical metrics storage

### Благодарности

Система мониторинга разработана для проекта TG News Bot Phase 4 и следует best practices:
- Prometheus metrics format
- Twelve-Factor App methodology
- Async-first design
- Production-ready код с тестами
