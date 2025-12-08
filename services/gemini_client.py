"""Клиент для работы с Google Gemini API"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Callable, Optional

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from utils.logger import setup_logger
from services.gemini_cache import GeminiCache


class NewsItem(BaseModel):
    """Pydantic-модель для валидации новостей Gemini."""

    model_config = ConfigDict(extra="ignore")

    id: int
    title: str
    description: str
    score: int = Field(ge=1, le=10)
    reason: str | None = None
    source_link: str | None = None
    source_message_id: int | None = None
    source_channel_id: int | None = None
    text: str | None = None
    marketplace: str | None = None
    category: str | None = None


class CategoryNews(BaseModel):
    """Pydantic-модель для валидации новостей по категориям маркетплейсов."""

    model_config = ConfigDict(extra="ignore")

    wildberries: list[NewsItem] = Field(default_factory=list)
    ozon: list[NewsItem] = Field(default_factory=list)
    general: list[NewsItem] = Field(default_factory=list)


class DynamicCategoryNews(BaseModel):
    """Pydantic-модель для валидации новостей с динамическими категориями (QA-1)."""

    model_config = ConfigDict(extra="allow")  # Разрешаем любые категории

    def __init__(self, **data):
        """Инициализация с валидацией каждой категории как списка NewsItem."""
        # Валидируем каждую категорию как список NewsItem
        validated_data = {}
        for category_name, items in data.items():
            if isinstance(items, list):
                validated_data[category_name] = [
                    item if isinstance(item, NewsItem) else NewsItem(**item)
                    for item in items
                ]
            else:
                validated_data[category_name] = []
        super().__init__(**validated_data)


logger = setup_logger(__name__)

_GEMINI_LOCK = threading.Lock()


DEFAULT_SELECT_TOP_NEWS_PROMPT = """Ты — редактор новостного дайджеста про маркетплейсы (Ozon, Wildberries, Яндекс.Маркет, KazanExpress и др.).

Проанализируй следующие сообщения из Telegram-каналов и выбери ТОП-{top_n} новостей, которые максимально полезны продавцам.

КРИТЕРИИ ОТБОРА (в порядке важности):

ВЫСОКИЙ ПРИОРИТЕТ (оценка 9-10):
✅ Новые правила, комиссии, договоры, штрафы или изменения в правилах размещения
✅ Логистика и склад: изменения тарифа, SLA, возвратов, приёмки, поставок
✅ Инструменты продвижения, аналитика, рекламные форматы с датами запуска
✅ Официальные анонсы от маркетплейса или государства, влияющие на продавцов

СРЕДНИЙ ПРИОРИТЕТ (оценка 7-8):
✅ Подробные кейсы с цифрами и пошаговыми выводами
✅ Аналитика рынка, тренды категорий, изменения спроса
✅ Программы поддержки, субсидии, новые акции для селлеров

НИЗКИЙ ПРИОРИТЕТ (оценка 5-6):
✅ Обучающие материалы с конкретными советами и чек-листами
✅ Разборы удачных карточек товаров или маркетинговых приёмов

ОБЯЗАТЕЛЬНО ИСКЛЮЧИ:
❌ Рекламу платных курсов, марафонов, менторства
❌ Обещания «быстрых миллионов», мотивационные посты без фактов
❌ Продажу аккаунтов, серые схемы, услуги накрутки
❌ Мемы, оффтоп и новости не про e-commerce

СООБЩЕНИЯ:

{messages_block}

Верни JSON массив с ТОП-{top_n} новостями в формате:
[
  {{"id": номер_ID_из_списка, "score": оценка_от_1_до_10, "reason": "кратко, почему важно"}},
  ...
]

Верни ТОЛЬКО JSON, без дополнительного текста."""


DEFAULT_SELECT_AND_FORMAT_NEWS_PROMPT = """Ты — редактор маркетплейс-дайджеста. Нужно выбрать ТОП-{top_n} новостей и сразу оформить их для публикации.

СООБЩЕНИЯ:

{messages_block}

КРИТЕРИИ:
ВЫСОКИЙ ПРИОРИТЕТ (9-10) — правила, комиссии, логистика, официальные письма.
СРЕДНИЙ (7-8) — кейсы с цифрами, аналитика, инструменты продвижения.
НИЗКИЙ (5-6) — инструкции с конкретными шагами.

ИСКЛЮЧИ: рекламу курсов, накрутки, мотивационные посты без фактов.

Верни JSON массив из {top_n} объектов с полями:
[
  {{
    "id": номер_ID,
    "score": оценка,
    "reason": "почему важно",
    "title": "заголовок без эмодзи",
    "description": "2-4 предложения с фактами"
  }},
  ...
]

Верни ТОЛЬКО JSON, без дополнительного текста."""


DEFAULT_SELECT_MARKETPLACE_NEWS_PROMPT = """Ты — редактор новостей маркетплейса {display_name}.

Проанализируй сообщения и выбери ТОП-{top_n} материалов про {display_name}. Сразу оформи их для дайджеста.

КРИТЕРИИ (по убыванию важности):

ВЫСОКИЙ ПРИОРИТЕТ (9-10):
✅ Правила, комиссии, штрафы, которые вводит {display_name}
✅ Изменения в выплатах, логистике, поставках, маркетинговых инструментах
✅ Официальные письма/сообщения {display_name} или государственных органов
✅ Технические сбои/обновления, влияющие на продажи

СРЕДНИЙ ПРИОРИТЕТ (7-8):
✅ Кейсы селлеров с цифрами именно на {display_name}
✅ Появление новых сервисов, бонусов, льгот для продавцов
✅ Аналитика продаж и спроса внутри площадки

НИЗКИЙ ПРИОРИТЕТ (5-6):
✅ Полезные инструкции и советы с конкретными шагами
✅ Разборы карточек, рекламных кампаний, повышающих конверсию

ОБЯЗАТЕЛЬНО ИСКЛЮЧИ:
❌ Рекламу платных курсов и «разбогатеешь за неделю»
❌ Новости про другие площадки
❌ Общие рассуждения без фактов
❌ Продажу аккаунтов, услуги накрутки, спам

СООБЩЕНИЯ:

{messages_block}

Верни JSON массив:
[
  {{"id": номер_ID, "title": "Заголовок без эмодзи", "description": "2-3 предложения", "score": число, "reason": "почему важно"}},
  ...
]

Верни ТОЛЬКО JSON, без дополнительного текста."""


DEFAULT_SELECT_THREE_CATEGORIES_PROMPT = """Ты — редактор сводного отчёта по маркетплейсам. Разложи новости по категориям:

📦 WILDBERRIES ({wb_count}) — всё, что касается продавцов Wildberries (WB, ВБ, вайлдберриз).
📦 OZON ({ozon_count}) — только новости про Ozon.
📦 ОБЩИЕ ({general_count}) — законодательство, логистика, тренды, которые влияют на всех.

ВЫСОКИЙ ПРИОРИТЕТ (9-10): правила, комиссии, логистика, официальные письма.
СРЕДНИЙ (7-8): кейсы с цифрами, программы поддержки, аналитика.
НИЗКИЙ (5-6): инструкции с конкретными шагами.

ИСКЛЮЧИ рекламу курсов, накрутки, мемы.

СООБЩЕНИЯ:

{messages_block}

Верни JSON-объект:
{{
  "wildberries": [{{"id": ..., "title": "...", "description": "...", "score": ..., "reason": "..."}}],
  "ozon": [...],
  "general": [...]
}}

Новость может быть только в одной категории. Заголовок 5-7 слов, описание 2-3 предложения с фактами. Верни ТОЛЬКО JSON."""


DEFAULT_SELECT_DYNAMIC_CATEGORIES_PROMPT = """Ты — редактор новостного дайджеста. Разложи новости по категориям:

{categories_description}

ПРАВИЛА ОТБОРА:
- ВЫСОКИЙ ПРИОРИТЕТ (9-10): важные обновления, правила, официальные заявления, значимые цифры
- СРЕДНИЙ (7-8): аналитика, кейсы с данными, полезные инсайты
- НИЗКИЙ (5-6): инструкции, советы, второстепенные новости

ИСКЛЮЧИ: рекламу, промо-посты, мемы, off-topic

СООБЩЕНИЯ:

{messages_block}

Верни JSON-объект с категориями. Каждая новость должна содержать:
- id: номер сообщения (целое число)
- title: заголовок 5-7 слов
- description: описание 2-3 предложения с фактами
- score: оценка важности 1-10
- reason: почему отобрана (опционально)

Формат JSON:
{{
{json_structure}
}}

Новость может быть только в одной категории. Верни ТОЛЬКО JSON без дополнительного текста."""


DEFAULT_FORMAT_NEWS_POST_PROMPT = """Сформируй структурированное описание новости для продавцов маркетплейсов.

ИСХОДНАЯ НОВОСТЬ:
{text}

СОЗДАЙ JSON С ПОЛЯМИ:
{{
  "title": "Заголовок без эмодзи",
  "description": "2-4 предложения с фактами",
  "source_link": "{source_link}"
}}

Верни ТОЛЬКО JSON, без дополнительного текста."""


class GeminiClient:
    """Клиент для работы с Gemini API"""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-1.5-flash",
        prompt_loader: Optional[Callable[[str], Optional[str]]] = None,
    ):
        """
        Инициализация Gemini клиента без мгновенной загрузки модели

        Args:
            api_key: API ключ Google Gemini
            model_name: Название модели
        """
        self.api_key = api_key
        self.model_name = model_name
        self._model: genai.GenerativeModel | None = None
        self._prompt_loader = prompt_loader
        self._prompt_cache: dict[str, str] = {}

        # Инициализация кэша для ответов
        self._response_cache = GeminiCache(
            ttl_hours=24,  # Кэш на 24 часа
            max_size=1000  # Максимум 1000 записей
        )
        logger.info("Инициализирован кэш для Gemini ответов")

    def _ensure_model(self) -> genai.GenerativeModel:
        if self._model is not None:
            return self._model

        with _GEMINI_LOCK:
            if self._model is not None:
                return self._model

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            logger.info(f"Gemini клиент инициализирован: {self.model_name}")
            self._model = model
            return self._model

    @property
    def model(self) -> genai.GenerativeModel:
        """Совместимость со старыми тестами/кодом, ожидающими атрибут model."""
        return self._ensure_model()

    def _get_prompt_template(self, key: str) -> Optional[str]:
        if not self._prompt_loader:
            return None
        if key in self._prompt_cache:
            return self._prompt_cache[key]
        template = self._prompt_loader(key)
        if template:
            self._prompt_cache[key] = template
            return template
        return None

    def _render_prompt(self, key: str, default_template: str, **kwargs) -> str:
        template = self._get_prompt_template(key) or default_template
        try:
            return template.format(**kwargs)
        except KeyError as exc:
            logger.error("Не удалось подставить параметры для промпта '%s': %s", key, exc)
            return default_template.format(**kwargs)

    @staticmethod
    def _escape_braces(value: str) -> str:
        return value.replace("{", "{{").replace("}", "}}")

    def _build_messages_block(self, messages: list[dict], text_limit: int = 500) -> str:
        parts = []
        for msg in messages:
            text = msg.get("text") or ""
            snippet = text[:text_limit]
            channel = msg.get("channel_username", "unknown")
            parts.append(f"ID: {msg.get('id')}\nКанал: @{channel}\nТекст:\n{snippet}")
        block = "\n\n".join(parts)
        return self._escape_braces(block)

    @staticmethod
    def _generate_request_id() -> str:
        """
        Генерация уникального ID для трассировки запроса (CR-C6)

        Returns:
            Короткий уникальный ID (8 символов)
        """
        return str(uuid.uuid4())[:8]

    @staticmethod
    def _estimate_prompt_tokens(prompt: str) -> int:
        """
        Оценка количества токенов в промпте (CR-C6)

        Примерная оценка: 1 токен ≈ 4 символа для русского текста.

        Args:
            prompt: Промпт для оценки

        Returns:
            Примерное количество токенов
        """
        return len(prompt) // 4

    def _validate_prompt_size(
        self, prompt: str, max_tokens: int = 30000, method_name: str = "unknown"
    ) -> bool:
        """
        Валидация размера промпта с предупреждениями (CR-C6)

        Args:
            prompt: Промпт для валидации
            max_tokens: Максимальное количество токенов (по умолчанию 30k)
            method_name: Название метода для логирования

        Returns:
            True если размер приемлем, False если превышен лимит
        """
        estimated_tokens = self._estimate_prompt_tokens(prompt)

        if estimated_tokens > max_tokens:
            logger.warning(
                f"[CR-C6] {method_name}: Промпт слишком большой! "
                f"Estimated {estimated_tokens} tokens (max {max_tokens}). "
                f"Prompt size: {len(prompt)} chars. Consider using chunking."
            )
            return False

        if estimated_tokens > max_tokens * 0.8:
            logger.info(
                f"[CR-C6] {method_name}: Промпт близок к лимиту. "
                f"Estimated {estimated_tokens} tokens (80% of {max_tokens}). "
                f"Prompt size: {len(prompt)} chars."
            )

        return True

    def _log_api_call(
        self,
        method_name: str,
        prompt: str,
        response_text: str,
        duration: float,
        request_id: str | None = None,
    ):
        """
        Детальное логирование вызова Gemini API

        Args:
            method_name: Название метода
            prompt: Отправленный промпт
            response_text: Полученный ответ
            duration: Время выполнения в секундах
            request_id: Уникальный ID запроса для трассировки (опционально, CR-C6)
        """
        # Формируем префикс с request_id если есть
        prefix = f"[Gemini][{request_id}]" if request_id else "[Gemini]"

        # Логируем метаданные
        logger.info(
            f"{prefix} {method_name}: промпт {len(prompt)} символов, "
            f"ответ {len(response_text)} символов, время {duration:.2f}s"
        )

        # Логируем промпт (с ограничением)
        max_log_length = 2000
        if len(prompt) <= max_log_length:
            logger.debug(f"{prefix} {method_name} ПРОМПТ:\n{prompt}")
        else:
            logger.debug(
                f"{prefix} {method_name} ПРОМПТ (обрезан до {max_log_length} символов):\n"
                f"{prompt[:max_log_length]}..."
            )

        # Логируем полный ответ (с ограничением)
        if len(response_text) <= max_log_length:
            logger.debug(f"{prefix} {method_name} ОТВЕТ:\n{response_text}")
        else:
            logger.debug(
                f"{prefix} {method_name} ОТВЕТ (обрезан до {max_log_length} символов):\n"
                f"{response_text[:max_log_length]}..."
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def select_top_news(self, messages: list[dict], top_n: int = 10) -> list[dict]:
        """
        Отобрать ТОП-N самых важных новостей про маркетплейсы

        Args:
            messages: Список сообщений с полями {id, text, channel}
            top_n: Количество новостей для отбора

        Returns:
            Список отобранных новостей с оценками
        """
        if not messages:
            return []

        # Проверяем кэш
        cache_params = {"top_n": top_n}
        cache_key = {"messages": messages, "params": cache_params}
        cached_result = self._response_cache.get(cache_key)
        if cached_result is not None:
            logger.info("Gemini ответ получен из кэша")
            return cached_result

        # Формируем промпт
        messages_block = self._build_messages_block(messages)

        prompt = self._render_prompt(
            "select_top_news",
            DEFAULT_SELECT_TOP_NEWS_PROMPT,
            top_n=top_n,
            messages_block=messages_block,
        )

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # Детальное логирование
            self._log_api_call("select_top_news", prompt, result_text, duration)

            # Извлекаем JSON из ответа (иногда Gemini добавляет ```json```)
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            # Пытаемся найти JSON массив с помощью регулярки если прямой парсинг не работает
            if not result_text.startswith("["):
                import re

                json_match = re.search(r"\[[\s\S]*\]", result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON массив в ответе Gemini: {result_text}")
                    return []

            selected = json.loads(result_text)
            logger.info(f"Gemini отобрал {len(selected)} новостей из {len(messages)}")

            # Сохраняем результат в кэш
            result = selected[:top_n]
            self._response_cache.set(cache_key, result)
            logger.debug("Результат сохранен в кэш")

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini: {e}")
            logger.error(f"Текст ответа: {result_text}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при отборе новостей через Gemini: {e}")
            if isinstance(e, google_exceptions.GoogleAPICallError):
                raise
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def format_news_post(
        self, text: str, channel: str, message_link: str | None = None
    ) -> dict | None:
        """
        Отформатировать новость в структурированный формат

        Args:
            text: Исходный текст новости
            channel: Канал-источник
            message_link: Ссылка на оригинальное сообщение

        Returns:
            Dict с полями: title, description, source_link
        """
        effective_link = message_link if message_link else f"https://t.me/{channel}"
        prompt = self._render_prompt(
            "format_news_post",
            DEFAULT_FORMAT_NEWS_POST_PROMPT,
            text=self._escape_braces(text),
            source_link=self._escape_braces(effective_link),
        )

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # Детальное логирование
            self._log_api_call("format_news_post", prompt, result_text, duration)

            # Извлекаем JSON из ответа
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            formatted = json.loads(result_text)

            # Добавляем ссылку на источник
            formatted["source_link"] = effective_link

            return formatted

        except Exception as e:
            logger.error(f"Ошибка форматирования поста через Gemini: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def select_and_format_news(self, messages: list[dict], top_n: int = 10) -> list[dict]:
        """
        НОВАЯ СХЕМА: Отобрать И отформатировать ТОП-N новостей одним запросом

        Args:
            messages: Список сообщений с полями {id, text, channel}
            top_n: Количество новостей для отбора

        Returns:
            Список отформатированных новостей с полями:
            {id, title, description, source_link, score, reason}
        """
        if not messages:
            return []

        messages_block = self._build_messages_block(messages)

        prompt = self._render_prompt(
            "select_and_format_news",
            DEFAULT_SELECT_AND_FORMAT_NEWS_PROMPT,
            top_n=top_n,
            messages_block=messages_block,
        )

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # Детальное логирование
            self._log_api_call("select_and_format_news", prompt, result_text, duration)

            # Извлекаем JSON из ответа
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            # Пытаемся найти JSON массив с помощью регулярки
            if not result_text.startswith("["):
                import re

                json_match = re.search(r"\[[\s\S]*\]", result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON массив в ответе Gemini: {result_text}")
                    return []

            selected = json.loads(result_text)
            try:
                validated_items = [NewsItem(**item) for item in selected]
                selected = [item.model_dump() for item in validated_items]
            except ValidationError as e:
                logger.error(f"Ошибка валидации JSON от Gemini: {e}")
                return []

            # Добавляем source_link к каждой новости
            messages_dict = {msg["id"]: msg for msg in messages}
            for item in selected:
                msg_id = item["id"]
                if msg_id in messages_dict:
                    msg = messages_dict[msg_id]
                    item["source_link"] = (
                        f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                    )
                    item["source_message_id"] = msg_id
                    item["source_channel_id"] = msg["channel_id"]
                    item["text"] = msg["text"]  # Для embeddings

            logger.info(
                f"Gemini отобрал и отформатировал {len(selected)} новостей из {len(messages)}"
            )
            return selected[:top_n]

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini: {e}")
            logger.error(f"Текст ответа: {result_text}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при отборе и форматировании новостей через Gemini: {e}")
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def is_spam_or_ad(self, text: str) -> bool:
        """
        Проверить, является ли текст спамом или рекламой

        Args:
            text: Текст для проверки

        Returns:
            True если это спам/реклама
        """
        prompt = f"""Определи, несёт ли сообщение пользу продавцам маркетплейсов или это реклама/спам.

ТЕКСТ:
{text[:500]}

Считай спамом, если упоминаются платные курсы, менторы, агентские услуги, накрутки, продажа аккаунтов или контент никак не помогает селлерам.
Если в тексте есть конкретные факты, правила, цифры или полезные инструкции — это не спам.

Ответь ТОЛЬКО одним словом: "ДА" (если спам/реклама) или "НЕТ" (если полезно)."""

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            answer = response.text.strip().upper()
            duration = time.time() - start_time

            # Детальное логирование
            self._log_api_call("is_spam_or_ad", prompt, answer, duration)

            return "ДА" in answer

        except Exception as e:
            logger.error(f"Ошибка проверки на спам: {e}")
            return False

    @staticmethod
    def _chunk_list(items: list, chunk_size: int) -> list[list]:
        """
        Разбить список на чанки заданного размера (CR-C6)

        Args:
            items: Список элементов
            chunk_size: Размер каждого чанка

        Returns:
            Список чанков
        """
        return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]

    def _process_category_chunk(
        self,
        messages: list[dict],
        marketplace: str,
        chunk_top_n: int,
        marketplace_display_name: str,
    ) -> list[dict]:
        """
        Обработать один чанк сообщений для маркетплейса (CR-C6 helper)

        Args:
            messages: Чанк сообщений
            marketplace: Название маркетплейса
            chunk_top_n: Сколько новостей отобрать из чанка
            marketplace_display_name: Display name для промпта

        Returns:
            Список отобранных новостей из чанка
        """
        # CR-C6: Генерация request_id для трассировки
        request_id = self._generate_request_id()

        messages_block = self._build_messages_block(messages)

        prompt = self._render_prompt(
            "select_and_format_marketplace_news",
            DEFAULT_SELECT_MARKETPLACE_NEWS_PROMPT,
            top_n=chunk_top_n,
            messages_block=messages_block,
            display_name=marketplace_display_name,
            marketplace=marketplace,
        )

        # CR-C6: Валидация размера промпта
        method_name = f"select_marketplace_news[{marketplace}]"
        self._validate_prompt_size(prompt, max_tokens=30000, method_name=method_name)

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # CR-C6: Детальное логирование с request_id
            self._log_api_call(method_name, prompt, result_text, duration, request_id)

            # Удаляем markdown разметку если есть
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            # Пытаемся найти JSON массив
            if not result_text.startswith("["):
                json_match = re.search(r"\[[\s\S]*\]", result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON в ответе Gemini: {result_text}")
                    return []

            selected = json.loads(result_text)
            try:
                validated_items = [NewsItem(**item) for item in selected]
                selected = [item.model_dump() for item in validated_items]
            except ValidationError as e:
                logger.error(f"Ошибка валидации JSON от Gemini ({marketplace}): {e}")
                return []

            # Добавляем дополнительные поля
            messages_dict = {msg["id"]: msg for msg in messages}
            for item in selected:
                msg_id = item["id"]
                if msg_id in messages_dict:
                    msg = messages_dict[msg_id]
                    item["source_link"] = (
                        f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                    )
                    item["source_message_id"] = msg_id
                    item["source_channel_id"] = msg["channel_id"]
                    item["text"] = msg["text"]
                    item["marketplace"] = marketplace

            logger.debug(f"Chunk: отобрано {len(selected)} новостей из {len(messages)} сообщений")
            return selected[:chunk_top_n]

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini ({marketplace}): {e}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при отборе новостей для {marketplace}: {e}")
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def select_and_format_marketplace_news(
        self,
        messages: list[dict],
        marketplace: str,
        top_n: int = 10,
        marketplace_display_name: str | None = None,
        chunk_size: int = 50,
    ) -> list[dict]:
        """
        Отбор и форматирование новостей для маркетплейсов (Ozon, Wildberries)

        С поддержкой chunking (CR-C6): если messages > chunk_size, разбиваем на чанки.

        Args:
            messages: Список сообщений уже отфильтрованных по ключевым словам
            marketplace: Название маркетплейса (ozon или wildberries)
            top_n: Количество новостей для отбора
            marketplace_display_name: Display name для промпта (опционально)
            chunk_size: Максимальный размер чанка (по умолчанию 50)

        Returns:
            Список отформатированных новостей
        """
        if not messages:
            return []

        display_name = marketplace_display_name or marketplace.replace("_", " ").title()

        # CR-C6: Chunking для больших списков сообщений
        if len(messages) <= chunk_size:
            # Малый список: обрабатываем за один запрос
            logger.info(f"Обработка {len(messages)} сообщений для {marketplace} (один запрос)")
            return self._process_category_chunk(messages, marketplace, top_n, display_name)

        # Большой список: разбиваем на чанки
        chunks = self._chunk_list(messages, chunk_size)
        logger.info(
            f"CR-C6: Разбиваем {len(messages)} сообщений на {len(chunks)} чанков по {chunk_size} для {marketplace}"
        )

        all_selected = []
        for i, chunk in enumerate(chunks, 1):
            logger.debug(f"Обработка чанка {i}/{len(chunks)} ({len(chunk)} сообщений)")
            chunk_results = self._process_category_chunk(chunk, marketplace, top_n, display_name)
            all_selected.extend(chunk_results)

            # Rate limiting: пауза между чанками для соблюдения квоты TPM (32K/min Free Tier)
            if i < len(chunks):
                logger.info(f"⏱️  Rate limiting: пауза 60 секунд перед следующим чанком ({i+1}/{len(chunks)})")
                time.sleep(60)

        # Сортируем по score и берем top_n
        all_selected.sort(key=lambda x: x.get("score", 0), reverse=True)
        final_results = all_selected[:top_n]

        logger.info(
            f"CR-C6: Gemini отобрал {len(final_results)} топовых новостей для {marketplace} из {len(messages)} сообщений ({len(chunks)} чанков)"
        )

        return final_results

    def _process_categories_chunk(
        self,
        messages: list[dict],
        wb_count: int,
        ozon_count: int,
        general_count: int,
    ) -> dict[str, list[dict]]:
        """
        Обработать один чанк сообщений для 3-категорийной системы (CR-C6 helper)

        Args:
            messages: Чанк сообщений
            wb_count: Количество новостей про Wildberries
            ozon_count: Количество новостей про Ozon
            general_count: Количество общих новостей

        Returns:
            Dict с ключами 'wildberries', 'ozon', 'general'
        """
        # CR-C6: Генерация request_id для трассировки
        request_id = self._generate_request_id()

        messages_block = self._build_messages_block(messages)

        prompt = self._render_prompt(
            "select_three_categories",
            DEFAULT_SELECT_THREE_CATEGORIES_PROMPT,
            wb_count=wb_count,
            ozon_count=ozon_count,
            general_count=general_count,
            messages_block=messages_block,
        )

        # CR-C6: Валидация размера промпта
        method_name = "select_three_categories[chunk]"
        self._validate_prompt_size(prompt, max_tokens=30000, method_name=method_name)

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # CR-C6: Детальное логирование с request_id
            self._log_api_call(method_name, prompt, result_text, duration, request_id)

            # Удаляем markdown разметку
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            # Пытаемся найти JSON объект
            if not result_text.startswith("{"):
                json_match = re.search(r"\{[\s\S]*\}", result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON в ответе Gemini: {result_text}")
                    return {"wildberries": [], "ozon": [], "general": []}

            categories = json.loads(result_text)
            try:
                validated_categories = CategoryNews(**categories)
                categories = validated_categories.model_dump()
            except ValidationError as e:
                logger.error(f"Ошибка валидации JSON от Gemini (3 категории, chunk): {e}")
                return {"wildberries": [], "ozon": [], "general": []}

            # Добавляем дополнительные поля к каждой новости
            messages_dict = {msg["id"]: msg for msg in messages}

            for category_name in ["wildberries", "ozon", "general"]:
                if category_name not in categories:
                    categories[category_name] = []

                for item in categories[category_name]:
                    msg_id = item["id"]
                    if msg_id in messages_dict:
                        msg = messages_dict[msg_id]
                        item["source_link"] = (
                            f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                        )
                        item["source_message_id"] = msg_id
                        item["source_channel_id"] = msg["channel_id"]
                        item["text"] = msg["text"]
                        item["category"] = category_name

            wb_len = len(categories.get("wildberries", []))
            ozon_len = len(categories.get("ozon", []))
            gen_len = len(categories.get("general", []))

            logger.debug(
                f"Chunk: отобрано WB={wb_len}, Ozon={ozon_len}, Общие={gen_len} из {len(messages)} сообщений"
            )
            return categories

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini (3 категории, chunk): {e}")
            return {"wildberries": [], "ozon": [], "general": []}
        except Exception as e:
            logger.error(f"Ошибка при отборе новостей (3 категории, chunk): {e}")
            return {"wildberries": [], "ozon": [], "general": []}

    def _process_dynamic_categories_chunk(
        self,
        messages: list[dict],
        category_counts: dict[str, int],
    ) -> dict[str, list[dict]]:
        """
        Обработать один чанк сообщений для динамических категорий (QA-1)

        Args:
            messages: Чанк сообщений
            category_counts: Словарь {категория: количество}

        Returns:
            Dict с категориями из category_counts
        """
        # CR-C6: Генерация request_id для трассировки
        request_id = self._generate_request_id()

        messages_block = self._build_messages_block(messages)

        # Формируем описание категорий для промпта
        categories_description = []
        json_structure_lines = []

        for idx, (cat_name, count) in enumerate(category_counts.items(), 1):
            emoji = ["📦", "🔔", "📊", "🎮", "🎬", "🪙", "🤖", "💻"][idx % 8]
            categories_description.append(
                f"{emoji} {cat_name.upper()} ({count}) — новости категории '{cat_name}'"
            )
            json_structure_lines.append(
                f'  "{cat_name}": [{{"id": ..., "title": "...", "description": "...", "score": ..., "reason": "..."}}]'
            )

        categories_desc_text = "\n".join(categories_description)
        json_structure_text = ",\n".join(json_structure_lines)

        prompt = self._render_prompt(
            "select_dynamic_categories",
            DEFAULT_SELECT_DYNAMIC_CATEGORIES_PROMPT,
            categories_description=categories_desc_text,
            messages_block=messages_block,
            json_structure=json_structure_text,
        )

        # CR-C6: Валидация размера промпта
        method_name = "select_dynamic_categories[chunk]"
        self._validate_prompt_size(prompt, max_tokens=30000, method_name=method_name)

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # CR-C6: Детальное логирование с request_id
            self._log_api_call(method_name, prompt, result_text, duration, request_id)

            # Удаляем markdown разметку
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            # Пытаемся найти JSON объект
            if not result_text.startswith("{"):
                json_match = re.search(r"\{[\s\S]*\}", result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON в ответе Gemini: {result_text}")
                    return {cat: [] for cat in category_counts.keys()}

            categories = json.loads(result_text)

            # QA-1: Валидация с DynamicCategoryNews
            try:
                validated_categories = DynamicCategoryNews(**categories)
                # Конвертируем обратно в dict, сохраняя только нужные категории
                categories = {
                    cat: getattr(validated_categories, cat, [])
                    for cat in category_counts.keys()
                }
                # Конвертируем NewsItem объекты обратно в dict
                categories = {
                    cat: [item.model_dump() if isinstance(item, NewsItem) else item
                          for item in items]
                    for cat, items in categories.items()
                }
            except ValidationError as e:
                logger.error(f"Ошибка валидации JSON от Gemini (dynamic categories, chunk): {e}")
                return {cat: [] for cat in category_counts.keys()}

            # Добавляем дополнительные поля к каждой новости
            messages_dict = {msg["id"]: msg for msg in messages}

            for category_name in category_counts.keys():
                if category_name not in categories:
                    categories[category_name] = []

                for item in categories[category_name]:
                    msg_id = item["id"]
                    if msg_id in messages_dict:
                        msg = messages_dict[msg_id]
                        item["source_link"] = (
                            f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                        )
                        item["source_message_id"] = msg_id
                        item["source_channel_id"] = msg["channel_id"]
                        item["text"] = msg["text"]
                        item["category"] = category_name

            # Логирование результатов
            counts_str = ", ".join([f"{cat}={len(items)}" for cat, items in categories.items()])
            logger.debug(
                f"Chunk: отобрано {counts_str} из {len(messages)} сообщений"
            )
            return categories

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini (dynamic categories, chunk): {e}")
            return {cat: [] for cat in category_counts.keys()}
        except Exception as e:
            logger.error(f"Ошибка при отборе новостей (dynamic categories, chunk): {e}")
            return {cat: [] for cat in category_counts.keys()}

    def _deduplicate_by_source_id(
        self,
        all_categories: dict[str, list[dict]],
        category_counts: dict[str, int],
    ) -> dict[str, list[dict]]:
        """
        Удаляет дубликаты по source_message_id из результатов чанков.

        Одно сообщение может быть выбрано Gemini в разных чанках или категориях.
        Этот метод гарантирует что каждый source_message_id встречается только один раз.

        Args:
            all_categories: Словарь категорий с новостями
            category_counts: Ожидаемое количество новостей по категориям

        Returns:
            Очищенный словарь категорий без дубликатов
        """
        seen_ids: set[int] = set()
        deduplicated = {cat: [] for cat in category_counts.keys()}
        duplicate_count = 0

        for category_name in category_counts.keys():
            for news in all_categories.get(category_name, []):
                source_id = news.get("source_message_id")
                if source_id is not None and source_id in seen_ids:
                    duplicate_count += 1
                    logger.debug(
                        f"Дубликат source_message_id={source_id} удалён из категории {category_name}"
                    )
                    continue
                if source_id is not None:
                    seen_ids.add(source_id)
                deduplicated[category_name].append(news)

        if duplicate_count > 0:
            logger.info(
                f"🔍 Удалено {duplicate_count} дубликатов по source_message_id после chunking"
            )

        return deduplicated

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def select_by_categories(
        self,
        messages: list[dict],
        category_counts: dict[str, int],
        chunk_size: int = 50,
    ) -> dict[str, list[dict]]:
        """
        Универсальный отбор новостей по категориям (U1 - универсализация)

        Поддерживает любые категории из конфига, не только marketplace-специфичные.
        С поддержкой chunking (CR-C6): если messages > chunk_size, разбиваем на чанки.

        Args:
            messages: Список всех сообщений
            category_counts: Словарь {категория: количество}, например:
                {"wildberries": 5, "ozon": 5, "general": 5}
                {"ai": 10, "tech": 10, "crypto": 5}
            chunk_size: Максимальный размер чанка (по умолчанию 50)

        Returns:
            Dict с ключами из category_counts, каждый содержит список новостей
        """
        if not messages:
            # Возвращаем пустой dict для всех категорий
            return {cat: [] for cat in category_counts.keys()}

        # Используем старый метод для обратной совместимости
        # (для marketplace use case с 3 категориями)
        if set(category_counts.keys()) == {"wildberries", "ozon", "general"}:
            return self.select_three_categories(
                messages,
                wb_count=category_counts.get("wildberries", 5),
                ozon_count=category_counts.get("ozon", 5),
                general_count=category_counts.get("general", 5),
                chunk_size=chunk_size,
            )

        # QA-1: Для других категорий используем универсальный промпт с chunking
        logger.info(
            f"Используем универсальный промпт для категорий: {list(category_counts.keys())}"
        )

        # CR-C6: Chunking для больших списков сообщений
        if len(messages) <= chunk_size:
            # Малый список: обрабатываем за один запрос
            logger.info(
                f"Обработка {len(messages)} сообщений для категорий {list(category_counts.keys())} (один запрос)"
            )
            all_categories = self._process_dynamic_categories_chunk(messages, category_counts)

            # Применяем глобальную сортировку по score
            all_news = []
            for category_name, news_list in all_categories.items():
                for news in news_list:
                    news['category'] = category_name
                    all_news.append(news)

            all_news.sort(key=lambda x: x.get("score", 0), reverse=True)
            total_target = sum(category_counts.values())
            top_news = all_news[:total_target]

            final_categories = {cat: [] for cat in category_counts.keys()}
            for news in top_news:
                category = news.get('category')
                if category and category in final_categories:
                    final_categories[category].append(news)

            counts_str = ", ".join([f"{cat}={len(items)}" for cat, items in final_categories.items()])
            logger.info(f"Отобрал топовые новости (по score): {counts_str} (топ-{total_target})")

            return final_categories

        # Большой список: разбиваем на чанки
        chunks = self._chunk_list(messages, chunk_size)
        logger.info(
            f"CR-C6: Разбиваем {len(messages)} сообщений на {len(chunks)} чанков по {chunk_size} "
            f"для категорий {list(category_counts.keys())}"
        )

        # Собираем результаты из всех чанков
        all_categories = {cat: [] for cat in category_counts.keys()}

        for i, chunk in enumerate(chunks, 1):
            logger.debug(f"Обработка чанка {i}/{len(chunks)} ({len(chunk)} сообщений)")
            chunk_results = self._process_dynamic_categories_chunk(chunk, category_counts)

            # Объединяем результаты по категориям
            for category_name in category_counts.keys():
                all_categories[category_name].extend(chunk_results.get(category_name, []))

            # Rate limiting: пауза между чанками для соблюдения квоты TPM (32K/min Free Tier)
            if i < len(chunks):
                logger.info(f"⏱️  Rate limiting: пауза 60 секунд перед следующим чанком ({i+1}/{len(chunks)})")
                time.sleep(60)

        # Дедупликация по source_message_id после объединения чанков
        # Одно сообщение может быть выбрано в разных чанках - оставляем только первое вхождение
        all_categories = self._deduplicate_by_source_id(all_categories, category_counts)

        # НОВАЯ ЛОГИКА: Глобальная сортировка по score (приоритет > категории)
        # Объединяем все новости из всех категорий
        all_news = []
        for category_name, news_list in all_categories.items():
            for news in news_list:
                # Добавляем категорию в новость для последующей группировки
                news['category'] = category_name
                all_news.append(news)

        # Сортируем глобально по score от большего к меньшему
        all_news.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Берём топ N (сумма всех category_counts)
        total_target = sum(category_counts.values())
        top_news = all_news[:total_target]

        # Группируем обратно по категориям для совместимости с форматом вывода
        final_categories = {cat: [] for cat in category_counts.keys()}
        for news in top_news:
            category = news.get('category')
            if category and category in final_categories:
                final_categories[category].append(news)

        counts_str = ", ".join([f"{cat}={len(items)}" for cat, items in final_categories.items()])
        logger.info(f"CR-C6: Gemini отобрал топовые новости (по score): {counts_str} из {len(messages)} сообщений (топ-{total_target})")

        return final_categories

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry {retry_state.attempt_number}/3 для select_three_categories "
            f"после ошибки: {retry_state.outcome.exception()}"
        ),
        reraise=True,
    )
    def select_three_categories(
        self,
        messages: list[dict],
        wb_count: int = 5,
        ozon_count: int = 5,
        general_count: int = 5,
        chunk_size: int = 50,
    ) -> dict[str, list[dict]]:
        """
        Отбор новостей по 3 категориям: Wildberries, Ozon, Общие

        DEPRECATED: Используйте select_by_categories() для универсальности.
        Этот метод сохранен для backwards compatibility.

        С поддержкой chunking (CR-C6): если messages > chunk_size, разбиваем на чанки.

        Args:
            messages: Список всех сообщений
            wb_count: Количество новостей про Wildberries
            ozon_count: Количество новостей про Ozon
            general_count: Количество общих новостей
            chunk_size: Максимальный размер чанка (по умолчанию 50)

        Returns:
            Dict с ключами 'wildberries', 'ozon', 'general'
        """
        if not messages:
            return {"wildberries": [], "ozon": [], "general": []}

        # CR-C6: Chunking для больших списков сообщений
        if len(messages) <= chunk_size:
            # Малый список: обрабатываем за один запрос
            logger.info(f"Обработка {len(messages)} сообщений для 3 категорий (один запрос)")
            all_categories = self._process_categories_chunk(messages, wb_count, ozon_count, general_count)

            # Применяем компенсацию для малого списка тоже
            all_categories["wildberries"].sort(key=lambda x: x.get("score", 0), reverse=True)
            all_categories["ozon"].sort(key=lambda x: x.get("score", 0), reverse=True)
            all_categories["general"].sort(key=lambda x: x.get("score", 0), reverse=True)

            target_total = wb_count + ozon_count + general_count

            final_categories = {
                "wildberries": all_categories["wildberries"][:wb_count],
                "ozon": all_categories["ozon"][:ozon_count],
                "general": all_categories["general"][:general_count],
            }

            current_total = sum(len(v) for v in final_categories.values())
            shortage = target_total - current_total

            if shortage > 0:
                logger.info(f"Недостаточно новостей: {current_total}/{target_total}. Компенсируем {shortage} из других категорий")

                remaining = []
                remaining.extend(all_categories["wildberries"][wb_count:])
                remaining.extend(all_categories["ozon"][ozon_count:])
                remaining.extend(all_categories["general"][general_count:])

                remaining.sort(key=lambda x: x.get("score", 0), reverse=True)
                compensated = remaining[:shortage]

                for news in compensated:
                    category = news.get('category', 'general')
                    if category in final_categories:
                        final_categories[category].append(news)
                    else:
                        final_categories['general'].append(news)

            wb_len = len(final_categories["wildberries"])
            ozon_len = len(final_categories["ozon"])
            gen_len = len(final_categories["general"])
            total = wb_len + ozon_len + gen_len

            logger.info(
                f"Gemini отобрал: WB={wb_len}, Ozon={ozon_len}, Общие={gen_len}, Всего={total}/{target_total}"
            )

            return final_categories

        # Большой список: разбиваем на чанки
        chunks = self._chunk_list(messages, chunk_size)
        logger.info(
            f"CR-C6: Разбиваем {len(messages)} сообщений на {len(chunks)} чанков по {chunk_size} для 3 категорий"
        )

        # Собираем результаты из всех чанков
        all_categories = {"wildberries": [], "ozon": [], "general": []}

        for i, chunk in enumerate(chunks, 1):
            logger.debug(f"Обработка чанка {i}/{len(chunks)} ({len(chunk)} сообщений)")
            chunk_results = self._process_categories_chunk(
                chunk, wb_count, ozon_count, general_count
            )

            # Объединяем результаты по категориям
            for category_name in ["wildberries", "ozon", "general"]:
                all_categories[category_name].extend(chunk_results.get(category_name, []))

            # Rate limiting: пауза между чанками для соблюдения квоты TPM (32K/min Free Tier)
            if i < len(chunks):
                logger.info(f"⏱️  Rate limiting: пауза 60 секунд перед следующим чанком ({i+1}/{len(chunks)})")
                time.sleep(60)

        # Дедупликация по source_message_id после объединения чанков
        category_counts_3 = {"wildberries": wb_count, "ozon": ozon_count, "general": general_count}
        all_categories = self._deduplicate_by_source_id(all_categories, category_counts_3)

        # Сортируем каждую категорию по score
        all_categories["wildberries"].sort(key=lambda x: x.get("score", 0), reverse=True)
        all_categories["ozon"].sort(key=lambda x: x.get("score", 0), reverse=True)
        all_categories["general"].sort(key=lambda x: x.get("score", 0), reverse=True)

        # КОМПЕНСАЦИЯ: Если какой-то категории не хватает → перераспределяем на другие
        target_total = wb_count + ozon_count + general_count

        # Сначала берём сколько есть из каждой категории
        final_categories = {
            "wildberries": all_categories["wildberries"][:wb_count],
            "ozon": all_categories["ozon"][:ozon_count],
            "general": all_categories["general"][:general_count],
        }

        current_total = sum(len(v) for v in final_categories.values())
        shortage = target_total - current_total

        if shortage > 0:
            logger.info(f"Недостаточно новостей: {current_total}/{target_total}. Компенсируем {shortage} из других категорий")

            # Собираем оставшиеся новости из всех категорий
            remaining = []
            remaining.extend(all_categories["wildberries"][wb_count:])
            remaining.extend(all_categories["ozon"][ozon_count:])
            remaining.extend(all_categories["general"][general_count:])

            # Сортируем по score и берём недостающее количество
            remaining.sort(key=lambda x: x.get("score", 0), reverse=True)
            compensated = remaining[:shortage]

            # Добавляем в соответствующие категории
            for news in compensated:
                # Определяем категорию по source_message_id или по ключевым словам
                category = news.get('category', 'general')
                if category in final_categories:
                    final_categories[category].append(news)
                else:
                    final_categories['general'].append(news)

        wb_len = len(final_categories["wildberries"])
        ozon_len = len(final_categories["ozon"])
        gen_len = len(final_categories["general"])
        total = wb_len + ozon_len + gen_len

        logger.info(
            f"CR-C6: Gemini отобрал топовые новости: WB={wb_len}, Ozon={ozon_len}, Общие={gen_len}, Всего={total}/{target_total} "
            f"из {len(messages)} сообщений ({len(chunks)} чанков)"
        )

        return final_categories
