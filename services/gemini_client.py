"""Клиент для работы с Google Gemini API"""
import google.generativeai as genai
import json
from typing import List, Dict, Optional
from utils.logger import setup_logger

logger = setup_logger(__name__)


class GeminiClient:
    """Клиент для работы с Gemini API"""

    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        """
        Инициализация Gemini клиента

        Args:
            api_key: API ключ Google Gemini
            model_name: Название модели
        """
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        logger.info(f"Gemini клиент инициализирован: {model_name}")

    def select_top_news(self, messages: List[Dict], top_n: int = 10) -> List[Dict]:
        """
        Отобрать ТОП-N самых интересных новостей про AI

        Args:
            messages: Список сообщений с полями {id, text, channel}
            top_n: Количество новостей для отбора

        Returns:
            Список отобранных новостей с оценками
        """
        if not messages:
            return []

        # Формируем промпт
        messages_text = "\n\n".join([
            f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
            for msg in messages
        ])

        prompt = f"""Ты - эксперт по новостям про искусственный интеллект.

Проанализируй следующие сообщения из Telegram каналов и отбери ТОП-{top_n} самых важных и интересных новостей.

КРИТЕРИИ ОТБОРА (в порядке приоритета):

ВЫСОКИЙ ПРИОРИТЕТ (оценка 9-10):
✅ Новости и обновления моделей (GPT-5, Claude, Gemini, Perplexity, Grok)
✅ Новые инструменты и функции в AI-продуктах

СРЕДНИЙ ПРИОРИТЕТ (оценка 7-8):
✅ Интересные кейсы использования AI
✅ Забавные применения AI

НИЗКИЙ ПРИОРИТЕТ (оценка 5-6):
✅ Бесплатные обучения от крупных игроков (OpenAI, Google, Anthropic)
✅ Научные прорывы, SOTA результаты

ОБЯЗАТЕЛЬНО ИСКЛЮЧИТЬ:
❌ Рекламу платных курсов, продуктов, услуг
❌ Мемы без практической ценности
❌ Политику без AI контекста
❌ Повторяющиеся темы (если одна и та же новость в разных каналах - выбери лучшее описание)
❌ Общие рассуждения без конкретики

СООБЩЕНИЯ:

{messages_text}

Верни JSON массив с ТОП-{top_n} новостями в формате:
[
  {{"id": номер_ID_из_списка, "score": оценка_от_1_до_10, "reason": "краткая причина отбора на русском"}},
  ...
]

Верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            # Логируем ответ для отладки
            logger.debug(f"Gemini ответ (первые 500 символов): {result_text[:500]}")

            # Извлекаем JSON из ответа (иногда Gemini добавляет ```json```)
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            # Пытаемся найти JSON массив с помощью регулярки если прямой парсинг не работает
            if not result_text.startswith("["):
                import re
                json_match = re.search(r'\[[\s\S]*\]', result_text)
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
            return []

    def format_news_post(self, text: str, channel: str, message_link: str = None) -> Optional[Dict]:
        """
        Отформатировать новость в структурированный формат

        Args:
            text: Исходный текст новости
            channel: Канал-источник
            message_link: Ссылка на оригинальное сообщение

        Returns:
            Dict с полями: title, description, source_link
        """
        prompt = f"""Проанализируй эту новость про AI и создай структурированное описание.

ИСХОДНАЯ НОВОСТЬ:
{text}

ЗАДАЧА:
Создай JSON с полями:
1. "title" - заголовок в 5-10 слов, начинающийся с темы (БЕЗ эмодзи)
2. "description" - описание в 2-4 предложениях с конкретными фактами

ПРАВИЛА:
- Заголовок без эмодзи, кратко и по делу
- Описание: конкретика, факты, цифры
- Пиши на русском, простым языком
- Без воды и хайпа

ПРИМЕР ПРАВИЛЬНОГО ОТВЕТА:
{{
  "title": "ANUS - опенсорсный клон Manus AI, созданный самой системой",
  "description": "Пользователь попросил Manus создать свою версию с открытым исходным кодом, в результате появился ANUS (Autonomous Networked Utility System) - полностью функциональный агентный фреймворк с идентичным функционалом. Проект доступен на GitHub и показывает уязвимость систем на базе LLM."
}}

Верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            # Извлекаем JSON из ответа
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            formatted = json.loads(result_text)

            # Добавляем ссылку на источник
            formatted['source_link'] = message_link if message_link else f"https://t.me/{channel}"

            return formatted

        except Exception as e:
            logger.error(f"Ошибка форматирования поста через Gemini: {e}")
            return None

    def select_and_format_news(self, messages: List[Dict], top_n: int = 10) -> List[Dict]:
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
        messages_text = "\n\n".join([
            f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
            for msg in messages
        ])

        prompt = f"""Ты - эксперт по новостям про искусственный интеллект.

Проанализируй следующие сообщения из Telegram каналов, отбери ТОП-{top_n} самых важных новостей И СРАЗУ отформатируй их.

КРИТЕРИИ ОТБОРА (в порядке приоритета):

ВЫСОКИЙ ПРИОРИТЕТ (оценка 9-10):
✅ Новости и обновления моделей (GPT-5, Claude, Gemini, Perplexity, Grok)
✅ Новые инструменты и функции в AI-продуктах

СРЕДНИЙ ПРИОРИТЕТ (оценка 7-8):
✅ Интересные кейсы использования AI
✅ Забавные применения AI

НИЗКИЙ ПРИОРИТЕТ (оценка 5-6):
✅ Бесплатные обучения от крупных игроков (OpenAI, Google, Anthropic)
✅ Научные прорывы, SOTA результаты

ОБЯЗАТЕЛЬНО ИСКЛЮЧИТЬ:
❌ Рекламу платных курсов, продуктов, услуг
❌ Мемы без практической ценности
❌ Политику без AI контекста
❌ Повторяющиеся темы (если одна и та же новость в разных каналах - выбери лучшее описание)
❌ Общие рассуждения без конкретики

СООБЩЕНИЯ:

{messages_text}

Верни JSON массив с ТОП-{top_n} новостями в формате:
[
  {{
    "id": номер_ID_из_списка,
    "score": оценка_от_1_до_10,
    "reason": "краткая причина отбора на русском",
    "title": "Заголовок в 5-10 слов БЕЗ эмодзи",
    "description": "Описание в 2-4 предложениях с конкретными фактами"
  }},
  ...
]

ПРАВИЛА ФОРМАТИРОВАНИЯ:
- Заголовок без эмодзи, кратко и по делу
- Описание: конкретика, факты, цифры
- Пиши на русском, простым языком
- Без воды и хайпа

Верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            # Логируем ответ для отладки
            logger.debug(f"Gemini ответ (первые 500 символов): {result_text[:500]}")

            # Извлекаем JSON из ответа
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            # Пытаемся найти JSON массив с помощью регулярки
            if not result_text.startswith("["):
                import re
                json_match = re.search(r'\[[\s\S]*\]', result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON массив в ответе Gemini: {result_text}")
                    return []

            selected = json.loads(result_text)

            # Добавляем source_link к каждой новости
            messages_dict = {msg['id']: msg for msg in messages}
            for item in selected:
                msg_id = item['id']
                if msg_id in messages_dict:
                    msg = messages_dict[msg_id]
                    item['source_link'] = f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                    item['source_message_id'] = msg_id
                    item['source_channel_id'] = msg['channel_id']
                    item['text'] = msg['text']  # Для embeddings

            logger.info(f"Gemini отобрал и отформатировал {len(selected)} новостей из {len(messages)}")
            return selected[:top_n]

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini: {e}")
            logger.error(f"Текст ответа: {result_text}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при отборе и форматировании новостей через Gemini: {e}")
            return []

    def is_spam_or_ad(self, text: str) -> bool:
        """
        Проверить, является ли текст спамом или рекламой

        Args:
            text: Текст для проверки

        Returns:
            True если это спам/реклама
        """
        prompt = f"""Определи, является ли это сообщение рекламой, спамом или мусором.

ТЕКСТ:
{text[:500]}

Ответь ТОЛЬКО одним словом: "ДА" (если это реклама/спам) или "НЕТ" (если это полезная информация про AI)."""

        try:
            response = self.model.generate_content(prompt)
            answer = response.text.strip().upper()
            return "ДА" in answer

        except Exception as e:
            logger.error(f"Ошибка проверки на спам: {e}")
            return False

    def select_and_format_marketplace_news(
        self,
        messages: List[Dict],
        marketplace: str,
        top_n: int = 10
    ) -> List[Dict]:
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
        marketplace_upper = marketplace.upper()

        messages_text = "\n\n".join([
            f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
            for msg in messages
        ])

        prompt = f"""Ты - эксперт по маркетплейсу {marketplace_upper}.

Проанализируй следующие сообщения из Telegram каналов про маркетплейсы, отбери ТОП-{top_n} самых важных новостей про {marketplace_upper} И СРАЗУ отформатируй их.

КРИТЕРИИ ОТБОРА (в порядке приоритета):

ВЫСОКИЙ ПРИОРИТЕТ (оценка 9-10):
✅ Изменения в работе {marketplace_upper} (новые правила, комиссии, функции)
✅ Официальные обновления от {marketplace_upper}
✅ Важные новости для продавцов (изменения в аналитике, продвижении, выплатах)
✅ Юридические изменения (законы, регуляции)

СРЕДНИЙ ПРИОРИТЕТ (оценка 7-8):
✅ Кейсы успешных продавцов на {marketplace_upper}
✅ Новые инструменты и сервисы для {marketplace_upper}
✅ Тренды и аналитика продаж
✅ Важные лайфхаки и советы

НИЗКИЙ ПРИОРИТЕТ (оценка 5-6):
✅ Общие советы по продажам
✅ Статистика и исследования рынка
✅ Второстепенные новости

ОБЯЗАТЕЛЬНО ИСКЛЮЧИТЬ:
❌ Рекламу платных курсов, менторства, консультаций
❌ Продажу аккаунтов, товаров, услуг
❌ Мемы без практической ценности
❌ Общие рассуждения без конкретики
❌ Повторяющиеся темы
❌ Новости про ДРУГИЕ маркетплейсы (не {marketplace_upper})

ВАЖНО: Отбирай ТОЛЬКО новости про {marketplace_upper}! Если упоминается Wildberries а нужен Ozon - не включай. И наоборот.

СООБЩЕНИЯ:
{messages_text}

Верни результат СТРОГО в формате JSON массива:
[
  {{
    "id": <ID сообщения>,
    "title": "<Короткий заголовок 5-7 слов>",
    "description": "<Описание 2-3 предложения>",
    "score": <число от 1 до 10>,
    "reason": "<Краткое объяснение почему важно>"
  }}
]

Верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            logger.debug(f"Ответ Gemini (маркетплейс {marketplace}): {result_text[:500]}")

            # Удаляем markdown разметку если есть
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            # Пытаемся найти JSON массив
            if not result_text.startswith("["):
                json_match = re.search(r'\[[\s\S]*\]', result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON в ответе Gemini: {result_text}")
                    return []

            selected = json.loads(result_text)

            # Добавляем дополнительные поля
            messages_dict = {msg['id']: msg for msg in messages}
            for item in selected:
                msg_id = item['id']
                if msg_id in messages_dict:
                    msg = messages_dict[msg_id]
                    item['source_link'] = f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                    item['source_message_id'] = msg_id
                    item['source_channel_id'] = msg['channel_id']
                    item['text'] = msg['text']
                    item['marketplace'] = marketplace

            logger.info(f"Gemini отобрал {len(selected)} новостей для {marketplace} из {len(messages)}")
            return selected[:top_n]

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini ({marketplace}): {e}")
            logger.error(f"Текст ответа: {result_text}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при отборе новостей для {marketplace}: {e}")
            return []

    def select_three_categories(
        self,
        messages: List[Dict],
        wb_count: int = 5,
        ozon_count: int = 5,
        general_count: int = 5
    ) -> Dict[str, List[Dict]]:
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
            return {'wildberries': [], 'ozon': [], 'general': []}

        messages_text = "\n\n".join([
            f"ID: {msg['id']}\nКанал: @{msg.get('channel_username', 'unknown')}\nТекст:\n{msg['text'][:500]}"
            for msg in messages
        ])

        prompt = f"""Ты - эксперт по маркетплейсам (Wildberries и Ozon).

Проанализируй следующие сообщения из Telegram каналов про маркетплейсы и отбери новости по 3 категориям:

📦 КАТЕГОРИЯ 1: WILDBERRIES ({wb_count} новостей)
Новости ТОЛЬКО про Wildberries (включая "WB", "ВБ", "вайлдберриз")

📦 КАТЕГОРИЯ 2: OZON ({ozon_count} новостей)
Новости ТОЛЬКО про Ozon (включая "озон")

📦 КАТЕГОРИЯ 3: ОБЩИЕ ({general_count} новостей)
- Новости касающиеся ОБОИХ маркетплейсов
- Общие изменения в законодательстве для всех маркетплейсов
- Советы применимые к любому маркетплейсу
- Тренды рынка маркетплейсов в целом

КРИТЕРИИ ОТБОРА (в порядке приоритета):

ВЫСОКИЙ ПРИОРИТЕТ (оценка 9-10):
✅ Изменения в работе платформы (новые правила, комиссии, функции)
✅ Официальные обновления
✅ Важные новости для продавцов (изменения в аналитике, продвижении, выплатах)
✅ Юридические изменения (законы, регуляции)
✅ Обновления платформы от правительства

СРЕДНИЙ ПРИОРИТЕТ (оценка 7-8):
✅ Кейсы успешных продавцов
✅ Новые инструменты и сервисы
✅ Тренды и аналитика продаж
✅ Важные лайфхаки и советы от экспертов

НИЗКИЙ ПРИОРИТЕТ (оценка 5-6):
✅ Общие советы по продажам
✅ Статистика и исследования рынка
✅ Второстепенные новости

ОБЯЗАТЕЛЬНО ИСКЛЮЧИТЬ:
❌ Рекламу платных курсов, менторства, консультаций, вебинаров
❌ Продажу аккаунтов, товаров, услуг
❌ Мемы без практической ценности
❌ Общие рассуждения без конкретики
❌ Повторяющиеся темы

СООБЩЕНИЯ:
{messages_text}

Верни результат СТРОГО в формате JSON объекта с тремя массивами:
{{
  "wildberries": [
    {{
      "id": <ID сообщения>,
      "title": "<Заголовок 5-7 слов>",
      "description": "<Описание 2-3 предложения>",
      "score": <число от 1 до 10>,
      "reason": "<Почему важно>"
    }}
  ],
  "ozon": [
    {{
      "id": <ID сообщения>,
      "title": "<Заголовок 5-7 слов>",
      "description": "<Описание 2-3 предложения>",
      "score": <число от 1 до 10>,
      "reason": "<Почему важно>"
    }}
  ],
  "general": [
    {{
      "id": <ID сообщения>,
      "title": "<Заголовок 5-7 слов>",
      "description": "<Описание 2-3 предложения>",
      "score": <число от 1 до 10>,
      "reason": "<Почему важно>"
    }}
  ]
}}

ВАЖНО:
- Wildberries: отбирай ТОЛЬКО новости где упоминается Wildberries/WB/ВБ
- Ozon: отбирай ТОЛЬКО новости где упоминается Ozon/Озон
- General: новости про оба маркетплейса ИЛИ общие для всех
- Не дублируй: одна новость только в ОДНОЙ категории
- Сортируй по важности (score) внутри каждой категории

Верни ТОЛЬКО JSON, без дополнительного текста."""

        try:
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            logger.debug(f"Ответ Gemini (3 категории): {result_text[:500]}")

            # Удаляем markdown разметку
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()

            # Пытаемся найти JSON объект
            if not result_text.startswith("{"):
                json_match = re.search(r'\{[\s\S]*\}', result_text)
                if json_match:
                    result_text = json_match.group(0)
                else:
                    logger.error(f"Не удалось найти JSON в ответе Gemini: {result_text}")
                    return {'wildberries': [], 'ozon': [], 'general': []}

            categories = json.loads(result_text)

            # Добавляем дополнительные поля к каждой новости
            messages_dict = {msg['id']: msg for msg in messages}

            for category_name in ['wildberries', 'ozon', 'general']:
                if category_name not in categories:
                    categories[category_name] = []

                for item in categories[category_name]:
                    msg_id = item['id']
                    if msg_id in messages_dict:
                        msg = messages_dict[msg_id]
                        item['source_link'] = f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                        item['source_message_id'] = msg_id
                        item['source_channel_id'] = msg['channel_id']
                        item['text'] = msg['text']
                        item['category'] = category_name

            wb_len = len(categories.get('wildberries', []))
            ozon_len = len(categories.get('ozon', []))
            gen_len = len(categories.get('general', []))

            logger.info(f"Gemini отобрал новости: WB={wb_len}, Ozon={ozon_len}, Общие={gen_len}")

            return categories

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON от Gemini (3 категории): {e}")
            logger.error(f"Текст ответа: {result_text}")
            return {'wildberries': [], 'ozon': [], 'general': []}
        except Exception as e:
            logger.error(f"Ошибка при отборе новостей (3 категории): {e}")
            return {'wildberries': [], 'ozon': [], 'general': []}
