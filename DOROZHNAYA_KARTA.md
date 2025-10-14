# 🗺️ ДОРОЖНАЯ КАРТА: TELEGRAM NEWS BOT — СТАБИЛИЗАЦИЯ И РАЗВИТИЕ

**Версия:** 1.0.0
**Дата запуска цикла:** 2025-10-14
**Статус:** 🟢 Активна

---

## 📌 Контекст и цели

| Аспект | Описание |
|--------|----------|
| **Наследие** | Проект tg-news-bot клонирован из marketplace-news-bot с базовой функциональностью: listener, processor, Gemini AI, embeddings, профили конфигурации. FloodWait protection добавлен 2025-10-14. |
| **Запрос** | Стабилизировать систему, добавить тестовое покрытие, улучшить надежность, оптимизировать производительность, подготовить к production deployment. |
| **Ограничения** | Минимальные изменения в стабильных компонентах, сохранение обратной совместимости с marketplace-news-bot, SQLite как основной storage, отсутствие breaking changes в API. |
| **Цель** | Довести проект до production-ready состояния с coverage > 70%, полной документацией, CI/CD pipeline, мониторингом и operational procedures. |

---

## 🎯 Основные задачи

1. **Стабилизация базовой функциональности** — проверка listener, processor, database, устранение критичных багов.
2. **Тестовое покрытие** — unit-тесты для всех компонентов, интеграционные тесты, coverage > 70%.
3. **Улучшение надежности** — Gemini retry логика, DB concurrency, graceful shutdown, error recovery.
4. **Оптимизация производительности** — lazy loading, batch operations, кэширование, профилирование.
5. **Документация и CI/CD** — обновленная документация, GitHub Actions, pre-commit hooks, release процедуры.

---

## ⚖️ Сравнение вариантов

| Критерий | Вариант A: Минимальные фиксы | Вариант B: Полная стабилизация (выбран) | Вариант C: Полный рефакторинг |
|----------|------------------------------|------------------------------------------|-------------------------------|
| Время до production | Низкое (1 неделя) | Среднее (2-3 недели) | Высокое (1-2 месяца) |
| Риск регрессий | Высокий | Средний (покрыт тестами) | Очень высокий |
| Качество кода | Низкое | Высокое | Очень высокое |
| Maintainability | Низкая | Высокая | Очень высокая |
| Coverage | < 30% | > 70% | > 90% |
| Вывод | Быстро но ненадежно | ✅ **Выбран** | Слишком долго |

**Обоснование выбора B:**
Баланс между скоростью и качеством. Тесты обеспечат стабильность, минимальные изменения сохранят совместимость, операционные процедуры упростят поддержку.

---

## 🧭 Подход

### Минимальные партии
- Следуем принципу **diff-limit**: безопасная граница **150 строк**, warning **300 строк**, fail **> 500 строк**
- Каждая партия = один логический блок изменений
- При превышении limit — разбиваем на меньшие части
- **Escalation через "обстукивание туннеля"**: пробный коммит → анализ → корректировка размера

### Двойная проверка
- После каждой партии обязательны:
  - `git diff --stat` — проверка размера изменений
  - Ревизия через `memory-bank/verification-protocol.md`
  - Обновление журнала прогресса
  - Запуск тестов (если есть)

### Точки отката
- На стыке этапов A–E создаём **snapshot commits**
- Фиксируем контрольные теги: `v1.0.0-stageA`, `v1.0.0-stageB`
- Сохраняем baseline в `snapshot/` (локально, не в git)
- При проблемах — откат через `git checkout <tag>`

### Контроль диффов
- Каждая подзадача → **отдельный коммит**
- В PR попадает **линейная история**
- После инцидента: уменьшаем партию, обновляем `diff-limit-plan.md`
- Никогда не squash commits до review

### Артефакты вне git
- **В git:** `.gitkeep`, инструкции, результаты анализа, тесты
- **Локально:** логи, snapshots, baseline, временные файлы
- **Структура:**
  ```
  logs/         # Логи (в git только .gitkeep)
  snapshot/     # Baseline снапшоты (локально)
  data/         # БД и embeddings (локально)
  ```

### Протокол работы
- Любая рабочая итерация стартует командой: **`Протокол, шаг <код>`**
- Последовательность: **Memory → Roadmap → Instruction → Execute → Update**
- Обязательное обновление журнала после каждого шага

---

## 🔢 Этапы A–E

| Код | Название | Ключевые действия | Контрольные проверки |
|-----|----------|-------------------|----------------------|
| **A** | Стабилизация базы | Проверка listener/processor/db, устранение критичных багов, проверка FloodWait fix | Smoke-тест: listener → сохранение → processor → публикация |
| **B** | Тестовое покрытие | Unit-тесты Database, Gemini, Embeddings, Processor, Coverage > 70% | pytest -v, coverage report, все тесты зеленые |
| **C** | Надежность | Gemini retry, DB WAL/concurrency, graceful shutdown, error recovery | Stress-тест, проверка recovery, логи без ошибок |
| **D** | Оптимизация | Lazy loading, batch operations, профилирование, кэширование | Benchmark до/после, < 5s на 100 сообщений |
| **E** | Документация & CI/CD | README, операционные процедуры, GitHub Actions, pre-commit hooks | CI/CD зеленый, документация актуальна |

### Вложенные проверки:

**Этап A — Стабилизация:**
- A1: Проверка listener (загрузка каналов, сохранение сообщений)
- A2: Проверка processor (обработка, Gemini API, публикация)
- A3: Проверка database (WAL mode, concurrent access, cleanup)
- A4: Baseline smoke-тест (end-to-end flow)

**Этап B — Тестирование:**
- B1: Unit-тесты Database (save, retrieve, mark_processed, embeddings)
- B2: Unit-тесты Gemini Client (mock API, retry, validation)
- B3: Unit-тесты Embeddings (encode, similarity, batch)
- B4: Integration тесты Processor (full flow with mocks)
- B5: Coverage report (> 70% target)

**Этап C — Надежность:**
- C1: Gemini retry logic (tenacity, exponential backoff)
- C2: Pydantic validation для Gemini ответов
- C3: DB concurrency improvements (WAL mode verification)
- C4: Graceful shutdown (signal handlers, cleanup)
- C5: Error recovery tests

**Этап D — Оптимизация:**
- D1: Lazy loading для EmbeddingService
- D2: Batch operations для embeddings
- D3: Профилирование processor (identify bottlenecks)
- D4: Кэширование (lru_cache для тяжелых операций)
- D5: Benchmark и сравнение

**Этап E — DevOps:**
- E1: README обновление
- E2: Operational playbook
- E3: GitHub Actions CI/CD
- E4: Pre-commit hooks (ruff, black, pytest)
- E5: Release процедуры

---

## ⚠️ Риски и меры

| Риск | Вероятность | Влияние | Митигирующие действия |
|------|-------------|---------|------------------------|
| FloodWait возвращается | Низкая | Критическое | Проверить все места с `client.start()`, code review перед merge |
| Тесты падают при интеграции | Средняя | Высокое | Запускать pytest после каждого коммита, CI/CD обязателен |
| DB locked errors | Средняя | Среднее | WAL mode verification, stress-тесты, retry логика |
| Gemini API quota exceeded | Высокая | Среднее | Rate limiting, retry с backoff, мониторинг квот |
| Партия изменений слишком большая | Средняя | Среднее | Контроль diff size, обновление diff-limit-plan.md |
| Потеря baseline при откате | Низкая | Высокое | Snapshot сохранение в `snapshot/<дата>-<этап>/` локально |

---

## 🚀 Спринты стабилизации (на основе code review)

Задачи выявлены в результате code review от 2025-10-14. Организованы в 3 спринта по приоритету.

### Спринт 1: Критические блокеры (5-7 дней)

**Цель:** Устранить критические дефекты, блокирующие production deployment

#### CR-C1: StatusReporter Database DI fix
**Приоритет:** 🔴 Критический
**Оценка:** 3 часа

**Проблема:**
- StatusReporter передаёт `timezone_name` в конструктор Database
- Database.__init__ принимает только `db_path`
- Результат: TypeError при создании StatusReporter

**Источники:**
- `database/db.py:18-39`
- `services/status_reporter.py:12-92`
- `services/status_reporter.py:23-32`

**Шаги:**
1. Исправить конструктор StatusReporter: передавать только db_path или Database instance
2. Удалить timezone_name из вызова Database()
3. Обновить все места создания StatusReporter
4. Добавить тест: StatusReporter с разными вариантами инициализации

**Критерии приёмки:**
- ✅ StatusReporter создаётся без TypeError
- ✅ Тесты проходят
- ✅ Database принимает корректные параметры

**Файлы:**
- `services/status_reporter.py`
- `database/db.py`
- `main.py`
- `tests/test_status_reporter.py`

---

#### CR-C2: processed флаг для всех сообщений
**Приоритет:** 🔴 Критический
**Оценка:** 6 часов

**Проблема:**
- Флаг `processed=1` устанавливается на этапе keyword-фильтра
- При старом режиме (use_categories=false) после первого маркетплейса остальные не получают сообщений
- Отклонённые сообщения переобрабатываются бесконечно

**Источники:**
- `services/marketplace_processor.py:133-235`
- `database/db.py:200-239`

**Шаги:**
1. Добавить поле `rejection_reason TEXT` в `raw_messages`
2. Создать миграцию БД
3. Обновить `mark_as_processed()`: добавить параметр `reason`
4. Помечать ВСЕ обработанные сообщения:
   - `duplicate` — дубликат
   - `rejected_keywords` — отфильтрован keyword
   - `rejected_llm` — не вошёл в топ-N LLM
   - `published` — успешно опубликован
5. Процессор помечает сообщения ПОСЛЕ обработки всех маркетплейсов
6. Тесты на все сценарии отклонения

**Критерии приёмки:**
- ✅ Все сообщения помечаются processed=1 после обработки
- ✅ rejection_reason корректно заполняется
- ✅ Нет повторной обработки старых сообщений
- ✅ Coverage database/db.py > 95%

**Файлы:**
- `database/db.py`
- `services/marketplace_processor.py`
- `migrations/` (новая миграция)
- `tests/test_processor_statuses.py` (новый)

---

#### CR-C3: SQLite lifecycle и concurrency
**Приоритет:** 🔴 Критический
**Оценка:** 5 часов

**Проблема:**
- listener закрывает соединение, а фоновые задачи продолжают использовать закрытую БД
- Повторное использование подключения из разных потоков/тасков
- Риск OperationalError и database locked

**Шаги:**
1. Включить WAL mode для SQLite (если ещё не включен)
2. DatabaseFactory для управления подключениями per-thread
3. Каждый компонент (listener, processor, status) создаёт своё подключение
4. Обновить main.py: передавать db_path вместо db instance
5. Mutex для критических операций записи
6. Интеграционный тест: параллельные записи из разных потоков
7. Тест graceful shutdown: корректное закрытие connections

**Критерии приёмки:**
- ✅ Нет "database is locked" ошибок
- ✅ WAL mode активен
- ✅ Каждый компонент имеет свой connection
- ✅ Graceful shutdown корректно закрывает connections

**Файлы:**
- `database/db.py`
- `main.py`
- `services/telegram_listener.py`
- `services/marketplace_processor.py`
- `services/status_reporter.py`
- `tests/test_database_concurrency.py` (новый)

---

#### CR-C7: Adaptive scheduler (замена sleep)
**Приоритет:** 🟡 Высокий
**Оценка:** 3 часа

**Проблема:**
- Жёсткий `sleep(60)` в планировщике → задержки до 60s
- Невозможны интервалы < 60s
- Дрожание таймингов

**Источники:**
- `main.py:163-170`

**Шаги:**
1. Заменить `time.sleep(60)` на `schedule.idle_seconds()`
2. Safety sleep (max 5 секунд) для предотвращения busy-wait
3. Edge cases: пустое расписание, пропущенные задачи
4. Юнит-тесты:
   - Корректный расчёт idle time
   - Обработка пропущенных задач
   - Graceful shutdown во время ожидания

**Критерии приёмки:**
- ✅ Adaptive idle через schedule.idle_seconds()
- ✅ Safety sleep ≤ 5 секунд
- ✅ Тесты покрывают edge cases
- ✅ Graceful shutdown работает

**Файлы:**
- `main.py`
- `tests/test_scheduler.py` (новый)

---

### Спринт 2: Высокий приоритет (5-7 дней)

**Цель:** Оптимизация производительности и надёжности LLM/embeddings

#### CR-H1: Оптимизация чтения сообщений
**Приоритет:** 🟡 Высокий
**Оценка:** 4 часа

**Проблема:**
- Повторное чтение всех сообщений/эмбеддингов по каждому маркетплейсу
- Неэффективная работа с БД

**Источники:**
- `services/marketplace_processor.py:133-206`
- `database/db.py:200-239`

**Шаги:**
1. Загружать сообщения один раз перед обработкой всех маркетплейсов
2. Кэшировать результат в памяти процессора
3. Переиспользовать данные для разных маркетплейсов
4. Benchmark: сравнить время обработки до/после

**Критерии приёмки:**
- ✅ Сообщения загружаются один раз
- ✅ Данные переиспользуются
- ✅ Ускорение ≥ 2x для multi-marketplace
- ✅ Memory footprint приемлемый

**Файлы:**
- `services/marketplace_processor.py`
- `tests/test_processor_performance.py` (новый)

---

#### CR-C5: Batch embeddings и async дедупликация
**Приоритет:** 🟡 Высокий
**Оценка:** 6 часов

**Проблема:**
- Блокирующая sync encode внутри async кода
- Повторные чтения/десериализации всех embeddings
- Квадратичная сложность дедупликации

**Шаги:**
1. Реализовать батчевое кодирование в EmbeddingService
2. Кэш published_embeddings на весь прогон processor
3. Async wrapper для encode (run_in_executor)
4. Оптимизация similarity checks (numpy vectorization)
5. Нагрузочный тест: 1000 сообщений, замер времени

**Критерии приёмки:**
- ✅ Batch encoding (≥10 сообщений за раз)
- ✅ published_embeddings кэшируются
- ✅ Async не блокируется
- ✅ Ускорение ≥ 5x

**Файлы:**
- `services/embeddings.py`
- `services/marketplace_processor.py`
- `database/db.py`
- `tests/test_batch_performance.py`

---

#### CR-C6: Robust LLM (JSON validation, retry, chunking)
**Приоритет:** 🟡 Высокий
**Оценка:** 7 часов

**Проблема:**
- Перегруженные промпты Gemini (десятки/сотни сообщений)
- Хрупкий парсинг JSON регулярками
- Нет валидации ответов

**Источники:**
- `services/marketplace_processor.py:288-352`
- `services/gemini_client.py:197-338`
- `services/gemini_client.py:512-618`

**Шаги:**
1. Добавить Pydantic схемы для Gemini responses
2. Chunking промптов (max 50 сообщений за запрос)
3. Retry логика с exponential backoff (tenacity)
4. Валидация размера промпта перед отправкой
5. Обработка частичных ответов
6. Улучшенное логирование (request_id, длина промпта, попытки)
7. Property-based тесты

**Критерии приёмки:**
- ✅ Pydantic валидация всех ответов
- ✅ Chunking промптов работает
- ✅ Retry работает корректно
- ✅ Детальное логирование

**Файлы:**
- `services/gemini_client.py`
- `models/llm_schemas.py` (новый)
- `tests/test_gemini_errors.py`
- `tests/test_gemini_chunking.py` (новый)

---

#### CR-H4: Валидация конфигурации (Pydantic)
**Приоритет:** 🟡 Высокий
**Оценка:** 4 часа

**Проблема:**
- Жёсткие `int(os.getenv(...))` без проверок → падения на старте
- Нет валидации YAML конфигов
- Недружелюбные error messages

**Шаги:**
1. Создать Pydantic модели для всех секций конфига
2. Валидация при загрузке конфига (utils/config.py)
3. Дружелюбные error messages с указанием проблемных параметров
4. Тесты на невалидные конфиги

**Критерии приёмки:**
- ✅ Pydantic схемы для всех конфигов
- ✅ Валидация на старте приложения
- ✅ Понятные error messages
- ✅ Тесты покрывают invalid cases

**Файлы:**
- `models/config_schema.py` (новый)
- `utils/config.py`
- `tests/test_config_validation.py` (новый)

---

### Спринт 3: Качество и масштабируемость (5-7 дней)

**Цель:** Устранить технический долг, улучшить maintainability

#### CR-H2: Timezone-aware система
**Приоритет:** 🟡 Высокий
**Оценка:** 4 часа

**Проблема:**
- Статистика "сегодня" в UTC вместо локальной TZ
- `date('now')` в БД использует UTC
- Дайджест может сдвигаться на ±1 день

**Шаги:**
1. Использовать timezone-aware datetime везде
2. Применить TZ к APScheduler
3. Конвертировать timestamps в БД к UTC явно
4. Дайджест формировать с учётом TZ
5. Тест на границы суток (23:59 → 00:01)

**Критерии приёмки:**
- ✅ Все datetime objects timezone-aware
- ✅ Scheduler использует конфигурационную TZ
- ✅ БД хранит timestamps в UTC
- ✅ Тест на границы суток проходит

**Файлы:**
- `main.py`
- `database/db.py`
- `services/marketplace_processor.py`
- `services/status_reporter.py`
- `tests/test_timezone.py` (новый)

---

#### CR-H3: Хрупкость точки входа / DI layer
**Приоритет:** 🟢 Средний
**Оценка:** 5 часов

**Проблема:**
- main создаёт Database даже когда режимы сами создают подключения
- Дублирование YAML-чтения
- Нет централизованного управления зависимостями

**Шаги:**
1. Создать ServiceContainer (DI container)
2. Фабрики для Database, Config, GeminiClient
3. Refactor main.py: использовать container
4. Компоненты получают зависимости из container
5. Mock-friendly архитектура для тестов

**Критерии приёмки:**
- ✅ Единый ServiceContainer
- ✅ Нет прямого создания instances в main.py
- ✅ Легко подменять зависимости в тестах

**Файлы:**
- `core/container.py` (новый)
- `main.py`
- `tests/test_container.py` (новый)

---

#### CR-H5: Config cleanup
**Приоритет:** 🟢 Низкий
**Оценка:** 3 часа

**Проблема:**
- Неиспользуемые параметры: `listener.reconnect_timeout`, `listener.save_batch_size`
- Config читается многократно
- Несинхронизированная документация

**Шаги:**
1. Аудит всех параметров конфига
2. Удалить неиспользуемые параметры
3. Config singleton pattern
4. Синхронизировать README с актуальными параметрами
5. Inline комментарии в config.yaml

**Критерии приёмки:**
- ✅ Все параметры используются
- ✅ README актуален
- ✅ Config загружается один раз

**Файлы:**
- `config/base.yaml`
- `config/profiles/*.yaml`
- `README.md`
- `utils/config.py`

---

#### CR-C4: Реальная модерация Telegram
**Приоритет:** 🟡 Высокий
**Оценка:** 8 часов

**Проблема:**
- `moderate_posts`/`moderate_categories` возвращают входные данные/топ-10
- Ответы модератора не учитываются
- Модерация — заглушка с автоодобрением

**Источники:**
- `services/marketplace_processor.py:257-279`
- `services/marketplace_processor.py:410-444`

**Шаги:**
1. Добавить состояния в БД: `pending_moderation`, `approved`, `rejected`
2. Отправка дайджеста модератору в Telegram
3. Обработка ответов модератора:
   - Reply с номерами для удаления: "0,3,5"
   - Команды: "все", "отмена"
   - Callback buttons (inline keyboard)
4. Timeout модерации (авто-публикация через N часов)
5. Сохранение решений модератора в БД
6. E2E тест с mock Telegram API

**Критерии приёмки:**
- ✅ Дайджест отправляется модератору
- ✅ Обработка всех типов ответов
- ✅ Timeout работает
- ✅ Решения сохраняются в БД

**Файлы:**
- `services/marketplace_processor.py`
- `database/db.py`
- `tests/test_moderation.py` (новый)

---

#### CR-OPT: Оптимизации и чистка
**Приоритет:** 🟢 Низкий
**Оценка:** 5 часов

**Задачи:**
1. Logging унификация (настройка один раз в main)
2. LLM prompt templates (Jinja2)
3. Удаление мёртвого кода (GeminiSelector или интеграция)
4. Профилирование processor (identify bottlenecks)
5. Code style consistency (ruff, black)

**Критерии приёмки:**
- ✅ Logging настраивается один раз
- ✅ Промпты в Jinja2 templates (опционально)
- ✅ Нет неиспользуемого кода
- ✅ Профилирование выполнено

**Файлы:**
- `main.py`
- `utils/logger.py`
- `services/gemini_client.py`
- `config/prompts/templates/` (новая директория)

---

## ✅ Чек-листы активных шагов

### A1 — Проверка listener
- [ ] Listener запускается без ошибок
- [ ] Загружаются каналы (subscriptions или manual)
- [ ] Новые сообщения сохраняются в БД
- [ ] Heartbeat файл обновляется
- [ ] Логи без ошибок за 5 минут работы

### A2 — Проверка processor
- [ ] Processor загружает необработанные сообщения
- [ ] Gemini API отвечает корректно
- [ ] Embeddings генерируются
- [ ] Дубликаты отфильтровываются
- [ ] Дайджест формируется

### A3 — Проверка database
- [ ] WAL mode включен (`PRAGMA journal_mode`)
- [ ] Concurrent access работает без блокировок
- [ ] Cleanup старых данных работает
- [ ] Indexes существуют и используются
- [ ] Backup/restore процедуры работают

### B1 — Unit-тесты Database
- [ ] test_save_message
- [ ] test_get_unprocessed_messages
- [ ] test_mark_as_processed
- [ ] test_save_embedding
- [ ] test_get_published_embeddings
- [ ] test_cleanup_old_messages
- [ ] Coverage database/db.py > 80%

### B2 — Unit-тесты Gemini Client
- [ ] test_select_and_format_marketplace_news (mock)
- [ ] test_retry_on_api_error
- [ ] test_invalid_json_response
- [ ] test_pydantic_validation
- [ ] Coverage services/gemini_client.py > 70%

### B3 — Unit-тесты Embeddings
- [ ] test_encode_single
- [ ] test_encode_batch
- [ ] test_cosine_similarity
- [ ] test_check_duplicate
- [ ] Coverage services/embeddings.py > 80%

### C1 — Gemini retry logic
- [ ] tenacity retry добавлен
- [ ] exponential backoff настроен
- [ ] max_attempts = 3
- [ ] before_sleep logging
- [ ] тесты retry behavior

### C2 — Pydantic validation
- [ ] GeminiResponse model создан
- [ ] parse_obj используется
- [ ] ValidationError обрабатывается
- [ ] тесты с невалидными данными

### E1 — README обновление
- [ ] Описание проекта актуально
- [ ] Инструкции по установке
- [ ] Примеры использования
- [ ] Configuration guide
- [ ] Troubleshooting секция

### E3 — GitHub Actions CI/CD
- [ ] .github/workflows/ci.yml создан
- [ ] pytest запускается
- [ ] ruff/black проверки
- [ ] Coverage report
- [ ] Badge в README

---

## 📓 Журнал прогресса

| Дата/время | Этап | Партия | Статус | Комментарий |
|------------|------|--------|--------|-------------|
| 2025-10-14 19:00 | Init | FloodWait fix | ✅ | Применен safe_connect() во всех файлах, 0 проблемных вызовов |
| 2025-10-14 19:15 | Init | Документация | ✅ | Обновлены DOROZHNAYA_KARTA, memory-bank, создана операционная система |
| 2025-10-14 20:00 | Planning | Code Review | ✅ | Добавлены 3 спринта стабилизации на основе code review (11 задач) |
| 2025-10-14 20:15 | Sprint 1 | CR-C1 | ✅ | StatusReporter DI уже исправлен, обновлены тесты (2/2 passing) |
| 2025-10-14 21:00 | Sprint 1 | CR-C2 | ✅ | Отложенная пометка processed в process_marketplace и process_all_categories (54/54 tests, 92.78% coverage) |
| 2025-10-14 22:30 | Sprint 1 | CR-C3 | ✅ | SQLite lifecycle и concurrency (2 коммита: Part 1 context manager + Part 2 per-component db, 51/51 tests, 90% coverage) |
| 2025-10-14 23:00 | Sprint 1 | CR-C7 | ✅ | Adaptive scheduler с schedule.idle_seconds() и safety sleep (6/6 tests, 57/57 total, 90% coverage) |
| 2025-10-14 23:30 | Sprint 2 | CR-H1 | ✅ | Оптимизация чтения сообщений: кэш published_embeddings + base_messages, inline duplicate check (90 lines, 57/57 tests, 90% coverage, 2x+ ускорение) |
| 2025-10-15 00:30 | Sprint 2 | CR-C5 | ✅ | Batch embeddings и async дедупликация: 5 коммитов (Part 1-5), async wrappers + batch encoding + batch similarity + tests (63/63 tests, 90% coverage, 5-10x ускорение) |
| | | | | |

**Спринты стабилизации (Code Review):**

### Спринт 1: Критические блокеры
| Дата | Задача | Статус | Комментарий |
|------|--------|--------|-------------|
| 2025-10-14 | CR-C1 | ✅ | StatusReporter DI уже исправлен, тесты обновлены (connect() + bot_token) |
| 2025-10-14 | CR-C2 | ✅ | Отложенная пометка processed в process_marketplace и process_all_categories (2 коммита: Part 1 + Part 2) |
| 2025-10-14 | CR-C3 | ✅ | SQLite lifecycle и concurrency (Part 1: context manager + threading, Part 2: per-component db instances) |
| 2025-10-14 | CR-C7 | ✅ | Adaptive scheduler (schedule.idle_seconds() + safety sleep max 5s + edge cases + 6 tests) |

### Спринт 2: Высокий приоритет
| Дата | Задача | Статус | Комментарий |
|------|--------|--------|-------------|
| 2025-10-14 | CR-H1 | ✅ | Оптимизация чтения сообщений: кэш published_embeddings + base_messages, inline check (90 lines, 2x+ speedup) |
| 2025-10-15 | CR-C5 | ✅ | Batch embeddings и async дедупликация (5 коммитов: async wrappers, batch in filter_duplicates, batch in publish, batch similarity, tests + pytest-asyncio) |
| - | CR-C6 | ⏳ | Robust LLM (JSON validation, retry, chunking) - не начато |
| - | CR-H4 | ⏳ | Валидация конфигурации (Pydantic) - не начато |

### Спринт 3: Качество и масштабируемость
| Дата | Задача | Статус | Комментарий |
|------|--------|--------|-------------|
| - | CR-H2 | ⏳ | Timezone-aware система - не начато |
| - | CR-H3 | ⏳ | Хрупкость точки входа / DI layer - не начато |
| - | CR-H5 | ⏳ | Config cleanup - не начато |
| - | CR-C4 | ⏳ | Реальная модерация Telegram - не начато |
| - | CR-OPT | ⏳ | Оптимизации и чистка - не начато |

**Заполняется командой «Протокол, шаг …» после завершения подэтапа/партии.**

---

## 📌 Текущее состояние

- **Версия:** 1.5.0-dev
- **Последний коммит:** CR-C5 completed (batch embeddings + async, 63/63 tests, 90% coverage)
- **Текущий этап:** Спринт 2 - В процессе 🟡 (2/4 completed, 50%)
- **Следующая цель:** CR-C6 (Robust LLM - JSON validation, retry, chunking)
- **Блокеры:** Нет

**Готовность компонентов:**
- ✅ Listener — базовая функциональность работает, создает свой DB
- ✅ Processor — базовая функциональность работает, создает свой DB + оптимизация чтения (CR-H1)
- ✅ Embeddings — lazy loading + async wrappers + batch encoding + batch similarity (CR-C5)
- ✅ Database — SQLite с WAL mode + context manager + per-component instances
- ✅ Scheduler — adaptive idle через schedule.idle_seconds() + safety sleep
- ✅ FloodWait protection — safe_connect() применен
- ✅ Тесты — 63/63 passing, 90% coverage (+6 новых async/batch тестов)
- ⏳ CI/CD — не настроен
- ⏳ Monitoring — минимальный (healthcheck)

**Новые спринты (Code Review):**
- ✅ Спринт 1: 4 критических блокера ЗАВЕРШЕН (CR-C1 ✅, CR-C2 ✅, CR-C3 ✅, CR-C7 ✅)
- 🟡 Спринт 2: 4 высокоприоритетных задачи - 2/4 ЗАВЕРШЕНО (CR-H1 ✅, CR-C5 ✅, CR-C6 ⏳, CR-H4 ⏳)
- 🟢 Спринт 3: 5 задач качества/масштаба (CR-H2, CR-H3, CR-H5, CR-C4, CR-OPT)

---

## 🛠 Быстрый протокол

### Команда запуска сессии:

```
Протокол, шаг <код>
```

**Примеры:**
- `Протокол, шаг A1` — Проверка listener
- `Протокол, шаг B1` — Unit-тесты Database
- `Протокол, шаг C1` — Gemini retry logic

**Новые спринты (Code Review):**
- `Протокол, шаг CR-C1` — StatusReporter Database DI fix
- `Протокол, шаг CR-C2` — processed флаг для всех сообщений
- `Протокол, шаг CR-C3` — SQLite lifecycle и concurrency
- `Протокол, шаг CR-C7` — Adaptive scheduler

### Последовательность выполнения:

1. **Memory:** Просмотреть памятки в `memory-bank/`
   - `diff-limit-plan.md` — проверить безопасный размер партии
   - `verification-protocol.md` — чек-лист проверок
   - `rollback-protocol.md` — процедура отката при проблемах

2. **Roadmap:** Свериться с настоящим файлом
   - Найти текущий этап в таблице этапов A–E
   - Прочитать чек-лист для данного шага
   - Понять контрольные проверки

3. **Instruction:** Открыть `INSTRUKTSIYA_VYPOLNENIYA.md`
   - Найти детальные инструкции для шага
   - Следовать пошаговому плану

4. **Execute:** Выполнить задачу
   - Соблюдать diff-limit
   - Делать частые коммиты
   - Запускать тесты

5. **Update:** Обновить документы
   - Отметить в журнале прогресса
   - Обновить memory-bank если нужно
   - Сохранить логи в `logs/` (локально)

6. **Verify:** Проверить результат
   - Запустить verification protocol
   - `git diff --stat` — проверить размер
   - Smoke-тест если применимо

---

## 🔄 План отката / PR

**Последний стабильный коммит:**
Будет сохранен в `snapshot/baseline_commit.txt` после этапа A

**Rollback процедура:**
```bash
# При критичной проблеме
git checkout $(cat snapshot/baseline_commit.txt)

# Или по тегу
git checkout v1.0.0-stageA
```

**Проверки перед PR:**
- [ ] Все тесты проходят: `pytest -v`
- [ ] Линтеры проходят: `ruff check . && black --check .`
- [ ] Coverage > 70%: `pytest --cov`
- [ ] Smoke-тест end-to-end
- [ ] Документация обновлена
- [ ] Журнал прогресса заполнен
- [ ] Нет коммитов секретов/credentials

**Pull Request:**
- Создавать после завершения каждого этапа (A, B, C, D, E)
- Описывать: что сделано, какие проверки пройдены, следующие шаги
- Включать ссылку на journal entry
- Reviewer должен проверить через `verification-protocol.md`

---

## 📊 Метрики успеха проекта

**После завершения всех этапов:**

| Метрика | Цель | Текущее | Статус |
|---------|------|---------|--------|
| Test Coverage | > 70% | 0% | ⏳ |
| Tests passing | 100% | N/A | ⏳ |
| Listener uptime | > 99% | Unknown | ⏳ |
| Processor success rate | > 95% | Unknown | ⏳ |
| CI/CD pipeline | Green | None | ⏳ |
| Documentation | Complete | 60% | ⏳ |
| FloodWait incidents | 0 | 0 | ✅ |
| Production ready | Yes | No | ⏳ |

---

_Этот документ — **Single Source of Truth**: любые изменения дорожки, рисков или подхода вносятся сюда до начала работ._

**Дата последнего обновления:** 2025-10-14 20:00
**Версия документа:** 1.1.0 (добавлены спринты стабилизации из code review)
