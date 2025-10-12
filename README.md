# 🛒 Marketplace News Bot

**Version 2.1.0** | ✅ Production Ready

Автоматический агрегатор новостей про маркетплейсы Ozon и Wildberries из Telegram каналов.

## 🎯 Возможности

- **Автоматический сбор** новостей из 200+ Telegram каналов про маркетплейсы
- **AI-анализ через Gemini** - отбор самых важных новостей
- **Два независимых канала**: отдельно для Ozon и Wildberries
- **Проверка дубликатов** через embeddings
- **Модерация через Telegram** перед публикацией
- **Docker** для изоляции и удобного деплоя

---

## 📋 Требования

- Docker и Docker Compose
- Telegram аккаунт (ОТДЕЛЬНЫЙ, не тот же что для AI News Bot!)
- Google Gemini API key
- Два Telegram канала для публикации (Ozon и Wildberries)

---

## 🚀 Быстрый старт

### 1. Настройка переменных окружения

```bash
# Копируем пример
cp .env.example .env

# Редактируем .env
nano .env
```

Заполни переменные:

```env
TELEGRAM_API_ID=your_api_id           # https://my.telegram.org/apps
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+79XXXXXXXXX           # Номер ОТДЕЛЬНОГО аккаунта!

GEMINI_API_KEY=your_gemini_api_key    # https://makersuite.google.com/app/apikey

MY_PERSONAL_ACCOUNT=@your_username    # Куда отправлять модерацию

# Замени на свои каналы!
OZON_CHANNEL=@your_ozon_channel
WB_CHANNEL=@your_wb_channel
```

### 2. Настройка config.yaml

Отредактируй `config.yaml`:

```yaml
marketplaces:
  - name: "ozon"
    target_channel: "@your_ozon_channel"  # Замени на свой

  - name: "wildberries"
    target_channel: "@your_wb_channel"    # Замени на свой

channels:
  all_digest:
    target_channel: "@your_digest_channel"  # Опционально: общий дайджест
```

### 3. Первый запуск (настройка Telegram)

```bash
# Собираем образ (займёт 10-15 минут из-за torch)
docker-compose build

# Первый запуск для авторизации в Telegram
docker-compose run marketplace-listener python main.py listener
```

Введи код из Telegram для авторизации. После успешной авторизации нажми `Ctrl+C`.

### 4. Запуск в фоне

```bash
# Запускаем listener в фоне
docker-compose up -d marketplace-listener

# Проверяем логи
docker-compose logs -f marketplace-listener
```

### 5. Обработка новостей

```bash
# Запускаем processor вручную
docker-compose run --rm marketplace-processor python main.py processor

# Или добавь в cron (раз в день в 09:00)
0 9 * * * cd /root/marketplace-news-bot && docker-compose run --rm marketplace-processor python main.py processor
```

---

## 📁 Структура проекта

```
marketplace-news-bot/
├── config.yaml              # Главная конфигурация
├── .env                     # Секретные ключи (не коммитится)
├── docker-compose.yml       # Docker конфигурация
├── Dockerfile               # Docker образ
├── requirements.txt         # Python зависимости
├── main.py                  # Точка входа
│
├── database/
│   └── db.py               # Работа с SQLite
│
├── services/
│   ├── telegram_listener.py        # Слушатель каналов
│   ├── marketplace_processor.py    # Обработчик новостей
│   ├── gemini_client.py            # Клиент Gemini AI
│   └── embeddings.py               # Проверка дубликатов
│
├── utils/
│   ├── config.py           # Загрузка конфигурации
│   └── logger.py           # Логирование
│
├── data/                   # База данных (создаётся автоматически)
└── logs/                   # Логи (создаётся автоматически)
```

---

## 🔧 Режимы работы

### Listener (Слушатель)

Работает 24/7, собирает сообщения из всех подписанных каналов:

```bash
docker-compose up -d marketplace-listener
```

### Processor (Обработчик)

Запускается по расписанию (обычно раз в день):

```bash
docker-compose run --rm marketplace-processor python main.py processor
```

**Что делает Processor:**

1. Загружает сообщения за последние 24 часа
2. Фильтрует по ключевым словам (Ozon / Wildberries)
3. Проверяет на дубликаты через embeddings
4. Отбирает топ-10 через Gemini AI для каждого маркетплейса
5. Отправляет на модерацию в Telegram
6. Публикует одобренные новости в каналы

---

## 📊 Как работает отбор новостей

### Критерии для Ozon и Wildberries

**ВЫСОКИЙ ПРИОРИТЕТ (9-10)**

- Изменения в работе маркетплейса (комиссии, правила)
- Официальные обновления
- Важные новости для продавцов

**СРЕДНИЙ ПРИОРИТЕТ (7-8)**

- Кейсы успешных продавцов
- Новые инструменты и сервисы
- Тренды и аналитика

**НИЗКИЙ ПРИОРИТЕТ (5-6)**

- Общие советы
- Статистика рынка

**ИСКЛЮЧАЕТСЯ:**

- Реклама курсов и консультаций
- Мемы без пользы
- Новости про ДРУГИЕ маркетплейсы

---

## 🔄 Workflow

```
┌─────────────────────────────────────────┐
│   Listener (24/7 в Docker)              │
│   Собирает все сообщения из 200 каналов │
└──────────────┬──────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│   Database (SQLite)                      │
│   Хранит сырые сообщения                │
└──────────────┬───────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│   Processor (09:00 по крону)             │
│                                          │
│   1. Фильтр по keywords (Ozon/WB)       │
│   2. Проверка дубликатов (embeddings)   │
│   3. Gemini отбирает топ-10 для каждого │
│   4. Модерация через Telegram           │
│   5. Публикация в каналы                │
└──────────────┬───────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│   Публикация                             │
│   @ozon_channel  │  @wb_channel          │
└──────────────────────────────────────────┘
```

---

## 🐛 Troubleshooting

### Проблема: Docker сборка долго идёт

**Решение:** Это нормально! Torch занимает 2GB, сборка может занять 10-15 минут.

### Проблема: Session already running

**Решение:**

```bash
# Останови listener
docker-compose stop marketplace-listener

# Удали session файлы
rm data/*.session*

# Перезапусти
docker-compose up -d marketplace-listener
```

### Проблема: Database locked

**Решение:**

```bash
# Останови все контейнеры
docker-compose down

# Подожди 5 секунд
sleep 5

# Запусти заново
docker-compose up -d marketplace-listener
```

### Проблема: Gemini API ошибка

**Решение:**

1. Проверь API key в `.env`
2. Проверь квоту на <https://makersuite.google.com/>
3. Убедись что модель `gemini-2.0-flash-exp` доступна

---

## 📝 Настройка cron для автоматической обработки

```bash
# Открой crontab
crontab -e

# Добавь строку (обработка каждый день в 09:00)
0 9 * * * cd /root/marketplace-news-bot && docker-compose run --rm marketplace-processor python main.py processor >> /root/marketplace-news-bot/logs/cron.log 2>&1
```

---

## 🔐 Важно про безопасность

1. **Используй ОТДЕЛЬНЫЙ Telegram аккаунт** (не тот же что для AI News Bot)
2. **Не коммить .env файл** в Git (уже в .gitignore)
3. **Не делись session файлами** - они дают полный доступ к аккаунту
4. **Gemini API key** держи в секрете

---

## 📈 Мониторинг

### Проверка статуса

```bash
# Статус контейнеров
docker-compose ps

# Логи listener
docker-compose logs -f marketplace-listener

# Логи последнего processor
docker-compose logs marketplace-processor

# Проверка БД
sqlite3 data/marketplace_news.db "SELECT COUNT(*) FROM raw_messages"
```

### Полезные команды

```bash
# Проверить статус контейнеров (должен быть healthy)
docker-compose ps

# Перезапуск listener
docker-compose restart marketplace-listener

# Остановка всего
docker-compose down

# Очистка логов
> logs/bot.log

# Ребилд образа после изменений
docker-compose build --no-cache
```

### Ротация логов

- Файл `logs/bot.log` автоматически ротируется Python-хендлером (5×10 MB).
- Дополнительно можно запустить `logrotate` внутри контейнера:

```bash
docker exec marketplace-listener logrotate -f /app/docker/logrotate.conf
```

### Бэкапы базы

- Снимок: `./scripts/backup_db.sh` (или `docker exec marketplace-listener /app/scripts/backup_db.sh`)
- Восстановить: `./scripts/restore_db.sh <путь-к-бэкапу>`
- Подробный план: `docs/backup_runbook.md`

---

## 🛠 Разработка

- Установи dev-зависимости: `pip install -r requirements-dev.txt`
- Активируй хуки: `pre-commit install`
- Запускай проверку перед пушем: `pre-commit run --all-files`
- Автоисправление: `make lint-fix`

---

## 🆚 Отличия от AI News Bot

| Параметр | AI News Bot | Marketplace Bot |
|----------|-------------|-----------------|
| **Каналов** | 20 (AI) | 200 (маркетплейсы) |
| **Публикация** | 1 канал | 2 канала (Ozon, WB) |
| **Фильтрация** | Только AI | Keywords + AI |
| **Gemini промпт** | Про AI новости | Про маркетплейсы |
| **Docker** | Нет | Да |
| **Telegram аккаунт** | Основной | Отдельный |

---

## 🤝 Поддержка

Если возникли вопросы - проверь:

1. Логи: `docker-compose logs`
2. Config: `config.yaml` правильно заполнен?
3. .env: все ключи на месте?
4. Telegram: аккаунт авторизован?

---

## 📜 Лицензия

Проект для личного использования. Не забудь соблюдать Terms of Service Telegram и Google.

---

**Удачи в запуске! 🚀**
