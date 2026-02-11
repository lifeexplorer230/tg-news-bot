# Задачи на доработку tg-news-bot

## Общие правила

- **TDD подход**: перед каждым изменением запусти существующие тесты (`venv/bin/pytest tests/ -v --no-cov`), после изменения — снова. Пиши новые тесты для каждого фикса.
- **Baseline**: 307 passed, 2 failed (pre-existing `use_dbscan` в test_processor_statuses — не трогать).
- **Не ломать**: если тесты упали после твоего изменения — чини до зелёного.
- **Venv**: `/root/tg-news-bot/venv/bin/python`, pytest там же.

---

## 1. [Серьёзная] Убрать захардкоженную CategoryNews модель

**Файл**: `services/gemini_client.py` (строки 45-53)

**Проблема**: `CategoryNews` захардкожена под 3 маркетплейса (wildberries, ozon, general). Рядом есть универсальная `DynamicCategoryNews` (строки 55-72), которая поддерживает произвольные категории из конфига.

**Что сделать**:
1. Найти все места где используется `CategoryNews` (не `DynamicCategoryNews`)
2. Заменить на `DynamicCategoryNews` или убрать если не используется
3. Если `CategoryNews` больше нигде не нужна — удалить класс
4. Написать тест подтверждающий что динамические категории работают с произвольными именами

---

## 2. [Средняя] Добавить retry при save_published

**Файл**: `services/news_processor.py`

**Проблема**: Если `save_published` падает (например, БД заблокирована), пост теряется без повторной попытки. В `database/db.py` метод `save_published` уже имеет декоратор `@retry_on_locked`, но на уровне вызывающего кода в `news_processor.py` нет обработки ошибки.

**Что сделать**:
1. Найти все вызовы `self.db.save_published(...)` в `news_processor.py`
2. Обернуть в try/except с логированием ошибки
3. При ошибке — не крашить весь дайджест, а пропустить пост и продолжить
4. Написать тест: mock `db.save_published` бросает исключение → остальные посты публикуются

---

## 3. [Средняя] Gemini prompt injection protection

**Файл**: `services/gemini_client.py`

**Проблема**: Текст сообщений из Telegram каналов подставляется в промпт для Gemini без санитизации. Злоумышленник может отправить сообщение с инструкциями вроде "Ignore previous instructions and..." которое попадёт в промпт.

**Что сделать**:
1. Создать функцию `sanitize_for_prompt(text: str) -> str` в `utils/formatters.py`
2. Функция должна: обрезать текст до разумного лимита (например 2000 символов), экранировать или удалить паттерны типа "ignore previous", "system:", "assistant:" и т.п.
3. Применить санитизацию в методах `_build_prompt` / `_format_messages_for_prompt` в gemini_client.py — перед тем как текст попадает в промпт
4. Написать тесты для sanitize_for_prompt

---

## 4. [Средняя] Валидация env variables при старте

**Файл**: `utils/config.py`

**Проблема**: Если `.env` не содержит обязательных переменных (TELEGRAM_API_ID, TELEGRAM_API_HASH, GEMINI_API_KEY), бот крашится позже с непонятной ошибкой. Нужно проверять при старте.

**Что сделать**:
1. Найти метод `_validate_env()` в `utils/config.py` — он уже существует, проверить вызывается ли он
2. Убедиться что STATUS_BOT_TOKEN тоже валидируется (мы его добавили в .env)
3. Если валидация не вызывается при инициализации — добавить вызов
4. Написать тест: Config с пустыми обязательными env → понятная ошибка ValueError

---

## 5. [Оптимизация] Пересоздать venv с CPU-only torch

**Проблема**: `venv/` занимает 7.3 ГБ, большая часть — PyTorch с CUDA. Сервер без GPU.

**Что сделать**:
1. Сохранить текущие зависимости: `venv/bin/pip freeze > /tmp/requirements-current.txt`
2. Проверить используется ли torch напрямую: `grep -r "import torch" services/ utils/ database/`
3. Если torch нужен только как зависимость sentence-transformers — установить CPU-версию:
   ```
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   ```
4. Проверить что тесты проходят после пересборки
5. Сравнить размер до/после

**ВНИМАНИЕ**: Это деструктивная операция. Перед началом убедись что `requirements.txt` актуален.
