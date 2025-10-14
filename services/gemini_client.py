"""Клиент для работы с Google Gemini API"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable, Optional

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from utils.logger import setup_logger


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
            text = (msg.get("text") or "")
            snippet = text[:text_limit]
            channel = msg.get("channel_username", "unknown")
            parts.append(
                f"ID: {msg.get('id')}\nКанал: @{channel}\nТекст:\n{snippet}"
            )
        block = "\n\n".join(parts)
        return self._escape_braces(block)

    def _log_api_call(self, method_name: str, prompt: str, response_text: str, duration: float):
        """
        Детальное логирование вызова Gemini API

        Args:
            method_name: Название метода
            prompt: Отправленный промпт
            response_text: Полученный ответ
            duration: Время выполнения в секундах
        """
        # Логируем метаданные
        logger.info(
            f"[Gemini] {method_name}: промпт {len(prompt)} символов, "
            f"ответ {len(response_text)} символов, время {duration:.2f}s"
        )

        # Логируем промпт (с ограничением)
        max_log_length = 2000
        if len(prompt) <= max_log_length:
            logger.debug(f"[Gemini] {method_name} ПРОМПТ:\n{prompt}")
        else:
            logger.debug(
                f"[Gemini] {method_name} ПРОМПТ (обрезан до {max_log_length} символов):\n"
                f"{prompt[:max_log_length]}..."
            )

        # Логируем полный ответ (с ограничением)
        if len(response_text) <= max_log_length:
            logger.debug(f"[Gemini] {method_name} ОТВЕТ:\n{response_text}")
        else:
            logger.debug(
                f"[Gemini] {method_name} ОТВЕТ (обрезан до {max_log_length} символов):\n"
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
            return selected[:top_n]

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
                    item[
                        "source_link"
                    ] = f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
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

    def _process_marketplace_chunk(
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
        messages_block = self._build_messages_block(messages)

        prompt = self._render_prompt(
            "select_and_format_marketplace_news",
            DEFAULT_SELECT_MARKETPLACE_NEWS_PROMPT,
            top_n=chunk_top_n,
            messages_block=messages_block,
            display_name=marketplace_display_name,
            marketplace=marketplace,
        )

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # Детальное логирование
            self._log_api_call(
                f"select_marketplace_news[{marketplace}]", prompt, result_text, duration
            )

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
                    item[
                        "source_link"
                    ] = f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                    item["source_message_id"] = msg_id
                    item["source_channel_id"] = msg["channel_id"]
                    item["text"] = msg["text"]
                    item["marketplace"] = marketplace

            logger.debug(
                f"Chunk: отобрано {len(selected)} новостей из {len(messages)} сообщений"
            )
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
            logger.info(
                f"Обработка {len(messages)} сообщений для {marketplace} (один запрос)"
            )
            return self._process_marketplace_chunk(messages, marketplace, top_n, display_name)

        # Большой список: разбиваем на чанки
        chunks = self._chunk_list(messages, chunk_size)
        logger.info(
            f"CR-C6: Разбиваем {len(messages)} сообщений на {len(chunks)} чанков по {chunk_size} для {marketplace}"
        )

        all_selected = []
        for i, chunk in enumerate(chunks, 1):
            logger.debug(f"Обработка чанка {i}/{len(chunks)} ({len(chunk)} сообщений)")
            chunk_results = self._process_marketplace_chunk(
                chunk, marketplace, top_n, display_name
            )
            all_selected.extend(chunk_results)

        # Сортируем по score и берем top_n
        all_selected.sort(key=lambda x: x.get("score", 0), reverse=True)
        final_results = all_selected[:top_n]

        logger.info(
            f"CR-C6: Gemini отобрал {len(final_results)} топовых новостей для {marketplace} из {len(messages)} сообщений ({len(chunks)} чанков)"
        )

        return final_results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    def select_three_categories(
        self, messages: list[dict], wb_count: int = 5, ozon_count: int = 5, general_count: int = 5
    ) -> dict[str, list[dict]]:
        """
        Отбор новостей по 3 категориям: Wildberries, Ozon, Общие

        Args:
            messages: Список всех сообщений
            wb_count: Количество новостей про Wildberries
            ozon_count: Количество новостей про Ozon
            general_count: Количество общих новостей

        Returns:
            Dict с ключами 'wildberries', 'ozon', 'general'
        """
        if not messages:
            return {"wildberries": [], "ozon": [], "general": []}

        messages_block = self._build_messages_block(messages)

        prompt = self._render_prompt(
            "select_three_categories",
            DEFAULT_SELECT_THREE_CATEGORIES_PROMPT,
            wb_count=wb_count,
            ozon_count=ozon_count,
            general_count=general_count,
            messages_block=messages_block,
        )

        try:
            start_time = time.time()
            model = self._ensure_model()
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            duration = time.time() - start_time

            # Детальное логирование
            self._log_api_call("select_three_categories", prompt, result_text, duration)

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
                logger.error(f"Ошибка валидации JSON от Gemini (3 категории): {e}")
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
                        item[
                            "source_link"
                        ] = f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                        item["source_message_id"] = msg_id
                        item["source_channel_id"] = msg["channel_id"]
                        item["text"] = msg["text"]
                        item["category"] = category_name

            wb_len = len(categories.get("wildberries", []))
            ozon_len = len(categories.get("ozon", []))
            gen_len = len(categories.get("general", []))

            logger.info(f"Gemini отобрал новости: WB={wb_len}, Ozon={ozon_len}, Общие={gen_len}")

            return categories

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini (3 категории): {e}")
            logger.error(f"Текст ответа: {result_text}")
            return {"wildberries": [], "ozon": [], "general": []}
        except Exception as e:
            logger.error(f"Ошибка при отборе новостей (3 категории): {e}")
            return {"wildberries": [], "ozon": [], "general": []}
