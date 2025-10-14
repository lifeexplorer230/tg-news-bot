# План универсализации проекта tg-news-bot

**Дата:** 2025-10-15
**Цель:** Удалить все marketplace-специфичные упоминания из кода, оставив их только в конфигах

---

## Текущая ситуация

### ✅ Что уже универсально (в конфигах):
- `config/profiles/marketplace.yaml` - marketplace-специфичная конфигурация
- `config/prompts/marketplace_*.md` - marketplace-специфичные промпты
- `marketplaces:` секция в конфиге с динамическим списком категорий

### ❌ Что НЕ универсально (hardcode в коде):
- **167 упоминаний** marketplace-специфики в Python коде
- Hardcoded строки: "wildberries", "ozon", "general"
- Класс `MarketplaceProcessor` (должен быть `NewsProcessor`)
- Файл `models/marketplace.py` (должен быть `models/category.py`)
- Методы `process_marketplace()` и др.

---

## Категории изменений

### 🔴 ВЫСОКИЙ ПРИОРИТЕТ (критические изменения)

#### H1. Удалить hardcoded marketplace имена из кода

**Файл:** `services/marketplace_processor.py`

**Проблемные места:**

```python
# Lines 93-95: Hardcoded names
self.all_digest_counts = {
    "wildberries": counts_config.get("wildberries", 5),  # ❌ Hardcode
    "ozon": counts_config.get("ozon", 5),                # ❌ Hardcode
    "general": counts_config.get("general", 5),          # ❌ Hardcode
}

# Lines 476-478: Hardcoded в вызове метода
categories = self.gemini.select_three_categories(
    unique_messages,
    wb_count=self.all_digest_counts["wildberries"],      # ❌ Hardcode
    ozon_count=self.all_digest_counts["ozon"],           # ❌ Hardcode
    general_count=self.all_digest_counts["general"],     # ❌ Hardcode
)

# Lines 803-830: Hardcoded в форматировании
if categories.get("wildberries"):                        # ❌ Hardcode
    lines.append("📦 **WILDBERRIES**\n")                 # ❌ Hardcode
    for post in categories["wildberries"]:
        # ...

if categories.get("ozon"):                               # ❌ Hardcode
    lines.append("📦 **OZON**\n")                        # ❌ Hardcode
    for post in categories["ozon"]:
        # ...

if categories.get("general"):                            # ❌ Hardcode
    lines.append("📦 **ОБЩИЕ**\n")                       # ❌ Hardcode
    for post in categories["general"]:
        # ...
```

**Решение:**
- Читать category names динамически из `config.get("channels.all_digest.category_counts", {})`
- Использовать `categories.items()` для итерации вместо hardcoded ключей
- Заменить `select_three_categories()` на generic `select_by_categories(category_counts)`

**Затронутые строки:**
- `services/marketplace_processor.py:93-95`
- `services/marketplace_processor.py:476-478`
- `services/marketplace_processor.py:482-483` (wb_count, ozon_count)
- `services/marketplace_processor.py:803-830` (форматирование)

---

#### H2. Переименовать класс MarketplaceProcessor → NewsProcessor

**Файл:** `services/marketplace_processor.py`

**Изменения:**
```python
# Было:
class MarketplaceProcessor:
    """Процессор новостей для маркетплейсов (Ozon и Wildberries)"""

# Станет:
class NewsProcessor:
    """Универсальный процессор новостей с поддержкой категорий"""
```

**Затронутые файлы:**
- `services/marketplace_processor.py:21` - объявление класса
- `main.py:21` - импорт
- `main.py:141` - создание экземпляра
- `tests/test_processor_statuses.py` - тесты
- `tests/test_healthcheck.py` - тесты

**Сложность:** Средняя (требуется обновить импорты и тесты)

---

#### H3. Переименовать файл models/marketplace.py → models/category.py

**Файл:** `models/marketplace.py`

**Изменения:**
```python
# Было:
@dataclass
class Marketplace:
    """Настройки конкретного маркетплейса для процессора."""

# Станет:
@dataclass
class Category:
    """Настройки категории новостей для процессора."""
```

**Затронутые файлы:**
- `models/marketplace.py` → переименовать в `models/category.py`
- `services/marketplace_processor.py:10` - импорт
- Все места где используется `Marketplace` class

**Сложность:** Низкая (простое переименование + find/replace)

---

#### H4. Переименовать файл services/marketplace_processor.py → services/news_processor.py

**Файл:** `services/marketplace_processor.py`

**Изменения:**
- Переименовать файл в `news_processor.py`
- Обновить module docstring

**Затронутые файлы:**
- `main.py:21` - импорт
- Все тесты

**Сложность:** Низкая (файл rename + обновить импорты)

---

### 🟡 СРЕДНИЙ ПРИОРИТЕТ (улучшения архитектуры)

#### M1. Переименовать переменные marketplace → category

**Файлы:** `services/marketplace_processor.py`

**Изменения:**
```python
# Было:
self.marketplaces: dict[str, Marketplace] = {}
raw_marketplaces = config.get("marketplaces", [])
self.marketplace_names = list(self.marketplaces.keys())

# Станет:
self.categories: dict[str, Category] = {}
raw_categories = config.get("categories", [])
self.category_names = list(self.categories.keys())
```

**Затронутые строки:**
- `services/marketplace_processor.py:46, 56, 70, 73, 76, 79`
- Все методы где используется `marketplace` как переменная

**Сложность:** Средняя (много мест для замены)

---

#### M2. Переименовать методы

**Файл:** `services/marketplace_processor.py`

**Изменения:**
```python
# Было:
async def process_marketplace(self, marketplace: str, ...)
async def process_all_categories(self, ...)  # Уже хорошее название!

# Станет:
async def process_category(self, category: str, ...)
async def process_all_categories(self, ...)  # Оставить как есть
```

**Затронутые строки:**
- `services/marketplace_processor.py:145` - определение метода
- `services/marketplace_processor.py:1023` - вызов метода

**Сложность:** Низкая

---

#### M3. Обновить конфиг ключи: marketplaces → categories

**Файлы:**
- `config/base.yaml`
- `config/profiles/marketplace.yaml`

**Изменения:**
```yaml
# Было:
marketplaces:
  - name: ozon
    display_name: Ozon
  - name: wildberries
    display_name: Wildberries

# Станет:
categories:
  - name: ozon
    display_name: Ozon
  - name: wildberries
    display_name: Wildberries
```

**ВАЖНО:** Это breaking change для существующих конфигов!

**Решение:** Поддержать оба варианта (backwards compatibility):
```python
raw_categories = config.get("categories") or config.get("marketplaces", [])
```

**Сложность:** Низкая (с backwards compatibility)

---

### 🟢 НИЗКИЙ ПРИОРИТЕТ (полировка)

#### L1. Обновить docstrings и комментарии

**Файлы:** Все `.py` файлы

**Изменения:**
- Заменить "маркетплейс" → "категория" в docstrings
- Заменить "Ozon, Wildberries" → "категории новостей"
- Обновить комментарии

**Сложность:** Низкая (текстовые замены)

---

#### L2. Обновить логирование

**Файл:** `services/marketplace_processor.py`

**Изменения:**
```python
# Было:
logger.info(f"🛒 ОБРАБОТКА НОВОСТЕЙ: {marketplace.upper()}")
logger.info(f"Нет новых сообщений для {marketplace}")

# Станет:
logger.info(f"📰 ОБРАБОТКА НОВОСТЕЙ: {category.upper()}")
logger.info(f"Нет новых сообщений для категории {category}")
```

**Сложность:** Низкая

---

## План реализации

### Этап 1: Подготовка (Sprint 4.0)
**Цель:** Создать backwards-compatible foundation

**Задачи:**
1. ✅ Создать `UNIVERSALIZATION_PLAN.md` (этот документ)
2. Создать feature branch: `git checkout -b feature/universalize-codebase`
3. Обновить `DOROZHNAYA_KARTA.md` с Sprint 4 roadmap

**Время:** 30 мин

---

### Этап 2: Критические изменения (Sprint 4.1)
**Цель:** Удалить hardcoded marketplace names

**Задачи:**

**4.1.A - Удалить hardcoded categories (H1)**
- [ ] Рефакторить `all_digest_counts` для динамических категорий
- [ ] Обновить `select_three_categories()` → `select_by_categories()`
- [ ] Рефакторить `_format_categories_moderation_message()` для динамических категорий
- [ ] Тесты: `test_processor_statuses.py`
- [ ] Commit: "refactor: Remove hardcoded category names (wildberries, ozon, general)"

**Время:** 2 часа
**Риск:** Средний (много мест для изменения)

---

### Этап 3: Переименования (Sprint 4.2)
**Цель:** Переименовать классы и файлы

**Задачи:**

**4.2.A - Переименовать Marketplace → Category (H3)**
- [ ] Переименовать `models/marketplace.py` → `models/category.py`
- [ ] Заменить `class Marketplace` → `class Category`
- [ ] Обновить все импорты
- [ ] Обновить docstrings класса
- [ ] Тесты: все тесты должны пройти
- [ ] Commit: "refactor: Rename Marketplace class to Category"

**4.2.B - Переименовать MarketplaceProcessor → NewsProcessor (H2, H4)**
- [ ] Заменить `class MarketplaceProcessor` → `class NewsProcessor`
- [ ] Переименовать `services/marketplace_processor.py` → `services/news_processor.py`
- [ ] Обновить импорты в `main.py`
- [ ] Обновить импорты в тестах
- [ ] Обновить docstrings
- [ ] Тесты: все тесты должны пройти
- [ ] Commit: "refactor: Rename MarketplaceProcessor to NewsProcessor"

**Время:** 1 час
**Риск:** Низкий (IDE refactoring поможет)

---

### Этап 4: Переменные и методы (Sprint 4.3)
**Цель:** Обновить naming в коде

**Задачи:**

**4.3.A - Переименовать переменные (M1)**
- [ ] `self.marketplaces` → `self.categories`
- [ ] `raw_marketplaces` → `raw_categories`
- [ ] `marketplace_names` → `category_names`
- [ ] Все локальные переменные `marketplace` → `category`
- [ ] Тесты: все тесты должны пройти
- [ ] Commit: "refactor: Rename marketplace variables to category"

**4.3.B - Переименовать методы (M2)**
- [ ] `process_marketplace()` → `process_category()`
- [ ] Обновить все вызовы
- [ ] Тесты: все тесты должны пройти
- [ ] Commit: "refactor: Rename process_marketplace to process_category"

**Время:** 1 час
**Риск:** Низкий

---

### Этап 5: Конфиг и backwards compatibility (Sprint 4.4)
**Цель:** Обновить конфиг с поддержкой старых версий

**Задачи:**

**4.4.A - Поддержать categories в конфиге (M3)**
- [ ] Добавить поддержку `config.get("categories")`
- [ ] Добавить fallback: `config.get("categories") or config.get("marketplaces")`
- [ ] Обновить `models/config_schemas.py`
- [ ] Документировать backwards compatibility
- [ ] Тесты: проверить оба варианта конфига
- [ ] Commit: "feat: Support 'categories' config key with backwards compatibility"

**4.4.B - Создать пример generic конфига**
- [ ] Создать `config/profiles/generic.yaml` с примером универсального конфига
- [ ] Документировать в README
- [ ] Commit: "docs: Add generic config profile example"

**Время:** 1 час
**Риск:** Низкий

---

### Этап 6: Полировка (Sprint 4.5)
**Цель:** Обновить документацию и комментарии

**Задачи:**

**4.5.A - Обновить docstrings (L1)**
- [ ] Обновить все docstrings в `services/news_processor.py`
- [ ] Обновить module docstring
- [ ] Обновить комментарии
- [ ] Commit: "docs: Update docstrings to use generic terminology"

**4.5.B - Обновить логирование (L2)**
- [ ] Обновить log messages для универсальности
- [ ] Убрать эмодзи 🛒 (marketplace cart)
- [ ] Использовать 📰 (newspaper) или 📊 (chart)
- [ ] Commit: "refactor: Update logging messages for universal terminology"

**Время:** 30 мин
**Риск:** Нет

---

### Этап 7: Финализация (Sprint 4.6)
**Цель:** Завершить рефакторинг и обновить документацию

**Задачи:**

**4.6.A - Запустить полный test suite**
- [ ] `pytest -v` - все 103 теста должны пройти
- [ ] `pytest --cov=. --cov-report=term-missing` - coverage >= 90%
- [ ] Проверить что не сломалась функциональность

**4.6.B - Обновить документацию**
- [ ] Обновить `README.md` с описанием универсальности
- [ ] Обновить `DOROZHNAYA_KARTA.md` со статусом Sprint 4
- [ ] Обновить `memory-bank/arkhitektura.md`
- [ ] Commit: "docs: Update project documentation for universal architecture"

**4.6.C - Создать release notes**
- [ ] Создать `RELEASE_NOTES_v2.2.0.md`
- [ ] Описать breaking changes (опционально)
- [ ] Описать новые возможности (generic categories)

**Время:** 1 час
**Риск:** Нет

---

### Этап 8: Release (Sprint 4.7)
**Цель:** Релиз версии 2.2.0

**Задачи:**
- [ ] Merge feature branch: `git checkout main && git merge feature/universalize-codebase`
- [ ] Обновить версию в проекте
- [ ] Создать git tag: `git tag -a v2.2.0 -m "Release v2.2.0 - Universal Architecture"`
- [ ] Push: `git push origin main --tags`

**Время:** 15 мин

---

## Общая оценка

### Временные затраты:
- **Этап 1 (Подготовка):** 30 мин
- **Этап 2 (Критические изменения):** 2 часа
- **Этап 3 (Переименования):** 1 час
- **Этап 4 (Переменные и методы):** 1 час
- **Этап 5 (Конфиг):** 1 час
- **Этап 6 (Полировка):** 30 мин
- **Этап 7 (Финализация):** 1 час
- **Этап 8 (Release):** 15 мин

**ИТОГО:** ~7 часов 15 минут

### Риски:
- **Высокий риск:** Нет
- **Средний риск:** Этап 2 (много мест для изменения)
- **Низкий риск:** Остальные этапы

### Рекомендации:
1. **Делать коммиты после каждой задачи** - для возможности rollback
2. **Запускать тесты после каждого этапа** - раннее обнаружение проблем
3. **Использовать IDE refactoring** - для переименований классов/методов
4. **Сохранить backwards compatibility** - для плавного перехода

---

## Критерии успеха

### После завершения рефакторинга:

✅ **Код не содержит hardcoded упоминаний "wildberries", "ozon", "general"**
✅ **Классы и файлы имеют универсальные названия (Category, NewsProcessor)**
✅ **Конфиг поддерживает любые категории (не только маркетплейсы)**
✅ **Все 103 теста проходят**
✅ **Coverage остаётся >= 90%**
✅ **Backwards compatibility сохранена (старые конфиги работают)**
✅ **Документация обновлена**

---

## Пример: До и После

### До (marketplace-specific):

```python
# models/marketplace.py
class MarketplaceProcessor:
    """Процессор для маркетплейсов Ozon и Wildberries"""

    def __init__(self, config):
        self.all_digest_counts = {
            "wildberries": 5,  # ❌ Hardcode
            "ozon": 5,         # ❌ Hardcode
            "general": 5,      # ❌ Hardcode
        }
```

### После (universal):

```python
# models/category.py
class NewsProcessor:
    """Универсальный процессор новостей с поддержкой категорий"""

    def __init__(self, config):
        # ✅ Динамическое чтение категорий из конфига
        counts_config = config.get("channels.all_digest.category_counts", {})
        self.all_digest_counts = dict(counts_config)
```

---

## Заключение

Этот план превратит проект из **marketplace-specific** в **truly universal**.

После выполнения:
- Проект можно использовать для ЛЮБЫХ категорий новостей (AI, tech, finance, etc.)
- Конфигурация полностью определяет поведение
- Код остаётся чистым и универсальным

**Следующий шаг:** Создать feature branch и начать Этап 1 (Подготовка).
