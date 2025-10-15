# 📰 Universal News Digest Bot

**Версия 3.0** | ✅ Production Ready | 🌐 Универсальная платформа

Автоматический агрегатор новостей из Telegram-каналов с поддержкой **любых категорий**. Начиная с версии 3.0 бот полностью универсален: вы можете настроить его для маркетплейсов, AI, криптовалют, технологий или любой другой тематики через систему профилей.

## 🎯 Возможности

- **Универсальная система категорий** - настройте любые категории новостей (маркетплейсы, AI, крипто, tech и т.д.)
- **Профили конфигурации** - быстрое переключение между разными наборами настроек (marketplace, ai, generic)
- **Автоматический сбор** новостей из сотен Telegram каналов
- **AI-анализ через Gemini** - отбор самых важных новостей с учетом категорий
- **Гибкая публикация** - один или несколько каналов, настройка под каждую категорию
- **Проверка дубликатов** через embeddings
- **Модерация через Telegram** перед публикацией
- **Docker** для изоляции и удобного деплоя

---

## 📋 Требования

- Docker и Docker Compose
- Telegram аккаунт для сбора новостей
- Google Gemini API key
- Один или несколько Telegram каналов для публикации (в зависимости от профиля)

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
TELEGRAM_PHONE=+79XXXXXXXXX           # Номер Telegram аккаунта для сбора новостей

GEMINI_API_KEY=your_gemini_api_key    # https://makersuite.google.com/app/apikey

MY_PERSONAL_ACCOUNT=@your_username    # Куда отправлять сообщения модерации
MY_CHANNEL=@your_channel              # Канал для публикации (основной)

# Для профиля marketplace (опционально):
OZON_CHANNEL=@your_ozon_channel
WB_CHANNEL=@your_wb_channel
```

**Примечание:** Конкретные каналы настраиваются в профилях (`config/profiles/*.yaml`), переменные окружения используются как запасной вариант.

### 2. Настройка профилей конфигурации

Конфигурация разделена на базовую (`config/base.yaml`) и профили (`config/profiles/*.yaml`).

#### Доступные профили:

1. **marketplace** - Новости маркетплейсов (Ozon, Wildberries)
2. **ai** - Новости искусственного интеллекта
3. **generic** - Универсальный шаблон для любой категории

#### Структура конфигурации:

- `config/base.yaml` — общие параметры (пути, БД, публикация, расписание)
- `config/profiles/marketplace.yaml` — профиль для маркетплейсов
- `config/profiles/ai.yaml` — профиль для AI новостей
- `config/profiles/generic.yaml` — универсальный шаблон

#### Пример профиля с категориями (generic.yaml):

```yaml
profile: generic

publication:
  channel: "@your_news_channel"
  header_template: "📰 Главные новости за {date}"
  footer_template: "Подпишись на канал: https://t.me/your_news_channel"

# Универсальная система категорий (вместо marketplaces)
categories:
  - name: ai
    display_name: Artificial Intelligence
    enabled: true
    top_n: 10
    target_channel: "@your_news_channel"
    keywords:
      - ai
      - artificial intelligence
      - нейросеть
    exclude_keywords:
      - реклама

  - name: crypto
    display_name: Cryptocurrency
    enabled: true
    top_n: 10
    target_channel: "@your_news_channel"
    keywords:
      - crypto
      - bitcoin
      - ethereum

# Настройка комбинированного дайджеста
channels:
  all_digest:
    enabled: true
    target_channel: "@your_news_channel"
    category_counts:
      ai: 5
      crypto: 3
      tech: 2
```

**Примечание:** Старые профили используют `marketplaces:` вместо `categories:` - оба варианта поддерживаются для обратной совместимости.

### 3. Первый запуск (настройка Telegram)

```bash
# Собираем образ (займёт 10-15 минут из-за torch)
docker-compose build

# Первый запуск для авторизации в Telegram (с выбранным профилем)
# Для маркетплейсов:
docker-compose run marketplace-listener python main.py listener --profile marketplace

# Или для AI:
docker-compose run marketplace-listener python main.py listener --profile ai
```

Введи код из Telegram для авторизации. После успешной авторизации нажми `Ctrl+C`.

### 4. Запуск в фоне

```bash
# Запускаем listener в фоне
docker-compose up -d marketplace-listener

# Проверяем логи
docker-compose logs -f marketplace-listener
```

### 5. Обработка новостей с выбором профиля

Бот поддерживает запуск с разными профилями через параметр `--profile`:

```bash
# Профиль marketplace (маркетплейсы)
docker-compose run --rm marketplace-processor python main.py processor --profile marketplace

# Профиль ai (новости AI)
docker-compose run --rm marketplace-processor python main.py processor --profile ai

# Профиль generic (универсальный шаблон)
docker-compose run --rm marketplace-processor python main.py processor --profile generic

# Если профиль не указан, используется значение из config/base.yaml
docker-compose run --rm marketplace-processor python main.py processor
```

#### Настройка cron для автоматической обработки:

```bash
# Для маркетплейсов (каждый день в 09:00)
0 9 * * * cd /root/tg-news-bot && docker-compose run --rm marketplace-processor python main.py processor --profile marketplace >> logs/cron.log 2>&1

# Для AI новостей (каждый день в 06:00)
0 6 * * * cd /root/tg-news-bot && docker-compose run --rm marketplace-processor python main.py processor --profile ai >> logs/cron.log 2>&1
```

---

## 📁 Структура проекта

```
tg-news-bot/
├── config/
│   ├── base.yaml            # Общие настройки (пути, публикация, retry)
│   ├── profiles/
│   │   ├── marketplace.yaml # Профиль маркетплейсов (Ozon, Wildberries)
│   │   ├── ai.yaml          # Профиль AI-новостей
│   │   └── generic.yaml     # Универсальный шаблон
│   └── prompts/             # Промпты для Gemini AI
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
│   ├── news_processor.py           # Универсальный обработчик новостей
│   ├── gemini_client.py            # Клиент Gemini AI
│   ├── status_reporter.py          # Часовые статус-репорты
│   └── embeddings.py               # Проверка дубликатов
│
├── models/
│   ├── config_schemas.py           # Схемы конфигурации
│   └── category.py                 # Модели категорий
│
├── utils/
│   ├── config.py           # Загрузка конфигурации с профилями
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

Запускается по расписанию (обычно раз в день) или вручную:

```bash
# С указанием профиля
docker-compose run --rm marketplace-processor python main.py processor --profile marketplace

# Без профиля (используется из config/base.yaml)
docker-compose run --rm marketplace-processor python main.py processor
```

**Что делает Processor:**

1. Загружает сообщения за последние 24 часа из БД
2. Фильтрует по ключевым словам категорий (из профиля)
3. Проверяет на дубликаты через embeddings
4. Отбирает топ-N через Gemini AI для каждой категории
5. Отправляет на модерацию в Telegram (опционально)
6. Публикует одобренные новости в настроенные каналы

---

## 📊 Как работает отбор новостей

Бот использует AI (Gemini) для анализа и отбора новостей по каждой категории. Критерии отбора настраиваются через промпты в `config/prompts/`.

### Пример критериев для маркетплейсов (профиль marketplace)

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
- Нерелевантные новости

### Пример критериев для AI новостей (профиль ai)

**ВЫСОКИЙ ПРИОРИТЕТ**
- Релизы новых AI моделей
- Прорывы в исследованиях
- Важные обновления популярных инструментов

**СРЕДНИЙ ПРИОРИТЕТ**
- Практические кейсы применения
- Новые продукты и сервисы
- Аналитика и тренды

**ИСКЛЮЧАЕТСЯ:**
- Реклама курсов
- Мемы и развлекательный контент
- Низкокачественные новости

### Настройка своих критериев

Вы можете создать свой профиль в `config/profiles/` и настроить:
- Категории и ключевые слова
- Промпты для AI в `config/prompts/`
- Количество новостей для каждой категории

---

## 🔄 Workflow

```
┌─────────────────────────────────────────┐
│   Подписанные Telegram каналы           │
│   (количество зависит от профиля)       │
└──────────────┬──────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│   Listener (24/7 в Docker)               │
│   Собирает все сообщения из каналов     │
└──────────────┬───────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│   Database (SQLite)                      │
│   Хранит сырые сообщения                │
└──────────────┬───────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│   Processor (по расписанию/вручную)      │
│                                          │
│   1. Фильтр по keywords категорий       │
│   2. Проверка дубликатов (embeddings)   │
│   3. Gemini отбирает топ-N новостей     │
│   4. Модерация через Telegram           │
│   5. Публикация в каналы                │
└──────────────┬───────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│   Публикация в настроенные каналы        │
│   (один или несколько, зависит от        │
│    конфигурации категорий)              │
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

# Примеры для разных профилей:

# Маркетплейсы (каждый день в 09:00)
0 9 * * * cd /root/tg-news-bot && docker-compose run --rm marketplace-processor python main.py processor --profile marketplace >> /root/tg-news-bot/logs/cron.log 2>&1

# AI новости (каждый день в 06:00)
0 6 * * * cd /root/tg-news-bot && docker-compose run --rm marketplace-processor python main.py processor --profile ai >> /root/tg-news-bot/logs/cron.log 2>&1

# Универсальный профиль (каждый день в 10:00)
0 10 * * * cd /root/tg-news-bot && docker-compose run --rm marketplace-processor python main.py processor --profile generic >> /root/tg-news-bot/logs/cron.log 2>&1
```

---

## 🔐 Важно про безопасность

1. **Используй отдельный Telegram аккаунт** для каждого профиля (если запускаешь несколько)
2. **Не коммить .env файл** в Git (уже в .gitignore)
3. **Не делись session файлами** - они дают полный доступ к аккаунту
4. **Gemini API key** держи в секрете
5. **Session файлы изолированы по профилям** - каждый профиль использует свою сессию

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

# Проверка БД (пути зависят от профиля)
sqlite3 data/marketplace.db "SELECT COUNT(*) FROM raw_messages"  # marketplace профиль
sqlite3 data/ai.db "SELECT COUNT(*) FROM raw_messages"           # ai профиль
sqlite3 data/generic.db "SELECT COUNT(*) FROM raw_messages"      # generic профиль
```

### Полезные команды

```bash
# Проверить статус контейнеров (должен быть healthy)
docker-compose ps

# Перезапуск listener
docker-compose restart marketplace-listener

# Остановка всего
docker-compose down

# Очистка логов для конкретного профиля
> logs/marketplace/bot.log
> logs/ai/bot.log

# Ребилд образа после изменений
docker-compose build --no-cache
```


### Логи по профилям

Каждый профиль создает свои логи в отдельной директории:
- `logs/marketplace/` - логи профиля marketplace
- `logs/ai/` - логи профиля ai
- `logs/generic/` - логи профиля generic

Файлы автоматически ротируются Python-хендлером (5×10 MB).

Дополнительно можно запустить `logrotate` внутри контейнера:

```bash
docker exec marketplace-listener logrotate -f /app/docker/logrotate.conf
```

### Бэкапы базы

```bash
# Бэкап для конкретного профиля
./scripts/backup_db.sh data/marketplace.db
./scripts/backup_db.sh data/ai.db

# Восстановление
./scripts/restore_db.sh <путь-к-бэкапу>
```

Подробный план: `docs/backup_runbook.md`

---

## 🛠 Разработка

- Установи dev-зависимости: `pip install -r requirements-dev.txt`
- Активируй хуки: `pre-commit install`
- Запускай проверку перед пушем: `pre-commit run --all-files`
- Автоисправление: `make lint-fix`

---

## 🎨 Примеры использования

### Пример 1: Новости маркетплейсов

**Профиль:** `marketplace`
- Категории: Ozon, Wildberries
- Каналы: 200+ про маркетплейсы
- Публикация: 2 канала (отдельно для каждой категории)

### Пример 2: AI новости

**Профиль:** `ai`
- Категории: AI, машинное обучение
- Каналы: ~20 про искусственный интеллект
- Публикация: 1 общий канал

### Пример 3: Универсальный дайджест

**Профиль:** `generic`
- Категории: AI, крипто, технологии (настраивается)
- Каналы: любые по вашему выбору
- Публикация: 1 или несколько каналов

Создайте свой профиль в `config/profiles/your_profile.yaml` для любой тематики!

---

## 🔨 Создание собственного профиля

Хотите собирать новости по своей тематике? Вот как это сделать:

### Шаг 1: Создайте файл профиля

```bash
cp config/profiles/generic.yaml config/profiles/myprofile.yaml
```

### Шаг 2: Настройте категории

Отредактируйте `config/profiles/myprofile.yaml`:

```yaml
profile: myprofile

publication:
  channel: "@your_channel"
  header_template: "📰 Новости за {date}"

# Определите свои категории
categories:
  - name: gaming
    display_name: Gaming
    enabled: true
    top_n: 10
    target_channel: "@your_channel"
    keywords:
      - игры
      - gaming
      - playstation
      - xbox
    exclude_keywords:
      - реклама

  - name: movies
    display_name: Movies
    enabled: true
    top_n: 5
    keywords:
      - кино
      - фильм
      - movies
```

### Шаг 3: Запустите с новым профилем

```bash
# Listener
docker-compose run marketplace-listener python main.py listener --profile myprofile

# Processor
docker-compose run --rm marketplace-processor python main.py processor --profile myprofile
```

### Шаг 4: Настройте промпты (опционально)

Создайте кастомный промпт в `config/prompts/myprofile_select.md` и укажите его в конфиге.

---

## 🤝 Поддержка

Если возникли вопросы - проверь:

1. Логи: `docker-compose logs`
2. Config: `config/base.yaml` и профиль правильно заполнены?
3. .env: все ключи на месте?
4. Telegram: аккаунт авторизован для текущего профиля?
5. Профиль: правильный профиль указан при запуске (`--profile`)?

---

## 📜 Лицензия

Проект для личного использования. Не забудь соблюдать Terms of Service Telegram и Google.

---

**Удачи в запуске! 🚀**
