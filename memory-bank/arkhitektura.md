# 🏗️ Архитектура: Telegram News Bot

**Дата:** 2025-10-14

---

## 📦 Основные компоненты

### 1. Listener (services/telegram_listener.py)

**Назначение:** Мониторинг Telegram каналов 24/7

**Основные функции:**
- Подключение к Telegram через Telethon (User API)
- Получение списка каналов (подписки или manual list)
- Прослушивание новых сообщений в реальном времени
- Фильтрация по длине и ключевым словам
- Сохранение в БД

**Запуск:**
```bash
python main.py listener
```

---

### 2. Processor (services/marketplace_processor.py)

**Назначение:** Обработка и публикация дайджестов

**Основные функции:**
- Загрузка необработанных сообщений из БД
- Фильтрация по категориям (Ozon, WB, общие)
- Проверка на дубликаты через embeddings
- Отбор топовых новостей через Gemini AI
- Формирование дайджеста
- Модерация (опционально)
- Публикация в Telegram каналы

**Запуск:**
```bash
python main.py processor
```

---

### 3. Database (database/db.py)

**Технология:** SQLite с WAL mode

**Таблицы:**
- `channels` - список отслеживаемых каналов
- `raw_messages` - все собранные сообщения
- `embeddings` - векторные представления для дедупликации
- `published_news` - опубликованные новости

**Особенности:**
- WAL mode для concurrent access
- Retry логика при блокировках
- Автоматическая очистка старых данных

---

### 4. Gemini Client (services/gemini_client.py)

**Назначение:** Работа с Google Gemini AI

**Основные методы:**
- `select_and_format_marketplace_news()` - отбор топ-N новостей
- `select_three_categories()` - разделение на категории

**Особенности:**
- Retry логика с exponential backoff
- Структурированный вывод (JSON)
- Валидация ответов

---

### 5. Embeddings (services/embeddings.py)

**Назначение:** Векторные представления текстов

**Модель:** SentenceTransformer (multilingual)

**Функции:**
- Генерация embeddings для текстов
- Batch processing для оптимизации
- Проверка на дубликаты через cosine similarity

---

## 🔄 Поток данных

```
1. Listener → Telegram каналы
   ↓
2. Новое сообщение → фильтрация → БД (raw_messages)
   ↓
3. Processor → загрузка необработанных
   ↓
4. Embeddings → проверка дубликатов
   ↓
5. Gemini AI → отбор топ-N новостей
   ↓
6. Формирование дайджеста
   ↓
7. Модерация (опционально)
   ↓
8. Публикация → Telegram канал
   ↓
9. Сохранение → published_news
```

---

## 🔐 Безопасность

### FloodWait Protection ✅

**Проблема:** Telegram блокирует при частых запросах авторизации

**Решение:**
- Использование `safe_connect()` вместо `client.start(phone=...)`
- Переиспользование существующей сессии
- Автоматическое ожидание при FloodWait

**Файл:** `utils/telegram_helpers.py`

---

### Session Management

**Правила:**
- Одна сессия на все компоненты
- Не создавать отдельные сессии (_status, _processor)
- Хранить .session файлы в `sessions/`
- Не коммитить .session файлы в git

---

## 📝 Конфигурация

### Структура:
```
config/
  ├── base.yaml          # Общие настройки
  └── profiles/          # Профили для разных доменов
      ├── marketplace.yaml
      ├── ai.yaml
      └── custom.yaml
```

### Загрузка:
```bash
python main.py --profile marketplace listener
```

### Приоритет:
1. Profile YAML (переопределяет)
2. Base YAML (значения по умолчанию)

---

## 🐳 Docker

**Контейнеры:**
- `tg-news-bot-listener` - непрерывный мониторинг
- `tg-news-bot-processor` - обработка по расписанию

**Volumes:**
- `./data/` - БД и данные
- `./sessions/` - Telegram сессии
- `./logs/` - логи

**Healthcheck:**
- Проверка heartbeat файла
- Restart policy: always (для listener)

---

## 🧪 Тестирование

**Структура:**
```
tests/
  ├── test_database.py        # БД операции
  ├── test_gemini_client.py   # Gemini интеграция
  ├── test_embeddings.py      # Векторные представления
  └── test_processor.py       # Обработка новостей
```

**Запуск:**
```bash
pytest tests/ -v
pytest tests/ --cov
```

---

## 📊 Метрики и мониторинг

**Логи:**
- `logs/bot.log` - основные события
- `logs/listener.heartbeat` - heartbeat listener
- Structured logging (JSON format)

**Healthcheck:**
- Проверка heartbeat файла каждые 60 секунд
- Максимальный возраст heartbeat: 180 секунд

**Status Reporter:**
- Отправка статистики в Telegram группу
- Запуск по расписанию
- Использование Bot API (для избежания конфликтов)

---

## 🔧 Технические решения

### Почему SQLite?
- Простота развертывания
- Достаточная производительность для < 10000 сообщений/день
- WAL mode обеспечивает concurrent access
- Легкое резервное копирование

### Почему Gemini?
- Качественный отбор новостей
- Структурированный вывод (JSON)
- Доступная цена
- Поддержка русского языка

### Почему профили?
- Один код для разных доменов
- Легкое добавление новых сценариев
- Переключение без изменения кода
- Простота тестирования

---

_Последнее обновление: 2025-10-14_
