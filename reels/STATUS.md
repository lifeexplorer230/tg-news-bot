# ✅ МОДУЛЬ REELS GENERATOR - ГОТОВ К ИСПОЛЬЗОВАНИЮ

**Дата завершения:** 2025-10-20
**Статус:** Production Ready
**Общий прогресс:** 100%

---

## 🎉 ЧТО РЕАЛИЗОВАНО

✅ **Полная интеграция с Perplexity API**
- Обогащение новостей дополнительным контекстом
- Retry логика с exponential backoff
- Парсинг JSON ответов с обработкой markdown

✅ **Генерация сценариев Instagram Reels**
- Hook (0-3 сек) - захватывающее начало
- Main Content (3-25 сек) - основной контент
- CTA (25-30 сек) - призыв к действию

✅ **Генерация video_prompts для Sora 2**
- 3 промпта для 30-секундного видео
- Детальные описания визуальных сцен
- Готовые к использованию в Sora 2

✅ **Интеграция с TG News Bot**
- Получение новостей из БД (таблица published)
- Использование конфигурации профилей
- Отправка на модерацию в Telegram

✅ **Валидация и типизация**
- Pydantic модели для всех данных
- Строгая валидация входных/выходных данных
- Type hints во всем коде

✅ **Документация**
- README.md с примерами использования
- PROJECT_DESCRIPTION.md - полное описание
- ROADMAP.md - дорожная карта разработки
- PROGRESS.md - отслеживание прогресса

---

## 🚀 КАК ИСПОЛЬЗОВАТЬ

### Быстрый старт

1. **Добавить API ключ в .env:**
   ```bash
   echo "PERPLEXITY_API_KEY=your_key_here" >> .env
   ```

2. **Убедиться что есть новости в БД:**
   ```bash
   # Должны быть опубликованные новости в профиле ai
   python main.py processor --profile ai
   ```

3. **Запустить генерацию сценариев:**
   ```bash
   python main.py reels --profile reels
   ```

### Тестовый запуск

```bash
# Использовать готовый тестовый скрипт
python test_reels_video_prompts.py
```

Результат сохраняется в `test_scenario_output.json`

---

## 📊 ТЕХНИЧЕСКИЕ ХАРАКТЕРИСТИКИ

| Параметр | Значение |
|----------|----------|
| Строк кода | ~1200 |
| Python файлов | 11 |
| Моделей данных | 6 |
| Сервисов | 2 |
| Промптов | 2 |
| API | Perplexity (sonar/sonar-pro) |
| Retry логика | 3 попытки с exp backoff |
| Timeout | 60 секунд |
| Валидация | Pydantic |

---

## 📁 СТРУКТУРА МОДУЛЯ

```
reels/
├── models/                    # Модели данных
│   ├── news.py               # News, EnrichedNews, Enrichment
│   └── reels.py              # ReelsScenario, Script
├── services/                  # Бизнес-логика
│   ├── perplexity_client.py  # Клиент Perplexity API
│   └── reels_processor.py    # Обработка новостей
├── config/                    # Конфигурация
│   └── reels_config.py       # Обертка для Config
├── prompts/                   # Промпты для Perplexity
│   ├── enrich_news.md        # Обогащение новостей
│   └── generate_reels.md     # Генерация сценариев
├── README.md                  # Документация
├── PROJECT_DESCRIPTION.md     # Полное описание
├── ROADMAP.md                 # Дорожная карта
└── PROGRESS.md                # Прогресс разработки
```

---

## 🎯 ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ

### Базовое использование

```python
from reels.services.reels_processor import ReelsProcessor
from utils.config import load_config

# Загрузить конфигурацию
config = load_config("reels")

# Создать процессор
processor = ReelsProcessor(config)

# Обработать последние новости
await processor.run()
```

### Обработка одной новости

```python
from reels.models.news import News
from reels.services.perplexity_client import PerplexityClient
from reels.config.reels_config import ReelsConfig

# Создать новость
news = News(
    id="001",
    title="GPT-5 анонсирован",
    summary="OpenAI представила GPT-5...",
    source="TechCrunch",
    published_date="2025-10-20T10:00:00"
)

# Обработать
config = ReelsConfig(load_config("reels"))
client = PerplexityClient(config)
enriched, scenario = await client.process_news_to_reels(news)

print(f"Сценарий: {scenario.title}")
print(f"Hook: {scenario.script.hook}")
print(f"Video prompts: {len(scenario.video_prompts)}")
```

---

## ⚙️ КОНФИГУРАЦИЯ

### config/profiles/reels.yaml

```yaml
profile: reels

perplexity:
  api_key: ${PERPLEXITY_API_KEY}
  model: sonar  # или sonar-pro
  timeout: 60
  max_retries: 3

reels_processor:
  news_limit: 10
  db_source:
    profile: ai        # Использовать БД из профиля ai
    table: published   # Таблица с новостями
    days_back: 1       # Брать за последний день

output:
  telegram:
    enabled: true
    channel: ${AI_MY_PERSONAL_ACCOUNT}
    format: detailed  # или compact
```

---

## 📝 ПРИМЕР ВЫВОДА

### Структура сценария

```json
{
  "news_id": "test_001",
  "title": "OpenAI анонсировала GPT-5",
  "duration": 30,
  "script": {
    "hook": "OpenAI шокировала мир: GPT-5 уже здесь!",
    "main_content": "OpenAI представила GPT-5...",
    "cta": "Сохрани и подписывайся!"
  },
  "hashtags": ["#GPT5", "#OpenAI", "#AI"],
  "video_prompts": [
    "Cinematic aerial view of futuristic cityscape...",
    "Close-up of microchips coming to life...",
    "Person coding on laptop..."
  ]
}
```

---

## 🔍 TROUBLESHOOTING

### Ошибка: "PERPLEXITY_API_KEY not found"

Добавьте API ключ в .env:
```bash
echo "PERPLEXITY_API_KEY=pplx-xxxxxxxx" >> .env
```

### Ошибка: "No news found in database"

Убедитесь что есть опубликованные новости:
```bash
python main.py processor --profile ai
```

### Ошибка: JSON parsing error

Модуль автоматически обрабатывает markdown блоки в JSON ответах.
Если ошибка сохраняется, проверьте логи.

---

## 📞 КОНТАКТЫ И ПОДДЕРЖКА

- **Документация:** [reels/README.md](README.md)
- **Issues:** https://github.com/lifeexplorer230/tg-news-bot/issues
- **Telegram:** @SoftStatustnb

---

## 🎓 ДОПОЛНИТЕЛЬНЫЕ РЕСУРСЫ

- [Perplexity API Docs](https://docs.perplexity.ai/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Instagram Reels Best Practices](https://help.instagram.com/270447560766967)
- [Sora 2 Prompting Guide](https://openai.com/sora)

---

**Создано с помощью Claude Code** 🤖
**Дата:** 2025-10-20
**Статус:** ✅ Production Ready
