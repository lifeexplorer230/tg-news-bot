# 🏗️ Архитектура проекта

## 📦 Компоненты

### 1. Listener (services/telegram_listener.py)

**Назначение**: 24/7 прослушивание Telegram каналов

**Ключевые классы**:

- `TelegramListener` - основной класс слушателя

**Поток работы**:

1. Подключается к Telegram через Telethon (User API)
2. Получает список всех диалогов (каналы пользователя)
3. Слушает новые сообщения через `client.on(events.NewMessage)`
4. Фильтрует по min_message_length
5. Сохраняет в БД через `db.save_message()`

**Database**: Собственное подключение (thread-safety)

**Запуск**: `docker-compose up -d marketplace-listener`

---

### 2. Processor (services/marketplace_processor.py)

**Назначение**: Обработка и публикация новостей

**Ключевые классы**:

- `MarketplaceProcessor` - основной процессор

**Поток работы**:

1. Загружает сообщения за последние 24 часа
2. Фильтрует по ключевым словам (Ozon / WB)
3. Проверяет дубликаты через embeddings
4. Отправляет в Gemini для отбора топ-10
5. Формирует дайджест (3 категории)
6. Отправляет на модерацию
7. Публикует одобренные новости

**Зависимости**:

- `GeminiClient` - отбор новостей
- `Embeddings` - проверка дубликатов
- `Database` - сохранение результатов

**Запуск**: `docker-compose run --rm marketplace-processor python main.py processor`

---

### 3. Database (database/db.py)

**Назначение**: Хранение и управление данными

**Таблицы**:

```sql
channels (id, username, title, is_active, last_checked)
raw_messages (id, channel_id, message_id, text, date, created_at, processed, gemini_score, rejection_reason)
published (id, text, embedding, published_at, source_message_id, source_channel_id)
```

**Ключевые методы**:

- `save_message()` - сохранить сырое сообщение
- `mark_as_processed()` - пометить обработанным с причиной
- `check_duplicate()` - проверка через cosine similarity
- `save_published()` - сохранить опубликованное
- `get_today_stats()` - статистика за день (в локальной timezone)
- `cleanup_old_data()` - очистка старых данных

**Особенности**:

- Хранит даты в UTC
- WAL mode для конкурентности
- timeout=30s для избежания блокировок
- Каждый компонент создаёт своё подключение

---

### 4. Gemini Client (services/gemini_client.py)

**Назначение**: Интеграция с Google Gemini API

**Ключевые методы**:

- `select_news()` - отбор топ-N новостей

**Промпт**:

- Критерии важности для маркетплейсов
- Исключение рекламы и курсов
- Валидация через Pydantic схему

**Retry логика**:

- 3 попытки через tenacity
- Exponential backoff
- Graceful fallback на пустой список

---

### 5. Embeddings (services/embeddings.py)

**Назначение**: Векторное представление текста

**Модель**: `paraphrase-multilingual-MiniLM-L12-v2`

- 384 измерения
- Поддержка русского языка
- Локально в ./models/

**Методы**:

- `encode()` - текст → вектор (384-dim)
- `similarity()` - cosine similarity между векторами

**Использование**:

- Проверка дубликатов (threshold 0.85)
- Сохранение embeddings опубликованного
- Поиск похожих новостей

---

### 6. Status Reporter (services/status_reporter.py)

**Назначение**: Автоматические отчёты в Telegram

**Особенности**:

- Использует Bot API (не User API!)
- Отправляет статистику каждые N минут
- Форматирует данные из get_today_stats()

**Конфигурация**:

```yaml
status:
  enabled: true
  bot_token: "..."  # От @BotFather
  chat: "Soft Status"
  interval_minutes: 60
```

**Запуск**: `python main.py all` (listener + status reporter вместе)

---

## 🔄 Поток данных

```
┌─────────────────────────────────────────┐
│  Telegram Channels (200+)               │
└──────────────┬──────────────────────────┘
               │
               ↓ NewMessage event
┌──────────────────────────────────────────┐
│  Listener                                │
│  - Фильтр по длине                      │
│  - Сохранение в БД                      │
└──────────────┬───────────────────────────┘
               │
               ↓ save_message()
┌──────────────────────────────────────────┐
│  Database (raw_messages)                 │
│  - channel_id, message_id, text, date   │
│  - processed=0 initially                │
└──────────────┬───────────────────────────┘
               │
               ↓ get_messages(24h)
┌──────────────────────────────────────────┐
│  Processor                               │
│  1. Filter by keywords (Ozon/WB)        │
│  2. Check duplicates (embeddings)       │
│  3. Gemini select top-10                │
│  4. Format digest (3 categories)        │
│  5. Moderation                          │
│  6. Publish to channels                 │
└──────────────┬───────────────────────────┘
               │
               ↓ save_published() + mark_as_processed()
┌──────────────────────────────────────────┐
│  Database (published + raw_messages)     │
│  - published: text, embedding           │
│  - raw_messages: processed=1, reason    │
└──────────────────────────────────────────┘
               │
               ↓ get_today_stats()
┌──────────────────────────────────────────┐
│  Status Reporter                         │
│  - Format stats                         │
│  - Send to Telegram group               │
└──────────────────────────────────────────┘
```

---

## 🧩 Зависимости между модулями

### Listener

```
TelegramListener
  ├── Database (own connection)
  ├── Config
  └── Logger
```

### Processor

```
MarketplaceProcessor
  ├── Database (own connection)
  ├── GeminiClient
  │     └── Config
  ├── Embeddings
  │     └── SentenceTransformer
  ├── TelegramClient (Telethon)
  └── Logger
```

### Status Reporter

```
StatusReporter
  ├── Database (own connection)
  ├── TelegramBot (aiogram с bot_token)
  ├── Config
  └── Logger
```

---

## 📊 Конфигурация (config.yaml)

### Секции

- **telegram**: session_name
- **gemini**: model, temperature, max_tokens
- **database**: path
- **listener**: reconnect_timeout, min_message_length
- **processor**: schedule_time, timezone, duplicate_threshold
- **embeddings**: model, local_path
- **marketplaces**: список маркетплейсов (name, target_channel, top_n, keywords, exclude_keywords)
- **moderation**: enabled, timeout_hours
- **cleanup**: raw_messages_days, published_days
- **status**: enabled, bot_token, chat, interval_minutes
- **logging**: level, format, file

### Загрузка

`utils/config.py` - класс `Config` с методом `get(key, default)`

---

## 🗄️ База данных

### Schema

```sql
-- Каналы источники
CREATE TABLE channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    title TEXT,
    is_active BOOLEAN DEFAULT 1,
    last_checked DATETIME
);

-- Сырые сообщения
CREATE TABLE raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    date DATETIME NOT NULL,          -- когда пришло (UTC)
    created_at DATETIME NOT NULL,    -- когда сохранено (UTC)
    processed BOOLEAN DEFAULT 0,
    gemini_score REAL,
    rejection_reason TEXT,           -- 'published', 'rejected_by_llm', 'rejected_by_keywords', 'is_duplicate'
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    UNIQUE(channel_id, message_id)
);

-- Опубликованные новости
CREATE TABLE published (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL,         -- numpy array 384-dim
    published_at DATETIME NOT NULL,  -- UTC
    source_message_id INTEGER,
    source_channel_id INTEGER
);
```

### Индексы

```sql
CREATE INDEX idx_raw_messages_date ON raw_messages(date);
CREATE INDEX idx_raw_messages_processed ON raw_messages(processed);
CREATE INDEX idx_published_date ON published(published_at);
```

---

## 🔧 Настройки SQLite

### Подключение

```python
self.conn = sqlite3.connect(
    self.db_path,
    timeout=30.0,           # Ждать до 30 сек при блокировке
    check_same_thread=False # Разрешить use из других threads
)
self.conn.execute('PRAGMA journal_mode=WAL')      # Write-Ahead Logging
self.conn.execute('PRAGMA busy_timeout=30000')    # Timeout в мс
```

### WAL (Write-Ahead Log)

- Позволяет одновременное чтение и запись
- Читатели не блокируют писателей
- Периодический checkpoint для merge

---

## 🕐 Timezone обработка

### Принцип

- **БД хранит UTC**: все DATETIME в UTC
- **Отображение в локальной timezone**: статистика, логи

### Методы

```python
def _now_local(self):
    """Текущее время в локальной timezone"""
    return datetime.now(self.tz)

def _to_db_datetime(self, dt: datetime) -> str:
    """Конвертация в UTC для БД"""
    if dt.tzinfo is None:
        dt = self.tz.localize(dt)
    return dt.astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')
```

### Примеры

```python
# Сохранение
local_time = datetime.now(tz)  # 2025-10-12 15:00:00 MSK
db_time = _to_db_datetime(local_time)  # '2025-10-12 12:00:00' UTC

# Чтение статистики
stats = get_today_stats()  # "сегодня" = начиная с 00:00 MSK
```

---

## 🧪 Тестирование

### Тестовые файлы

- `test_fixes.py` - A1, A2 (check_duplicate, rejection_reason)
- `test_concurrency.py` - A4 (SQLite concurrency)
- `test_timezone.py` - C9 (timezone handling)
- `test_database.py` - D1 (7 тестовых наборов)

### Принципы

- Использовать tempfile для изоляции
- In-memory SQLite где возможно
- Проверять edge cases
- Cleanup в finally блоке

---

## 🚀 Deployment

### Docker

```yaml
services:
  marketplace-listener:
    build: .
    command: python main.py listener
    volumes:
      - ./data:/app/data
    restart: unless-stopped
  
  marketplace-processor:
    build: .
    command: python main.py processor
    volumes:
      - ./data:/app/data
```

### Volumes

- `./data` - база данных, session файлы, модели
- `./logs` - логи бота

### Образ

- Base: python:3.10-slim
- Размер: ~2.5GB (из-за torch)
- Сборка: ~10-15 минут

---

**Последнее обновление**: 2025-10-12
**Версия**: 1.0
