# 🎬 News-to-Reels Generator

> Автоматическая генерация сценариев Instagram Reels из новостей через Perplexity API

[![Status](https://img.shields.io/badge/status-production_ready-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.10+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()
[![Completed](https://img.shields.io/badge/completed-2025--10--20-success)]()

---

## 📋 Что это?

**News-to-Reels Generator** — модуль для TG News Bot, который автоматически превращает новости в готовые сценарии для 30-секундных Instagram Reels видео.

**✅ МОДУЛЬ ГОТОВ К ИСПОЛЬЗОВАНИЮ** (Production Ready, 2025-10-20)

### Основные возможности

- 📰 **Обогащение новостей** — дополнительный контекст, факты, предыстория через Perplexity AI
- 🎬 **Генерация сценариев** — структурированные скрипты с хронометражем (hook, content, CTA)
- 🔄 **Интеграция с ТНБ** — использует новости из базы данных TG News Bot
- 📲 **Модерация** — отправка сценариев в Telegram перед использованием
- ⚙️ **Гибкость** — настраиваемые промпты и параметры обработки

---

## 🚀 Быстрый старт

### Установка

```bash
# Перейти в корень проекта TG News Bot
cd /root/tg-news-bot

# Добавить Perplexity API ключ в .env
echo "PERPLEXITY_API_KEY=your_key_here" >> .env

# Установить зависимости (если еще не установлены)
pip install aiohttp tenacity
```

### Использование

```bash
# Ручной запуск
python main.py reels --profile reels

# Обработать только 5 новостей
python main.py reels --profile reels --limit 5

# Фильтр по категории
python main.py reels --profile reels --category ai
```

### Автоматический запуск

Добавьте в `config/profiles/reels.yaml`:

```yaml
reels_processor:
  auto_run_after_processor: true
```

Теперь после `python main.py processor` автоматически запустится reels generator.

---

## 📐 Архитектура

```
reels/
├── models/           # Модели данных (News, EnrichedNews, ReelsScenario)
├── services/         # Бизнес-логика (PerplexityClient, ReelsProcessor)
├── config/           # Конфигурация
├── prompts/          # Промпты для Perplexity API
└── tests/            # Unit и интеграционные тесты
```

### Workflow

```
1. Получение новостей из БД ТНБ
         ↓
2. Обогащение через Perplexity API
         ↓
3. Генерация сценария Reels
         ↓
4. Форматирование для Telegram
         ↓
5. Отправка на модерацию
```

---

## 🛠️ Конфигурация

### Переменные окружения

```bash
# .env
PERPLEXITY_API_KEY=your_key_here
MY_PERSONAL_ACCOUNT=@your_username
```

### Профиль конфигурации

```yaml
# config/profiles/reels.yaml
profile: reels

perplexity:
  model: sonar-pro
  timeout: 60
  max_retries: 3

reels_processor:
  news_limit: 10
  auto_run_after_processor: false

output:
  telegram:
    enabled: true
    channel: ${MY_PERSONAL_ACCOUNT}
```

---

## 📖 Документация

- **[PROJECT_DESCRIPTION.md](./PROJECT_DESCRIPTION.md)** — Полное описание проекта
- **[ROADMAP.md](./ROADMAP.md)** — Детальная дорожная карта разработки
- **[PROGRESS.md](./PROGRESS.md)** — Текущий прогресс и статус

---

## 💡 Примеры

### Базовое использование

```python
from reels.services.reels_processor import ReelsProcessor
from utils.config import load_config

# Инициализация
config = load_config("reels")
processor = ReelsProcessor(config)

# Обработка последних новостей
enriched_news, scenarios = await processor.process_latest_news(limit=5)

# Отправка на модерацию
await processor.send_to_moderation(scenarios)
```

### Кастомные промпты

Измените промпты в `reels/prompts/`:
- `enrich_news.md` — для обогащения новостей
- `generate_reels.md` — для генерации сценариев

---

## 🧪 Тестирование

```bash
# Запустить все тесты
pytest reels/tests/

# С покрытием
pytest reels/tests/ --cov=reels --cov-report=html

# Только unit-тесты
pytest reels/tests/ -k "not integration"
```

---

## 📊 Статус разработки

**Статус:** ✅ Production Ready (Завершено 2025-10-20)

| Этап | Статус | Прогресс |
|------|--------|----------|
| 0. Документация | ✅ | 100% |
| 1. Инфраструктура | ✅ | 100% |
| 2. Perplexity Client | ✅ | 100% |
| 3. Reels Processor | ✅ | 100% |
| 4. Интеграция main.py | ✅ | 100% |
| 5. Тестирование | ✅ | 100% |
| 6. Финализация | ✅ | 100% |

**Общий прогресс:** 100% ✅

См. подробности в [PROGRESS.md](./PROGRESS.md)

---

## 🔧 Технологии

- **Python** 3.10+
- **Perplexity API** (sonar-pro модель)
- **Pydantic** — валидация данных
- **aiohttp** — асинхронные HTTP запросы
- **tenacity** — retry логика
- **pytest** — тестирование

---

## 🤝 Участие в разработке

Проект находится на стадии разработки.

### Как помочь

1. Реализовать задачи из [ROADMAP.md](./ROADMAP.md)
2. Написать тесты
3. Улучшить промпты для Perplexity
4. Добавить новые форматы (YouTube Shorts, TikTok)

---

## 📄 Лицензия

MIT License - см. LICENSE файл

---

## 🔗 Ссылки

- **TG News Bot**: https://github.com/lifeexplorer230/tg-news-bot
- **Perplexity API**: https://docs.perplexity.ai/
- **Instagram Reels**: https://help.instagram.com/270447560766967

---

## 📞 Контакты

- **GitHub Issues**: https://github.com/lifeexplorer230/tg-news-bot/issues
- **Telegram**: @SoftStatustnb

---

**Создано с помощью Claude Code** 🤖

