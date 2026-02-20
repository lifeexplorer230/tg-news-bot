"""Клиент для работы с Anthropic Claude API для отбора и категоризации новостей."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Callable, Optional

import anthropic
from pydantic import ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from services.gemini_client import NewsItem, DynamicCategoryNews
from utils.formatters import sanitize_for_prompt
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Маркер разделения system/user в промпте
PROMPT_SPLIT_MARKER = "---SPLIT---"


class ClaudeNewsClient:
    """Синхронный клиент Claude API для отбора новостей."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        prompt_loader: Optional[Callable[[str], Optional[str]]] = None,
    ):
        if api_key.startswith("sk-ant-oat"):
            import os
            saved = os.environ.pop("ANTHROPIC_API_KEY", None)
            self.client = anthropic.Anthropic(
                auth_token=api_key,
                default_headers={
                    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
                    "user-agent": "claude-cli/2.1.2 (external, cli)",
                    "x-app": "cli",
                },
            )
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved
        else:
            self.client = anthropic.Anthropic(api_key=api_key)

        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._prompt_loader = prompt_loader
        self._prompt_cache: dict[str, str] = {}

        # Token tracking
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0

        logger.info("Claude клиент инициализирован: %s", self.model)

    # ------------------------------------------------------------------
    # Prompt management (same pattern as GeminiClient)
    # ------------------------------------------------------------------

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

    def _build_messages_block(self, messages: list[dict], text_limit: int = 1500) -> str:
        parts = []
        for msg in messages:
            text = msg.get("text") or ""
            snippet = sanitize_for_prompt(text, max_length=text_limit)
            channel = msg.get("channel_username", "unknown")
            parts.append(f"ID: {msg.get('id')}\nКанал: @{channel}\nТекст:\n{snippet}")
        block = "\n\n".join(parts)
        return self._escape_braces(block)

    @staticmethod
    def _generate_request_id() -> str:
        return str(uuid.uuid4())[:8]

    # ------------------------------------------------------------------
    # Core API call
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        )),
        reraise=True,
    )
    def _complete(
        self,
        system: str,
        user_message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Синхронный вызов Claude API."""
        start_time = time.time()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature if temperature is not None else self.temperature,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        duration = time.time() - start_time

        inp = response.usage.input_tokens
        out = response.usage.output_tokens
        self._total_input_tokens += inp
        self._total_output_tokens += out

        # Cost estimation (Sonnet 4.6 pricing: $3/MTok input, $15/MTok output)
        cost = (inp * 3 + out * 15) / 1_000_000
        self._total_cost_usd += cost

        result_text = response.content[0].text

        logger.info(
            "[Claude] %d in / %d out tokens, %.2fs, $%.4f (session total: $%.4f)",
            inp, out, duration, cost, self._total_cost_usd,
        )

        return result_text

    # ------------------------------------------------------------------
    # JSON extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> str:
        """Извлечь JSON из ответа Claude (markdown code blocks, raw JSON, etc)."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        if not text.startswith("{"):
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                text = match.group(0)
        return text

    # ------------------------------------------------------------------
    # Category quota enforcement
    # ------------------------------------------------------------------

    def _apply_category_quotas(
        self,
        all_categories: dict[str, list[dict]],
        category_counts: dict[str, int],
    ) -> dict[str, list[dict]]:
        """
        Распределяет новости по категориям с соблюдением квот.
        Шаг 1: берём min(available, quota) из каждой категории (по score).
        Шаг 2: остаток слотов заполняем лучшими новостями из surplus-категорий.
        """
        # Сортируем каждую категорию по score
        for cat in all_categories:
            all_categories[cat].sort(key=lambda x: x.get("score", 0), reverse=True)

        final: dict[str, list[dict]] = {cat: [] for cat in category_counts}
        surplus: list[dict] = []

        # Шаг 1: берём квоту из каждой категории
        for cat, quota in category_counts.items():
            available = all_categories.get(cat, [])
            final[cat] = list(available[:quota])
            surplus.extend(available[quota:])

        # Шаг 2: если какая-то категория недобрала — заполняем из surplus
        total_filled = sum(len(v) for v in final.values())
        total_target = sum(category_counts.values())
        remaining_slots = total_target - total_filled

        if remaining_slots > 0 and surplus:
            surplus.sort(key=lambda x: x.get("score", 0), reverse=True)
            for news in surplus:
                if remaining_slots <= 0:
                    break
                # Найти первую категорию с незаполненной квотой
                for cat, quota in category_counts.items():
                    if len(final[cat]) < quota:
                        news["category"] = cat
                        final[cat].append(news)
                        remaining_slots -= 1
                        break

        return final

    # ------------------------------------------------------------------
    # Main method: select_by_categories
    # ------------------------------------------------------------------

    def select_by_categories(
        self,
        messages: list[dict],
        category_counts: dict[str, int],
        chunk_size: int = 200,
        recently_published: list[str] | None = None,
        category_descriptions: dict[str, str] | None = None,
    ) -> dict[str, list[dict]]:
        """
        Универсальный отбор новостей по категориям.
        Интерфейс-совместимый с GeminiClient.select_by_categories().
        """
        if not messages:
            return {cat: [] for cat in category_counts.keys()}

        if len(messages) <= chunk_size:
            logger.info(
                "Обработка %d сообщений для категорий %s (один запрос)",
                len(messages), list(category_counts.keys()),
            )
            all_categories = self._process_dynamic_categories_chunk(
                messages, category_counts, recently_published, category_descriptions
            )

            # Помечаем каждую новость её категорией
            for cat_name, news_list in all_categories.items():
                for news in news_list:
                    news["category"] = cat_name

            final_categories = self._apply_category_quotas(all_categories, category_counts)

            counts_str = ", ".join(
                f"{cat}={len(items)}" for cat, items in final_categories.items()
            )
            logger.info("Отобрано (по квотам): %s", counts_str)
            return final_categories

        # Chunking для больших списков
        chunks = self._chunk_list(messages, chunk_size)
        logger.info(
            "Разбиваем %d сообщений на %d чанков по %d для категорий %s",
            len(messages), len(chunks), chunk_size, list(category_counts.keys()),
        )

        all_categories: dict[str, list[dict]] = {cat: [] for cat in category_counts.keys()}

        for i, chunk in enumerate(chunks, 1):
            logger.debug("Обработка чанка %d/%d (%d сообщений)", i, len(chunks), len(chunk))
            chunk_results = self._process_dynamic_categories_chunk(
                chunk, category_counts, recently_published, category_descriptions
            )
            for cat_name in category_counts:
                all_categories[cat_name].extend(chunk_results.get(cat_name, []))

            # Rate limiting between chunks (Claude has higher limits than Gemini)
            if i < len(chunks):
                logger.info("Пауза 5 секунд перед чанком %d/%d", i + 1, len(chunks))
                time.sleep(5)

        # Deduplicate by source_message_id
        all_categories = self._deduplicate_by_source_id(all_categories, category_counts)

        # Помечаем каждую новость её категорией
        for cat_name, news_list in all_categories.items():
            for news in news_list:
                news["category"] = cat_name

        final_categories = self._apply_category_quotas(all_categories, category_counts)

        counts_str = ", ".join(
            f"{cat}={len(items)}" for cat, items in final_categories.items()
        )
        logger.info(
            "Claude отобрал: %s из %d сообщений (топ-%d)",
            counts_str, len(messages), sum(category_counts.values()),
        )
        return final_categories

    # ------------------------------------------------------------------
    # Chunk processing
    # ------------------------------------------------------------------

    def _process_dynamic_categories_chunk(
        self,
        messages: list[dict],
        category_counts: dict[str, int],
        recently_published: list[str] | None = None,
        category_descriptions: dict[str, str] | None = None,
    ) -> dict[str, list[dict]]:
        """Обработать один чанк сообщений через Claude API."""
        request_id = self._generate_request_id()
        messages_block = self._build_messages_block(messages)

        # Формируем описание категорий
        categories_description = []
        json_structure_lines = []
        emojis = ["📦", "🔔", "📊", "🎮", "🎬", "🪙", "🤖", "💻"]

        descs = category_descriptions or {}
        for idx, (cat_name, count) in enumerate(category_counts.items(), 1):
            emoji = emojis[idx % len(emojis)]
            desc = descs.get(cat_name, f"новости категории '{cat_name}'")
            categories_description.append(
                f"{emoji} {cat_name.upper()} ({count}) — {desc}"
            )
            json_structure_lines.append(
                f'  "{cat_name}": [{{"id": ..., "title": "...", "description": "...", "score": ..., "reason": "..."}}]'
            )

        categories_desc_text = "\n".join(categories_description)
        json_structure_text = ",\n".join(json_structure_lines)

        # Тематическая память
        recently_published_section = ""
        if recently_published:
            topics = "\n".join(f"- {t}" for t in recently_published[:30])
            recently_published_section = (
                f"\n\n## РАНЕЕ ОПУБЛИКОВАННЫЕ ТЕМЫ (избегай тематических повторов)\n"
                f"За последние 7 дней уже были опубликованы следующие новости. "
                f"НЕ выбирай новости, покрывающие те же темы/события:\n\n{topics}"
            )

        # Рендерим промпт
        full_prompt = self._render_prompt(
            "select_dynamic_categories",
            DEFAULT_CLAUDE_PROMPT,
            categories_description=categories_desc_text,
            messages_block=messages_block,
            json_structure=json_structure_text,
            recently_published_section=recently_published_section,
        )

        # Разделяем на system и user по маркеру
        if PROMPT_SPLIT_MARKER in full_prompt:
            parts = full_prompt.split(PROMPT_SPLIT_MARKER, 1)
            system_prompt = parts[0].strip()
            user_prompt = parts[1].strip()
        else:
            # Fallback: всё в user prompt
            system_prompt = "Ты — эксперт-редактор AI-дайджеста на русском языке."
            user_prompt = full_prompt

        try:
            result_text = self._complete(
                system=system_prompt,
                user_message=user_prompt,
            )

            json_text = self._extract_json(result_text)
            categories = json.loads(json_text)

            # Валидация через Pydantic
            try:
                validated = DynamicCategoryNews(**categories)
                categories = {
                    cat: getattr(validated, cat, [])
                    for cat in category_counts.keys()
                }
                categories = {
                    cat: [
                        item.model_dump() if isinstance(item, NewsItem) else item
                        for item in items
                    ]
                    for cat, items in categories.items()
                }
            except ValidationError as e:
                logger.error("[%s] Ошибка валидации JSON: %s", request_id, e)
                return {cat: [] for cat in category_counts.keys()}

            # Обогащаем данные
            messages_dict = {msg["id"]: msg for msg in messages}
            for cat_name in category_counts:
                if cat_name not in categories:
                    categories[cat_name] = []
                for item in categories[cat_name]:
                    msg_id = item["id"]
                    if msg_id in messages_dict:
                        msg = messages_dict[msg_id]
                        item["source_link"] = (
                            f"https://t.me/{msg['channel_username']}/{msg.get('message_id', '')}"
                        )
                        item["source_message_id"] = msg_id
                        item["source_channel_id"] = msg["channel_id"]
                        item["text"] = msg["text"]
                        item["category"] = cat_name

            counts_str = ", ".join(
                f"{cat}={len(items)}" for cat, items in categories.items()
            )
            logger.debug("[%s] Chunk: отобрано %s из %d сообщений", request_id, counts_str, len(messages))
            return categories

        except json.JSONDecodeError as e:
            logger.error("[%s] Ошибка парсинга JSON от Claude: %s", request_id, e)
            return {cat: [] for cat in category_counts.keys()}
        except anthropic.APIError as e:
            logger.error("[%s] Ошибка Claude API: %s", request_id, e)
            return {cat: [] for cat in category_counts.keys()}

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _chunk_list(items: list, chunk_size: int) -> list[list]:
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    @staticmethod
    def _deduplicate_by_source_id(
        all_categories: dict[str, list[dict]],
        category_counts: dict[str, int],
    ) -> dict[str, list[dict]]:
        """Удалить дубликаты по source_message_id."""
        seen_ids: set[int] = set()
        deduplicated = {cat: [] for cat in category_counts.keys()}
        duplicate_count = 0

        for cat_name in category_counts:
            for news in all_categories.get(cat_name, []):
                source_id = news.get("source_message_id")
                if source_id is not None and source_id in seen_ids:
                    duplicate_count += 1
                    continue
                if source_id is not None:
                    seen_ids.add(source_id)
                deduplicated[cat_name].append(news)

        if duplicate_count > 0:
            logger.info("Удалено %d дубликатов по source_message_id", duplicate_count)

        return deduplicated


    def rewrite_digest(
        self,
        posts: list[dict],
        header: str,
        footer: str,
    ) -> str:
        """
        Второй проход: Claude переписывает дайджест как живой редактор.

        Args:
            posts: Список отобранных новостей с title, description, text, source_link
            header: Заголовок дайджеста
            footer: Футер дайджеста

        Returns:
            Готовый текст поста для Telegram
        """
        news_parts = []
        for idx, post in enumerate(posts, 1):
            title = post.get("title", "")
            description = post.get("description", "")
            text = (post.get("text") or "")[:2000]
            source_link = post.get("source_link", "")
            news_parts.append(
                f"--- Новость {idx} ---\n"
                f"Заголовок: {title}\n"
                f"Описание: {description}\n"
                f"Полный текст: {text}\n"
                f"Ссылка: {source_link}"
            )

        news_block = self._escape_braces("\n\n".join(news_parts))
        header_escaped = self._escape_braces(header)
        footer_escaped = self._escape_braces(footer)

        full_prompt = self._render_prompt(
            "rewrite_digest",
            DEFAULT_REWRITE_PROMPT,
            header=header_escaped,
            news_block=news_block,
            footer=footer_escaped,
        )

        if PROMPT_SPLIT_MARKER in full_prompt:
            parts = full_prompt.split(PROMPT_SPLIT_MARKER, 1)
            system_prompt = parts[0].strip()
            user_prompt = parts[1].strip()
        else:
            system_prompt = "Ты — редактор AI-дайджеста для Telegram."
            user_prompt = full_prompt

        try:
            result = self._complete(system=system_prompt, user_message=user_prompt)
            # Убираем возможные markdown code blocks
            result = result.strip()
            if result.startswith("```"):
                result = result.split("```")[1]
                if result.startswith("\n"):
                    result = result[1:]
                result = result.rsplit("```", 1)[0].strip()
            return result
        except Exception as e:
            logger.error("Ошибка при переписывании дайджеста: %s", e)
            return ""

    @property
    def usage(self) -> dict:
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "cost_usd": self._total_cost_usd,
        }


# ------------------------------------------------------------------
# Default prompt (используется если нет файла промпта)
# ------------------------------------------------------------------


DEFAULT_REWRITE_PROMPT = """Ты — редактор AI-дайджеста. Перепиши набор новостей в единый связный пост для Telegram-канала.

Требования:
- Русский язык, лаконичный стиль
- Каждая новость: нумерованный пункт с жирным заголовком, 2-3 предложения, ссылка
- Сохрани ВСЕ ссылки на источники
- Используй эмодзи-цифры: 1️⃣ 2️⃣ и т.д.
- Конкретные цифры и факты из исходных текстов
- Не выдумывай факты
- До 3800 символов

---SPLIT---

{header}

{news_block}

{footer}"""

DEFAULT_CLAUDE_PROMPT = """Ты — эксперт-редактор AI-дайджеста на русском языке для руководителя.
Твоя задача — отобрать самые важные и полезные новости про искусственный интеллект и разложить их по категориям.

🚨 КРИТИЧЕСКИ ВАЖНО: ВСЕ ЗАГОЛОВКИ И ОПИСАНИЯ — НА РУССКОМ ЯЗЫКЕ! 🚨

{categories_description}

## КРИТЕРИИ ОЦЕНКИ

### ВЫСОКИЙ ПРИОРИТЕТ (9-10):
✅ Релизы и обновления моделей (GPT, Claude, Gemini, Llama, Mistral и др.)
✅ Новые инструменты и функции в AI-продуктах
✅ Анонсы от крупных компаний (OpenAI, Anthropic, Google, Meta)

### СРЕДНИЙ ПРИОРИТЕТ (7-8):
✅ Кейсы с конкретными результатами (ROI, экономия, автоматизация)
✅ Сравнения моделей с числами

### НИЗКИЙ ПРИОРИТЕТ (5-6):
✅ Научные прорывы, SOTA результаты
✅ Бесплатные обучения от крупных игроков

## ИСКЛЮЧИТЬ:
❌ Рекламу, платные курсы, промокоды
❌ Мемы без практической ценности
❌ Политику без AI контекста
❌ Общие рассуждения без конкретики

## ДЕДУПЛИКАЦИЯ
Выбирай МАКСИМАЛЬНО РАЗНЫЕ новости. Одно событие = одна новость (лучший вариант).
{recently_published_section}

---SPLIT---

## СООБЩЕНИЯ ДЛЯ АНАЛИЗА:

{messages_block}

## ИНСТРУКЦИИ:
1. Прочитай все сообщения
2. Отфильтруй рекламу/спам
3. Для повторяющихся новостей выбери ОДИН лучший вариант
4. Отбери РОВНО указанное количество для каждой категории
5. Оцени важность по критериям выше

Верни JSON-объект. Каждая новость:
- id: номер сообщения (целое число)
- title: заголовок 5-7 слов НА РУССКОМ
- description: описание 2-3 предложения с фактами НА РУССКОМ
- score: оценка 1-10
- reason: почему отобрана

Формат:
{{
{json_structure}
}}

Верни ТОЛЬКО JSON без дополнительного текста."""
