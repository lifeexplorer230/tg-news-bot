"""Клиент для работы с Google Gemini API"""

from __future__ import annotations

import json
import re
import threading
import time

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


class GeminiClient:
    """Клиент для работы с Gemini API"""

    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        """
        Инициализация Gemini клиента без мгновенной загрузки модели

        Args:
            api_key: API ключ Google Gemini
            model_name: Название модели
        """
        self.api_key = api_key
        self.model_name = model_name
        self._model: genai.GenerativeModel | None = None

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
        messages_text = "\n\n".join(
            [
                f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
                for msg in messages
            ]
        )

        prompt = f"""Ты — редактор новостного дайджеста про маркетплейсы (Ozon, Wildberries, Яндекс.Маркет, KazanExpress и др.).

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

{messages_text}

Верни JSON массив с ТОП-{top_n} новостями в формате:
[
  {{"id": номер_ID_из_списка, "score": оценка_от_1_до_10, "reason": "кратко, почему важно"}},
  ...
]

Верни ТОЛЬКО JSON, без дополнительного текста."""

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
        prompt = f"""Сформируй структурированное описание новости для продавцов маркетплейсов.

ИСХОДНАЯ НОВОСТЬ:
{text}

СОЗДАЙ JSON С ПОЛЯМИ:
1. "title" — 5-10 слов без эмодзи; сразу отражает суть изменений.
2. "description" — 2-4 предложения с фактами: что изменилось, для кого, какие даты/цифры.

ПРАВИЛА:
- Никаких хайповых заголовков, только конкретика.
- Укажи суммы, проценты, дедлайны, если они есть.
- Пиши на русском, простыми предложениями.
- Не повторяй текст целиком, сделай выжимку.

ПРИМЕР:
{{
  "title": "Ozon вводит плату за хранение крупногабарита",
  "description": "С 1 ноября Ozon начнёт списывать 30 ₽ в сутки за хранение товаров крупнее 120 см на ФБО после 7 дней. Продавцам стоит сократить запасы на складе или использовать FBS, чтобы избежать дополнительной комиссии."
}}

Верни ТОЛЬКО JSON, без дополнительного текста."""

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
            formatted["source_link"] = message_link if message_link else f"https://t.me/{channel}"

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

        # Формируем промпт
        messages_text = "\n\n".join(
            [
                f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
                for msg in messages
            ]
        )

        prompt = f"""Ты — редактор маркетплейс-дайджеста. Отбери и оформи ТОП-{top_n} новостей, которые дают продавцам практическую пользу.

КРИТЕРИИ ОТБОРА:

ВЫСОКИЙ ПРИОРИТЕТ (оценка 9-10):
✅ Правила, комиссии, договоры, штрафы, которые меняют работу селлеров
✅ Логистика, доставка, возвраты, SLA складов
✅ Запуск инструментов (реклама, аналитика, витрины), изменения тарифов
✅ Официальные письма от маркетплейса, ФНС, Минпромторга, влияющие на торговлю

СРЕДНИЙ ПРИОРИТЕТ (оценка 7-8):
✅ Кейсы селлеров с цифрами, работающие связки
✅ Аналитика рынка, сезонность, тренды категорий
✅ Программы поддержки, кредиты, льготы, акции маркетплейса

НИЗКИЙ ПРИОРИТЕТ (оценка 5-6):
✅ Обучающие материалы с конкретными шагами
✅ Разборы карточек, инструменты повышения конверсии

ИСКЛЮЧАЙ:
❌ Рекламу курсов/менторства/агентств
❌ Фантазии «как заработать миллион» без фактов
❌ Продажу аккаунтов, услуги накрутки
❌ Мемы, оффтоп, новости не про e-commerce

СООБЩЕНИЯ:

{messages_text}

Верни JSON массив с ТОП-{top_n} новостями в формате:
[
  {{
    "id": номер_ID_из_списка,
    "score": оценка_от_1_до_10,
    "reason": "почему важно",
    "title": "Заголовок 5-10 слов без эмодзи",
    "description": "2-4 предложения: что изменилось, кому важно, какие цифры"
  }},
  ...
]

Пиши на русском. Верни ТОЛЬКО JSON, без дополнительного текста."""

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
    ) -> list[dict]:
        """
        Отбор и форматирование новостей для маркетплейсов (Ozon, Wildberries)

        Args:
            messages: Список сообщений уже отфильтрованных по ключевым словам
            marketplace: Название маркетплейса (ozon или wildberries)
            top_n: Количество новостей для отбора

        Returns:
            Список отформатированных новостей
        """
        if not messages:
            return []

        # Формируем промпт в зависимости от маркетплейса
        display_name = marketplace_display_name or marketplace.replace("_", " ").title()

        messages_text = "\n\n".join(
            [
                f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
                for msg in messages
            ]
        )

        prompt = f"""Ты — редактор новостей маркетплейса {display_name}.

Проанализируй сообщения и выбери ТОП-{top_n} материалов строго про {display_name}. Сразу оформи их для дайджеста.

КРИТЕРИИ (по убыванию важности):

ВЫСОКИЙ ПРИОРИТЕТ (оценка 9-10):
✅ Правила, комиссии, штрафы, которые вводит {display_name}
✅ Изменения в выплатах, логистике, поставках, маркетинговых инструментах
✅ Официальные письма/сообщения {display_name} или государственных органов
✅ Технические сбои/обновления, влияющие на продажи

СРЕДНИЙ ПРИОРИТЕТ (оценка 7-8):
✅ Кейсы селлеров с цифрами именно на {display_name}
✅ Появление новых сервисов, бонусов, льгот для продавцов
✅ Аналитика продаж и спроса внутри площадки

НИЗКИЙ ПРИОРИТЕТ (оценка 5-6):
✅ Полезные инструкции и советы с конкретными шагами
✅ Разборы карточек, рекламных кампаний, повышающих конверсию

ОБЯЗАТЕЛЬНО ИСКЛЮЧИ:
❌ Рекламу платных курсов и «разбогатеешь за неделю»
❌ Новости про другие площадки
❌ Общие рассуждения без фактов
❌ Продажу аккаунтов, услуги накрутки, спам

СООБЩЕНИЯ:
{messages_text}

Верни JSON массив в формате:
[
  {{
    "id": <ID сообщения>,
    "title": "Заголовок 5-7 слов без эмодзи",
    "description": "2-3 предложения с фактами",
    "score": <число от 1 до 10>,
    "reason": "почему важно для продавцов {display_name}"
  }}
]

Верни ТОЛЬКО JSON, без дополнительного текста."""

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

            logger.info(
                f"Gemini отобрал {len(selected)} новостей для {marketplace} из {len(messages)}"
            )
            return selected[:top_n]

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini ({marketplace}): {e}")
            logger.error(f"Текст ответа: {result_text}")
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

        messages_text = "\n\n".join(
            [
                f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
                for msg in messages
            ]
        )

        prompt = f"""Ты — редактор сводного отчёта по маркетплейсам. Разложи новости по категориям:

📦 WILDBERRIES ({wb_count}) — всё, что касается продавцов Wildberries (WB, ВБ, вайлдберриз).
📦 OZON ({ozon_count}) — только новости про Ozon.
📦 ОБЩИЕ ({general_count}) — законодательство, логистика, тренды, которые влияют сразу на оба маркетплейса или отрасль в целом.

ВЫСОКИЙ ПРИОРИТЕТ (9-10):
✅ Новые правила, комиссии, изменения в договорах
✅ Обновления логистики, складов, возвратов, выплат
✅ Официальные письма площадок или государства

СРЕДНИЙ ПРИОРИТЕТ (7-8):
✅ Кейсы с конкретными цифрами
✅ Новые инструменты продвижения, программы поддержки
✅ Аналитика спроса и продаж

НИЗКИЙ ПРИОРИТЕТ (5-6):
✅ Обучающие материалы с чёткими шагами
✅ Практические советы, повышающие продажи

ИСКЛЮЧИ:
❌ Рекламу курсов, наставников, агентств
❌ Мемы, мотивационные посты без фактов
❌ Продажу аккаунтов, услуги накрутки, спам

СООБЩЕНИЯ:
{messages_text}

Верни JSON-объект вида:
{{
  "wildberries": [{{"id": ..., "title": "...", "description": "...", "score": ..., "reason": "..."}}],
  "ozon": [...],
  "general": [...]
}}

Требования:
- Новость может появиться только в одной категории.
- Заголовок 5-7 слов, без эмодзи, по делу.
- Описание 2-3 предложения с фактами (что изменилось, кому полезно, даты/цифры).
- "reason" объясняет, почему эта новость важна продавцам.

Верни ТОЛЬКО JSON, без дополнительного текста."""

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
