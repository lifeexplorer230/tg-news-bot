# 🗺️ ДОРОЖНАЯ КАРТА: NEWS-TO-REELS GENERATOR

**Версия:** 1.0.0
**Дата начала:** 2025-10-20
**Ожидаемое завершение:** 2025-10-22 (11-17 часов разработки)
**Статус:** 🔨 In Progress

---

## 📌 КОНТЕКСТ И ЦЕЛИ

| Аспект | Описание |
|--------|----------|
| **Проект** | News-to-Reels Generator — модуль для TG News Bot |
| **Назначение** | Автоматическая генерация сценариев Instagram Reels из новостей через Perplexity API |
| **Интеграция** | Модульная структура (`reels/`), переиспользование инфраструктуры ТНБ |
| **Цель** | Production-ready модуль с coverage > 70%, полной документацией, готовый к использованию |

---

## 🎯 ОСНОВНЫЕ ЗАДАЧИ

1. **Инфраструктура модуля** — создание структуры папок, моделей данных, конфигурации
2. **Perplexity API клиент** — реализация взаимодействия с API, retry логика, валидация
3. **Процессор Reels** — обработка новостей, интеграция с БД ТНБ, Telegram модерация
4. **Интеграция в main.py** — добавление режима `reels`, авто-запуск после processor
5. **Тестирование** — unit-тесты, интеграционные тесты, coverage
6. **Документация** — README, примеры использования, API reference

---

## ⚖️ ПОДХОД К РАЗРАБОТКЕ

### Принципы

- **Модульность**: Слабая связанность с ТНБ, возможность выделения в отдельный проект
- **Малые партии**: Коммиты не более 300 строк, diff-limit контроль
- **Test-Driven**: Тесты пишутся параллельно с кодом
- **Переиспользование**: Максимальное использование инфраструктуры ТНБ

### Протокол работы

1. Для каждого этапа:
   - Обновление todo list (TodoWrite)
   - Реализация функционала
   - Написание тестов
   - Коммит с детальным описанием
   - Обновление PROGRESS.md

2. Критерии готовности этапа:
   - ✅ Код реализован
   - ✅ Тесты написаны и проходят
   - ✅ Документация обновлена
   - ✅ Code review пройден

---

## 🔢 ЭТАПЫ РАЗРАБОТКИ

### Обзор

| Код | Название | Время | Ключевые задачи | Критерии готовности |
|-----|----------|-------|-----------------|---------------------|
| **1** | Инфраструктура | 2-3 часа | Структура, модели, конфиг | Структура создана, модели валидируются |
| **2** | Perplexity Client | 2-3 часа | API клиент, retry, валидация | Успешные вызовы API, тесты проходят |
| **3** | Reels Processor | 3-4 часа | Обработка, БД, Telegram | End-to-end обработка работает |
| **4** | Интеграция main.py | 1-2 часа | Новый режим, авто-запуск | `python main.py reels` работает |
| **5** | Тестирование | 2-3 часа | Unit-тесты, integration | Coverage > 70% |
| **6** | Документация | 1-2 часа | README, примеры, API docs | Документация полная |

---

## 📋 ЭТАП 1: ПОДГОТОВКА ИНФРАСТРУКТУРЫ

**Время:** 2-3 часа
**Зависимости:** Нет

### Задачи

#### 1.1. Создать структуру папок (30 мин)

```bash
tg-news-bot/reels/
├── __init__.py
├── main.py
├── models/
│   ├── __init__.py
│   ├── news.py
│   └── reels.py
├── services/
│   ├── __init__.py
│   ├── perplexity_client.py
│   └── reels_processor.py
├── config/
│   ├── __init__.py
│   └── reels_config.py
├── prompts/
│   ├── enrich_news.md
│   └── generate_reels.md
└── tests/
    ├── __init__.py
    ├── test_perplexity_client.py
    └── test_reels_processor.py
```

**Файлы для создания:**
- `reels/__init__.py`
- `reels/main.py` (заглушка)
- Все `__init__.py` в подпапках

**Критерий готовности:**
- ✅ Все папки созданы
- ✅ Структура соответствует PROJECT_DESCRIPTION.md
- ✅ Import модуля работает: `from reels import main`

#### 1.2. Создать модели данных (60 мин)

**Файл:** `reels/models/news.py`

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class News(BaseModel):
    """Входная новость из БД ТНБ"""
    id: str
    title: str
    summary: str
    source: str
    url: Optional[str] = None
    published_date: str
    category: Optional[str] = None

class Enrichment(BaseModel):
    """Обогащение от Perplexity"""
    additional_context: str
    key_facts: List[str] = Field(min_length=3, max_length=10)
    background: str
    implications: str
    related_topics: List[str]

class ProcessingMetadata(BaseModel):
    """Метаданные обработки"""
    processed_at: str
    tokens_used: int
    model: str

class EnrichedNews(BaseModel):
    """Новость обогащенная через Perplexity"""
    # Базовые поля
    id: str
    title: str
    summary: str
    source: str

    # Обогащение
    enrichment: Enrichment
    processing_metadata: ProcessingMetadata
```

**Файл:** `reels/models/reels.py`

```python
from pydantic import BaseModel, Field
from typing import List

class Script(BaseModel):
    """Структура сценария"""
    hook: str = Field(..., description="0-3 сек: Захватывающее начало")
    main_content: str = Field(..., description="3-25 сек: Основной контент")
    cta: str = Field(..., description="25-30 сек: Call-to-action")

class ReelsScenario(BaseModel):
    """Сценарий для Instagram Reels"""
    news_id: str
    title: str
    duration: int = 30

    # Сценарий
    script: Script

    # Дополнительные рекомендации
    visual_suggestions: List[str] = Field(min_length=3)
    hashtags: List[str] = Field(min_length=5, max_length=10)
    music_mood: str
    target_audience: str
```

**Критерий готовности:**
- ✅ Модели валидируются с корректными данными
- ✅ Модели отклоняют некорректные данные
- ✅ Тесты для моделей проходят

#### 1.3. Настроить конфигурацию (30 мин)

**Файл:** `.env` (добавить)

```bash
# Perplexity API
PERPLEXITY_API_KEY=your_key_here
```

**Файл:** `config/profiles/reels.yaml`

```yaml
profile: reels

perplexity:
  api_key: ${PERPLEXITY_API_KEY}
  model: sonar-pro
  timeout: 60
  max_retries: 3
  base_url: https://api.perplexity.ai

reels_processor:
  source: database
  news_limit: 10
  filter_by_category: []

  prompts:
    enrich_news: reels/prompts/enrich_news.md
    generate_reels: reels/prompts/generate_reels.md

  auto_run_after_processor: false

output:
  telegram:
    enabled: true
    channel: ${MY_PERSONAL_ACCOUNT}
    format: detailed
  file:
    enabled: false

logging:
  level: INFO
  log_tokens: true
```

**Файл:** `reels/config/reels_config.py`

```python
from utils.config import Config

class ReelsConfig:
    """Обертка для конфигурации Reels модуля"""

    def __init__(self, config: Config):
        self.config = config

    @property
    def perplexity_api_key(self) -> str:
        return self.config.get("perplexity.api_key")

    @property
    def perplexity_model(self) -> str:
        return self.config.get("perplexity.model", "sonar-pro")

    # ... и т.д.
```

**Критерий готовности:**
- ✅ Профиль загружается: `Config("reels")`
- ✅ Переменные окружения подставляются
- ✅ ReelsConfig корректно читает настройки

#### 1.4. Создать промпты (30 мин)

**Файл:** `reels/prompts/enrich_news.md`

```markdown
# Промпт для обогащения новости

Ты эксперт-журналист. Изучи следующую новость и предоставь детальный анализ.

## НОВОСТЬ

**Заголовок:** {title}
**Краткое описание:** {summary}
**Источник:** {source}
{url}

## ТВОЯ ЗАДАЧА

1. Найди дополнительную информацию и контекст по этой теме
2. Выдели 5-7 самых важных ключевых фактов
3. Объясни предысторию события (что привело к этому)
4. Опиши возможные последствия и влияние
5. Укажи 3-5 связанных тем для дальнейшего изучения

## ФОРМАТ ОТВЕТА

Ответь СТРОГО в формате JSON:

{
  "additional_context": "Детальный контекст события...",
  "key_facts": [
    "Факт 1",
    "Факт 2",
    "Факт 3",
    "..."
  ],
  "background": "Предыстория события...",
  "implications": "Возможные последствия...",
  "related_topics": ["Тема 1", "Тема 2", "..."]
}

ВАЖНО: Ответ должен быть ТОЛЬКО JSON, без дополнительного текста.
```

**Файл:** `reels/prompts/generate_reels.md`

```markdown
# Промпт для генерации сценария Reels

Ты креатор вирусного контента для Instagram Reels. Твоя задача — создать сценарий для 30-секундного видео на основе новости.

## ОБОГАЩЕННАЯ НОВОСТЬ

{enriched_news_json}

## ТРЕБОВАНИЯ К СЦЕНАРИЮ

**Длительность:** Ровно 30 секунд

**Структура:**
1. **Hook (0-3 сек):** Захватывающее начало, которое остановит скролл
   - Используй интригу, шокирующий факт или вопрос
   - Максимум 10-15 слов

2. **Main Content (3-25 сек):** Суть новости с самыми интересными фактами
   - Структурированная подача
   - Динамичное повествование
   - 80-100 слов

3. **CTA (25-30 сек):** Призыв к действию
   - Комментарий, сохранение, подписка
   - 10-15 слов

**Дополнительно:**
- 5-7 визуальных предложений (что показывать на экране)
- 5-7 релевантных хэштегов
- Настроение музыки (энергичная/спокойная/драматичная/мотивирующая)
- Описание целевой аудитории

## ФОРМАТ ОТВЕТА

Ответь СТРОГО в формате JSON:

{
  "hook": "Захватывающий hook...",
  "main_content": "Основной контент...",
  "cta": "Призыв к действию...",
  "visual_suggestions": [
    "Визуал 1",
    "Визуал 2",
    "..."
  ],
  "hashtags": ["#хэштег1", "#хэштег2", "..."],
  "music_mood": "энергичная",
  "target_audience": "Описание ЦА"
}

ВАЖНО: Ответ должен быть ТОЛЬКО JSON, без markdown блоков или дополнительного текста.
```

**Критерий готовности:**
- ✅ Промпты созданы
- ✅ Переменные в промптах корректны ({title}, {enriched_news_json})
- ✅ Промпты читаются через `Path().read_text()`

### Итоговые критерии Этапа 1

- ✅ Структура папок создана
- ✅ Модели данных реализованы и протестированы
- ✅ Конфигурация настроена и загружается
- ✅ Промпты созданы
- ✅ Базовые unit-тесты проходят
- ✅ Коммит: "feat(reels): Этап 1 — Инфраструктура модуля"

---

## 📋 ЭТАП 2: PERPLEXITY API КЛИЕНТ

**Время:** 2-3 часа
**Зависимости:** Этап 1

### Задачи

#### 2.1. Реализовать базовый клиент (60 мин)

**Файл:** `reels/services/perplexity_client.py`

```python
import json
import logging
from pathlib import Path
from typing import Dict, Any

import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from reels.models.news import News, EnrichedNews, Enrichment, ProcessingMetadata
from reels.models.reels import ReelsScenario, Script
from reels.config.reels_config import ReelsConfig

logger = logging.getLogger(__name__)

class PerplexityClient:
    """Клиент для взаимодействия с Perplexity API"""

    def __init__(self, config: ReelsConfig):
        self.config = config
        self.api_key = config.perplexity_api_key
        self.model = config.perplexity_model
        self.base_url = "https://api.perplexity.ai"
        self.timeout = config.config.get("perplexity.timeout", 60)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError))
    )
    async def _make_request(self, messages: list[dict]) -> dict:
        """Выполнить запрос к Perplexity API с retry логикой"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                response.raise_for_status()
                data = await response.json()
                logger.info(f"Perplexity API успешно вызван, токены: {data.get('usage', {})}")
                return data

    def _load_prompt(self, prompt_key: str) -> str:
        """Загрузить промпт из файла"""
        prompt_path = self.config.config.get(f"reels_processor.prompts.{prompt_key}")
        return Path(prompt_path).read_text(encoding='utf-8')

    def _build_prompt(self, template: str, context: dict) -> str:
        """Подставить переменные в промпт"""
        return template.format(**context)

    async def enrich_news(self, news: News) -> EnrichedNews:
        """Обогатить новость дополнительными деталями"""
        # Загрузить промпт
        template = self._load_prompt("enrich_news")

        # Подставить данные новости
        context = {
            "title": news.title,
            "summary": news.summary,
            "source": news.source,
            "url": f"**URL:** {news.url}" if news.url else ""
        }
        prompt = self._build_prompt(template, context)

        # Вызвать API
        messages = [{"role": "user", "content": prompt}]
        response = await self._make_request(messages)

        # Извлечь и парсить ответ
        content = response['choices'][0]['message']['content']
        enrichment_data = self._parse_json_response(content)

        # Валидировать через Pydantic
        enrichment = Enrichment(**enrichment_data)

        # Собрать метаданные
        metadata = ProcessingMetadata(
            processed_at=datetime.utcnow().isoformat(),
            tokens_used=response['usage']['total_tokens'],
            model=self.model
        )

        return EnrichedNews(
            id=news.id,
            title=news.title,
            summary=news.summary,
            source=news.source,
            enrichment=enrichment,
            processing_metadata=metadata
        )

    async def generate_reels_scenario(self, enriched_news: EnrichedNews) -> ReelsScenario:
        """Сгенерировать сценарий Reels"""
        # Загрузить промпт
        template = self._load_prompt("generate_reels")

        # Подготовить контекст
        enriched_json = enriched_news.model_dump_json(indent=2)
        prompt = self._build_prompt(template, {"enriched_news_json": enriched_json})

        # Вызвать API
        messages = [{"role": "user", "content": prompt}]
        response = await self._make_request(messages)

        # Парсить ответ
        content = response['choices'][0]['message']['content']
        scenario_data = self._parse_json_response(content)

        # Валидировать
        script = Script(
            hook=scenario_data['hook'],
            main_content=scenario_data['main_content'],
            cta=scenario_data['cta']
        )

        return ReelsScenario(
            news_id=enriched_news.id,
            title=enriched_news.title,
            duration=30,
            script=script,
            visual_suggestions=scenario_data['visual_suggestions'],
            hashtags=scenario_data['hashtags'],
            music_mood=scenario_data['music_mood'],
            target_audience=scenario_data['target_audience']
        )

    def _parse_json_response(self, content: str) -> dict:
        """Парсить JSON из ответа (может быть в markdown блоке)"""
        # Убрать markdown блоки если есть
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}\nContent: {content}")
            raise ValueError(f"Perplexity вернул некорректный JSON: {e}")
```

**Критерий готовности:**
- ✅ Базовый клиент реализован
- ✅ Retry логика работает
- ✅ JSON парсинг корректен

#### 2.2. Добавить rate limiting (30 мин)

```python
from utils.rate_limiter import RateLimiter

class PerplexityClient:
    def __init__(self, config: ReelsConfig):
        # ... существующий код

        # Rate limiter: 60 запросов в минуту (условно)
        self._rate_limiter = RateLimiter(max_requests=60, per_seconds=60)

    async def _make_request(self, messages: list[dict]) -> dict:
        # Ждем разрешения от rate limiter
        await self._rate_limiter.acquire()

        # ... существующий код запроса
```

#### 2.3. Написать unit-тесты (60 мин)

**Файл:** `reels/tests/test_perplexity_client.py`

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from reels.services.perplexity_client import PerplexityClient
from reels.models.news import News

@pytest.fixture
def mock_config():
    """Мок конфигурации"""
    config = MagicMock()
    config.perplexity_api_key = "test_key"
    config.perplexity_model = "sonar-pro"
    config.config.get.side_effect = lambda key, default=None: {
        "perplexity.timeout": 60,
        "reels_processor.prompts.enrich_news": "reels/prompts/enrich_news.md",
        "reels_processor.prompts.generate_reels": "reels/prompts/generate_reels.md"
    }.get(key, default)
    return config

@pytest.fixture
def sample_news():
    """Тестовая новость"""
    return News(
        id="test_001",
        title="Новая AI модель от OpenAI",
        summary="Представлена GPT-5...",
        source="TechCrunch",
        published_date="2025-10-20T10:00:00Z"
    )

@pytest.mark.asyncio
async def test_enrich_news_success(mock_config, sample_news):
    """Тест успешного обогащения новости"""
    client = PerplexityClient(mock_config)

    # Мок API ответа
    mock_response = {
        'choices': [{
            'message': {
                'content': '''
                {
                    "additional_context": "Контекст...",
                    "key_facts": ["Факт 1", "Факт 2", "Факт 3"],
                    "background": "Предыстория...",
                    "implications": "Последствия...",
                    "related_topics": ["AI", "GPT"]
                }
                '''
            }
        }],
        'usage': {'total_tokens': 500}
    }

    with patch.object(client, '_make_request', new=AsyncMock(return_value=mock_response)):
        enriched = await client.enrich_news(sample_news)

        assert enriched.id == sample_news.id
        assert enriched.title == sample_news.title
        assert len(enriched.enrichment.key_facts) == 3
        assert enriched.processing_metadata.tokens_used == 500

@pytest.mark.asyncio
async def test_enrich_news_invalid_json(mock_config, sample_news):
    """Тест обработки невалидного JSON"""
    client = PerplexityClient(mock_config)

    mock_response = {
        'choices': [{'message': {'content': 'invalid json'}}],
        'usage': {'total_tokens': 100}
    }

    with patch.object(client, '_make_request', new=AsyncMock(return_value=mock_response)):
        with pytest.raises(ValueError, match="некорректный JSON"):
            await client.enrich_news(sample_news)

# ... больше тестов
```

**Критерий готовности:**
- ✅ Тесты для `enrich_news()` проходят
- ✅ Тесты для `generate_reels_scenario()` проходят
- ✅ Тесты для error handling проходят
- ✅ Coverage `perplexity_client.py` > 80%

### Итоговые критерии Этапа 2

- ✅ PerplexityClient реализован
- ✅ Retry логика работает
- ✅ Rate limiting добавлен
- ✅ JSON parsing корректен
- ✅ Unit-тесты покрывают > 80%
- ✅ Коммит: "feat(reels): Этап 2 — Perplexity API клиент"

---

## 📋 ЭТАП 3: REELS PROCESSOR

**Время:** 3-4 часа
**Зависимости:** Этапы 1, 2

### Задачи

#### 3.1. Реализовать базовый процессор (90 мин)

**Файл:** `reels/services/reels_processor.py`

```python
import asyncio
import logging
from typing import List, Tuple, Optional

from database.db import Database
from reels.models.news import News, EnrichedNews
from reels.models.reels import ReelsScenario
from reels.services.perplexity_client import PerplexityClient
from reels.config.reels_config import ReelsConfig
from utils.config import Config

logger = logging.getLogger(__name__)

class ReelsProcessor:
    """Процессор для генерации Reels сценариев из новостей"""

    def __init__(self, config: Config):
        self.config = config
        self.reels_config = ReelsConfig(config)
        self.db = Database(config.db_path)
        self.perplexity_client = PerplexityClient(self.reels_config)

    async def process_latest_news(
        self,
        limit: int = 10,
        category: Optional[str] = None
    ) -> Tuple[List[EnrichedNews], List[ReelsScenario]]:
        """
        Обработать последние новости из БД

        Args:
            limit: Количество новостей для обработки
            category: Фильтр по категории (опционально)

        Returns:
            Кортеж (обогащенные новости, сценарии Reels)
        """
        logger.info(f"Начало обработки последних {limit} новостей")

        # Получить новости из БД ТНБ
        news_list = await self._fetch_news_from_db(limit, category)
        logger.info(f"Получено {len(news_list)} новостей из БД")

        enriched_news = []
        scenarios = []

        # Обработать каждую новость
        for news in news_list:
            try:
                enriched, scenario = await self.process_single_news(news)
                enriched_news.append(enriched)
                scenarios.append(scenario)
                logger.info(f"✅ Обработана новость: {news.id}")
            except Exception as e:
                logger.error(f"❌ Ошибка обработки новости {news.id}: {e}", exc_info=True)
                continue

        logger.info(f"Обработка завершена. Успешно: {len(scenarios)}/{len(news_list)}")
        return enriched_news, scenarios

    async def process_single_news(self, news: News) -> Tuple[EnrichedNews, ReelsScenario]:
        """
        Обработать одну новость

        Returns:
            Кортеж (обогащенная новость, сценарий Reels)
        """
        # Шаг 1: Обогатить новость через Perplexity
        logger.debug(f"Обогащение новости: {news.title}")
        enriched = await self.perplexity_client.enrich_news(news)

        # Шаг 2: Сгенерировать сценарий Reels
        logger.debug(f"Генерация сценария Reels для: {news.title}")
        scenario = await self.perplexity_client.generate_reels_scenario(enriched)

        return enriched, scenario

    async def _fetch_news_from_db(
        self,
        limit: int,
        category: Optional[str]
    ) -> List[News]:
        """Получить новости из БД ТНБ"""
        # Получить опубликованные новости за последний день
        query = """
            SELECT id, title, content as summary, channel as source, created_at as published_date
            FROM published
            WHERE date(created_at) = date('now')
            ORDER BY created_at DESC
            LIMIT ?
        """

        rows = self.db.execute_query(query, (limit,))

        news_list = []
        for row in rows:
            news = News(
                id=str(row[0]),
                title=row[1],
                summary=row[2][:500],  # Ограничить summary
                source=row[3],
                published_date=row[4],
                category=category
            )
            news_list.append(news)

        return news_list

    def format_for_telegram(self, scenario: ReelsScenario) -> str:
        """Форматировать сценарий для отправки в Telegram"""
        formatted = f"""
🎬 **СЦЕНАРИЙ REELS: {scenario.title}**

📝 **ID новости:** {scenario.news_id}
⏱️ **Длительность:** {scenario.duration} секунд

---

**🎯 HOOK (0-3 сек):**
{scenario.script.hook}

**📢 MAIN CONTENT (3-25 сек):**
{scenario.script.main_content}

**👉 CTA (25-30 сек):**
{scenario.script.cta}

---

**🎨 ВИЗУАЛЬНЫЕ ПРЕДЛОЖЕНИЯ:**
{self._format_list(scenario.visual_suggestions)}

**#️⃣ ХЭШТЕГИ:**
{' '.join(scenario.hashtags)}

**🎵 НАСТРОЕНИЕ МУЗЫКИ:** {scenario.music_mood}

**👥 ЦЕЛЕВАЯ АУДИТОРИЯ:** {scenario.target_audience}
"""
        return formatted.strip()

    def _format_list(self, items: List[str]) -> str:
        """Форматировать список с буллетами"""
        return '\n'.join(f"• {item}" for item in items)

    async def send_to_moderation(self, scenarios: List[ReelsScenario]):
        """Отправить сценарии в Telegram для модерации"""
        if not self.config.get("output.telegram.enabled", True):
            logger.info("Отправка в Telegram отключена")
            return

        channel = self.config.get("output.telegram.channel")
        if not channel:
            logger.warning("Telegram канал не настроен")
            return

        logger.info(f"Отправка {len(scenarios)} сценариев в {channel}")

        # TODO: Реализовать через TelegramClient из ТНБ
        # Временно: просто логируем
        for scenario in scenarios:
            formatted = self.format_for_telegram(scenario)
            logger.info(f"Отправка сценария:\n{formatted}")
            # await telegram_client.send_message(channel, formatted)
```

**Критерий готовности:**
- ✅ Базовый процессор работает
- ✅ Получение новостей из БД работает
- ✅ Форматирование для Telegram корректно

#### 3.2. Интеграция с Telegram (60 мин)

Добавить реальную отправку в Telegram используя инфраструктуру ТНБ.

```python
from services.telegram_listener import TelegramListener
from telethon import TelegramClient

class ReelsProcessor:
    async def send_to_moderation(self, scenarios: List[ReelsScenario]):
        """Отправить сценарии в Telegram для модерации"""
        # ... проверки

        # Использовать существующий TelegramClient из ТНБ
        async with TelegramClient(
            self.config.session_file,
            self.config.api_id,
            self.config.api_hash
        ) as client:
            for scenario in scenarios:
                formatted = self.format_for_telegram(scenario)
                await client.send_message(channel, formatted)
                logger.info(f"✅ Отправлен сценарий для новости {scenario.news_id}")
                await asyncio.sleep(1)  # Rate limiting
```

#### 3.3. Написать тесты (60 мин)

**Файл:** `reels/tests/test_reels_processor.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from reels.services.reels_processor import ReelsProcessor
from reels.models.news import News, EnrichedNews, Enrichment, ProcessingMetadata
from reels.models.reels import ReelsScenario, Script

# ... фикстуры

@pytest.mark.asyncio
async def test_process_single_news():
    """Тест обработки одной новости"""
    # ... реализация

@pytest.mark.asyncio
async def test_process_latest_news():
    """Тест batch обработки"""
    # ... реализация

@pytest.mark.asyncio
async def test_format_for_telegram():
    """Тест форматирования для Telegram"""
    # ... реализация
```

### Итоговые критерии Этапа 3

- ✅ ReelsProcessor реализован
- ✅ Интеграция с БД ТНБ работает
- ✅ Telegram отправка работает
- ✅ Unit-тесты покрывают > 70%
- ✅ Коммит: "feat(reels): Этап 3 — Reels Processor"

---

## 📋 ЭТАП 4: ИНТЕГРАЦИЯ В MAIN.PY

**Время:** 1-2 часа
**Зависимости:** Этапы 1-3

### Задачи

#### 4.1. Добавить режим "reels" (45 мин)

**Файл:** `main.py` (изменения)

```python
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TG News Bot")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["listener", "processor", "reels", "all"],  # ← ДОБАВИТЬ
        default="all",
        help="Режим работы бота",
    )
    # ... остальное
```

```python
async def run_reels_mode(config: Config | None = None):
    """Запуск Reels Generator (генерация сценариев из новостей)"""
    config = config or get_container().config
    configure_logging(config)

    logger.info("=" * 80)
    logger.info("🎬 ЗАПУСК REELS GENERATOR")
    logger.info("=" * 80)

    from reels.services.reels_processor import ReelsProcessor

    processor = ReelsProcessor(config)

    # Параметры обработки
    limit = config.get("reels_processor.news_limit", 10)
    category = config.get("reels_processor.filter_by_category")

    # Обработка новостей
    enriched_news, scenarios = await processor.process_latest_news(limit, category)

    # Отправка на модерацию
    if scenarios:
        await processor.send_to_moderation(scenarios)
        logger.info(f"✅ Обработано {len(scenarios)} новостей")
    else:
        logger.warning("⚠️ Нет новостей для обработки")
```

```python
async def main_async(argv: list[str] = None):
    # ... существующий код

    if args.mode == "reels":
        await run_reels_mode(config)
    elif args.mode == "listener":
        await run_listener_mode(config)
    # ... остальное
```

#### 4.2. Добавить авто-запуск после processor (30 мин)

```python
async def run_processor_mode(config: Config | None = None):
    # ... существующий код обработки

    # После успешной обработки
    logger.info("Процессор завершил работу")

    # Проверить, нужен ли авто-запуск reels
    if config.get("reels_processor.auto_run_after_processor", False):
        logger.info("Авто-запуск Reels Generator...")
        await run_reels_mode(config)
```

#### 4.3. Написать интеграционный тест (30 мин)

```python
@pytest.mark.integration
async def test_main_reels_mode():
    """Интеграционный тест режима reels"""
    # Подготовить тестовую БД с новостями
    # Запустить main с режимом "reels"
    # Проверить, что сценарии сгенерированы
```

### Итоговые критерии Этапа 4

- ✅ Режим `python main.py reels` работает
- ✅ Авто-запуск после processor работает
- ✅ Интеграционный тест проходит
- ✅ Коммит: "feat(reels): Этап 4 — Интеграция в main.py"

---

## 📋 ЭТАП 5: ТЕСТИРОВАНИЕ

**Время:** 2-3 часа
**Зависимости:** Этапы 1-4

### Задачи

#### 5.1. Увеличить coverage до >70% (90 мин)

- Добавить тесты для edge cases
- Тесты для error handling
- Тесты для валидации

#### 5.2. Интеграционные тесты end-to-end (60 мин)

```python
@pytest.mark.integration
async def test_full_pipeline():
    """Полный цикл: БД → Perplexity → Telegram"""
    # 1. Создать тестовую новость в БД
    # 2. Запустить processor
    # 3. Проверить, что сценарий отправлен в Telegram
```

#### 5.3. Coverage report (30 мин)

```bash
pytest reels/ --cov=reels --cov-report=html --cov-report=term
```

### Итоговые критерии Этапа 5

- ✅ Coverage > 70%
- ✅ Все unit-тесты проходят
- ✅ Интеграционные тесты проходят
- ✅ Coverage report сгенерирован
- ✅ Коммит: "test(reels): Этап 5 — Тестирование"

---

## 📋 ЭТАП 6: ДОКУМЕНТАЦИЯ

**Время:** 1-2 часа
**Зависимости:** Этапы 1-5

### Задачи

#### 6.1. README для модуля (45 мин)

**Файл:** `reels/README.md`

- Описание модуля
- Установка зависимостей
- Примеры использования
- API reference
- FAQ

#### 6.2. Примеры использования (30 мин)

**Файл:** `reels/examples/`

- `basic_usage.py` — базовое использование
- `custom_prompts.py` — кастомные промпты
- `batch_processing.py` — массовая обработка

#### 6.3. API документация (30 мин)

Добавить docstrings везде, сгенерировать API docs.

### Итоговые критерии Этапа 6

- ✅ README полный
- ✅ Примеры работают
- ✅ API документация актуальна
- ✅ Коммит: "docs(reels): Этап 6 — Документация"

---

## ✅ КРИТЕРИИ ГОТОВНОСТИ ПРОЕКТА

### Must Have (обязательно)

- ✅ Все 6 этапов завершены
- ✅ Coverage > 70%
- ✅ Все тесты проходят (unit + integration)
- ✅ `python main.py reels --profile reels` работает
- ✅ Отправка в Telegram работает
- ✅ README и документация полные
- ✅ Код прошел review

### Nice to Have (желательно)

- ⏳ Coverage > 80%
- ⏳ Performance тесты
- ⏳ Примеры для разных use cases
- ⏳ Мониторинг использования токенов
- ⏳ Dashboard для просмотра сценариев

---

## 📊 ПРОГРЕСС

| Этап | Статус | Прогресс | Время |
|------|--------|----------|-------|
| 1. Инфраструктура | 🔨 | 0% | 0/3 ч |
| 2. Perplexity Client | ⏳ | 0% | 0/3 ч |
| 3. Reels Processor | ⏳ | 0% | 0/4 ч |
| 4. Интеграция main.py | ⏳ | 0% | 0/2 ч |
| 5. Тестирование | ⏳ | 0% | 0/3 ч |
| 6. Документация | ⏳ | 0% | 0/2 ч |
| **ИТОГО** | 🔨 | **0%** | **0/17 ч** |

---

## 🚀 СЛЕДУЮЩИЕ ШАГИ

1. Начать с Этапа 1: Создать структуру папок
2. Обновлять PROGRESS.md после каждой задачи
3. Делать коммиты по завершении каждого этапа
4. Запускать тесты после каждого изменения

---

**Дата обновления:** 2025-10-20
**Ответственный:** Claude Code

