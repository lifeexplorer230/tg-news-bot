"""
Клиент для взаимодействия с Perplexity API

Обеспечивает обогащение новостей и генерацию сценариев Reels
через Perplexity AI.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any

import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError
)

from reels.models.news import News, EnrichedNews, Enrichment, ProcessingMetadata
from reels.models.reels import ReelsScenario, Script
from reels.config.reels_config import ReelsConfig

logger = logging.getLogger(__name__)


class PerplexityClient:
    """Клиент для взаимодействия с Perplexity API"""

    def __init__(self, config: ReelsConfig):
        """
        Инициализация клиента

        Args:
            config: Конфигурация Reels модуля
        """
        self.config = config
        self.api_key = config.perplexity_api_key
        self.model = config.perplexity_model
        self.base_url = config.perplexity_base_url
        self.timeout = config.perplexity_timeout
        self.max_retries = config.perplexity_max_retries

        logger.info(f"PerplexityClient инициализирован: model={self.model}, timeout={self.timeout}s")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError))
    )
    async def _make_request(self, messages: list[dict]) -> dict:
        """
        Выполнить запрос к Perplexity API с retry логикой

        Args:
            messages: Список сообщений для API

        Returns:
            Ответ от API

        Raises:
            aiohttp.ClientError: При ошибке HTTP запроса
            ValueError: При ошибке валидации ответа
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages
        }

        logger.debug(f"Отправка запроса к Perplexity API: model={self.model}")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    # Логировать использование токенов
                    usage = data.get('usage', {})
                    tokens_used = usage.get('total_tokens', 0)
                    if self.config.log_tokens:
                        logger.info(
                            f"Perplexity API: токены использованы={tokens_used} "
                            f"(input={usage.get('prompt_tokens', 0)}, "
                            f"output={usage.get('completion_tokens', 0)})"
                        )

                    return data

            except aiohttp.ClientResponseError as e:
                logger.error(f"HTTP ошибка от Perplexity API: {e.status} - {e.message}")
                raise
            except aiohttp.ClientError as e:
                logger.error(f"Ошибка соединения с Perplexity API: {e}")
                raise
            except Exception as e:
                logger.error(f"Неожиданная ошибка при запросе к Perplexity API: {e}")
                raise

    def _build_prompt(self, template: str, context: dict) -> str:
        """
        Подставить переменные в промпт шаблон

        Args:
            template: Шаблон промпта с переменными {var}
            context: Словарь с значениями для подстановки

        Returns:
            Промпт с подставленными значениями
        """
        try:
            return template.format(**context)
        except KeyError as e:
            logger.error(f"Ошибка подстановки переменных в промпт: отсутствует {e}")
            raise ValueError(f"В промпте отсутствует переменная: {e}")

    def _parse_json_response(self, content: str) -> dict:
        """
        Парсить JSON из ответа Perplexity (может быть в markdown блоке)

        Args:
            content: Текст ответа от API

        Returns:
            Распарсенный JSON

        Raises:
            ValueError: Если JSON невалиден
        """
        # Убрать leading/trailing whitespace
        content = content.strip()

        # Убрать markdown блоки если есть
        if content.startswith("```json"):
            content = content[7:]  # Убрать ```json
        elif content.startswith("```"):
            content = content[3:]  # Убрать ```

        if content.endswith("```"):
            content = content[:-3]  # Убрать закрывающий ```

        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(
                f"Ошибка парсинга JSON от Perplexity: {e}\n"
                f"Content (first 500 chars): {content[:500]}"
            )
            raise ValueError(f"Perplexity вернул некорректный JSON: {e}")

    async def enrich_news(self, news: News) -> EnrichedNews:
        """
        Обогатить новость дополнительными деталями через Perplexity

        Args:
            news: Исходная новость

        Returns:
            Обогащенная новость с дополнительным контекстом

        Raises:
            ValueError: При ошибке обработки
        """
        logger.info(f"Обогащение новости: {news.id} - {news.title[:50]}...")

        try:
            # Загрузить промпт
            template = self.config.load_prompt("enrich_news")

            # Подготовить контекст для промпта
            context = {
                "title": news.title,
                "summary": news.summary,
                "source": news.source,
                "url": f"**URL:** {news.url}" if news.url else ""
            }

            # Построить промпт
            prompt = self._build_prompt(template, context)

            # Выполнить запрос к API
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

            # Создать обогащенную новость
            enriched = EnrichedNews.from_news(news, enrichment, metadata)

            logger.info(
                f"✅ Новость обогащена: {news.id}, "
                f"фактов={len(enrichment.key_facts)}, "
                f"токенов={metadata.tokens_used}"
            )

            return enriched

        except RetryError as e:
            logger.error(f"Не удалось обогатить новость после {self.max_retries} попыток: {e}")
            raise ValueError(f"Ошибка обогащения новости: превышено количество попыток")
        except Exception as e:
            logger.error(f"Ошибка обогащения новости {news.id}: {e}", exc_info=True)
            raise

    async def generate_reels_scenario(self, enriched_news: EnrichedNews) -> ReelsScenario:
        """
        Сгенерировать сценарий Reels из обогащенной новости

        Args:
            enriched_news: Обогащенная новость

        Returns:
            Сценарий для Instagram Reels

        Raises:
            ValueError: При ошибке генерации
        """
        logger.info(f"Генерация сценария Reels для новости: {enriched_news.id}")

        try:
            # Загрузить промпт
            template = self.config.load_prompt("generate_reels")

            # Сериализовать обогащенную новость в JSON
            enriched_json = enriched_news.model_dump_json(indent=2, exclude_none=True)

            # Подготовить контекст
            context = {"enriched_news_json": enriched_json}

            # Построить промпт
            prompt = self._build_prompt(template, context)

            # Выполнить запрос к API
            messages = [{"role": "user", "content": prompt}]
            response = await self._make_request(messages)

            # Парсить ответ
            content = response['choices'][0]['message']['content']
            scenario_data = self._parse_json_response(content)

            # Валидировать через Pydantic
            script = Script(
                hook=scenario_data['hook'],
                main_content=scenario_data['main_content'],
                cta=scenario_data['cta']
            )

            scenario = ReelsScenario(
                news_id=enriched_news.id,
                title=enriched_news.title,
                duration=scenario_data.get('duration', 30),
                script=script,
                visual_suggestions=scenario_data['visual_suggestions'],
                hashtags=scenario_data['hashtags'],
                music_mood=scenario_data['music_mood'],
                target_audience=scenario_data['target_audience']
            )

            logger.info(
                f"✅ Сценарий Reels создан: {enriched_news.id}, "
                f"длина_скрипта={scenario.get_total_script_length()}, "
                f"хэштегов={len(scenario.hashtags)}"
            )

            return scenario

        except RetryError as e:
            logger.error(f"Не удалось сгенерировать сценарий после {self.max_retries} попыток: {e}")
            raise ValueError(f"Ошибка генерации сценария: превышено количество попыток")
        except Exception as e:
            logger.error(f"Ошибка генерации сценария для {enriched_news.id}: {e}", exc_info=True)
            raise

    async def process_news_to_reels(self, news: News) -> tuple[EnrichedNews, ReelsScenario]:
        """
        Полный цикл: обогащение новости + генерация сценария Reels

        Args:
            news: Исходная новость

        Returns:
            Кортеж (обогащенная новость, сценарий Reels)

        Raises:
            ValueError: При ошибке обработки
        """
        logger.info(f"Полная обработка новости в Reels: {news.id}")

        # Шаг 1: Обогатить новость
        enriched = await self.enrich_news(news)

        # Шаг 2: Сгенерировать сценарий
        scenario = await self.generate_reels_scenario(enriched)

        logger.info(f"✅ Полная обработка завершена: {news.id}")

        return enriched, scenario
