# 📖 ИНСТРУКЦИЯ ВЫПОЛНЕНИЯ
## Marketplace News Bot — Детальные шаги миграции

**Версия:** 1.0
**Дата:** 2025-10-11

---

## 🚀 БЫСТРЫЙ СТАРТ

### Команда для начала работы

```bash
Протокол, шаг <код>
```

Где `<код>` — это ID задачи из `DOROZHNAYA_KARTA.md`.

### Последовательность действий ассистента

1. **Memory** → Читает памятки из `memory-bank/`
2. **Roadmap** → Сверяется с `DOROZHNAYA_KARTA.md`
3. **Instruction** → Следует этой инструкции
4. **Execute** → Выполняет чек-лист
5. **Verify** → Проверяет результат
6. **Update** → Обновляет журнал

---

## 📋 ОБЩИЕ ПРАВИЛА

### До начала ЛЮБОЙ задачи

```bash
# 1. Проверить текущую ветку
git branch --show-current

# 2. Проверить статус
git status

# 3. Убедиться что находимся в корне проекта
pwd  # Должно быть: /root/marketplace-news-bot
```

### Правила коммитов

- ✅ Один подпункт = один коммит
- ✅ Сообщение коммита: `[<код>] Краткое описание`
- ✅ Пример: `[B1] Реализовать метод Database.check_duplicate`
- ✅ После коммита: обновить журнал в дорожной карте

### Правила проверок

```bash
# После каждого изменения кода
git diff --stat  # Проверить размер изменений
git diff         # Просмотреть детали

# Проверить что код не сломался (если есть тесты)
pytest tests/

# Попробовать импортировать модуль
python -c "from database.db import Database; print('OK')"
```

### Pre-commit и автоформатирование

```bash
pip install -r requirements-dev.txt     # Установить dev-зависимости
pre-commit install                      # Установить хуки один раз
pre-commit run --all-files              # Проверить весь проект перед пушем
```

- Хуки запускают ruff, black, isort, markdownlint и поиск секретов.
- Не переходи к коммиту, пока `pre-commit run --all-files` не завершится без ошибок.

### Правила логирования

```bash
# Сохранять логи после каждой партии
echo "[$(date)] Выполнено: <описание>" >> logs/migration_$(date +%Y-%m-%d).log
```

---

## 📦 ЭТАП A0: BASELINE (Подготовка)

### A0.1: Структура документации ✅

**Уже выполнено** — документы созданы.

---

### A0.2: Baseline Snapshot

**Цель:** Сохранить текущее состояние кода для возможности отката.

#### Чек-лист:

```bash
# 1. Создать snapshot директорию
mkdir -p snapshot

# 2. Сохранить список всех файлов
find . -type f -name "*.py" | sort > snapshot/files_list.txt

# 3. Сохранить структуру проекта
tree -I '__pycache__|*.pyc|.git|data|logs|snapshot|memory-bank' > snapshot/structure.txt

# 4. Подсчитать статистику
wc -l services/*.py database/*.py utils/*.py main.py > snapshot/lines_count.txt

# 5. Сохранить версии зависимостей (если есть)
if [ -f requirements.txt ]; then
    cp requirements.txt snapshot/requirements_baseline.txt
fi

# 6. Сохранить конфиг
cp config.yaml snapshot/config_baseline.yaml

# 7. Создать diff baseline (пустой на этом этапе)
git diff > snapshot/baseline_diff.patch

# 8. Сохранить информацию о коммите
git log -1 --format="%H %ai %s" > snapshot/baseline_commit.txt

# 9. Записать в лог
echo "[$(date)] A0.2: Baseline snapshot создан" >> logs/migration_$(date +%Y-%m-%d).log

# 10. Коммит
git add snapshot/.gitkeep logs/.gitkeep
git commit -m "[A0.2] Создан baseline snapshot"
```

**Проверка:**
- ✅ Файл `snapshot/files_list.txt` содержит список всех .py файлов
- ✅ Файл `snapshot/structure.txt` содержит дерево проекта
- ✅ Коммит создан

**Обновить:** Отметить A0.2 как ✅ в `DOROZHNAYA_KARTA.md`

---

### A0.3: Запуск существующих компонентов

**Цель:** Убедиться что текущий код запускается (для понимания baseline).

#### Чек-лист:

```bash
# 1. Проверить зависимости
pip list | grep -E "(telethon|sentence-transformers|google-generativeai)"

# 2. Проверить конфиг
python -c "from utils.config import load_config; c = load_config(); print('Config OK')"

# 3. Проверить БД
python -c "from database.db import Database; db = Database('./data/test.db'); print('DB OK'); db.close()"

# 4. Проверить Telegram Listener (импорт)
python -c "from services.telegram_listener import TelegramListener; print('Listener OK')"

# 5. Проверить Processor (импорт)
python -c "from services.marketplace_processor import MarketplaceProcessor; print('Processor OK')"

# 6. Проверить Gemini Client (импорт)
python -c "from services.gemini_client import GeminiClient; print('Gemini OK')"

# 7. Записать результаты
echo "[$(date)] A0.3: Проверка импортов" >> logs/migration_$(date +%Y-%m-%d).log
python -c "
from database.db import Database
from services.telegram_listener import TelegramListener
from services.marketplace_processor import MarketplaceProcessor
from services.gemini_client import GeminiClient
print('✅ Все модули импортируются успешно')
" >> logs/migration_$(date +%Y-%m-%d).log 2>&1

# 8. Коммит (если были изменения в логах)
git add logs/.gitkeep
git commit -m "[A0.3] Проверка базовой работоспособности" --allow-empty
```

**Проверка:**
- ✅ Все модули импортируются без ошибок
- ✅ Логи сохранены

**Обновить:** Отметить A0.3 как ✅ в `DOROZHNAYA_KARTA.md`

---

## 🔴 ЭТАП B: КРИТИЧЕСКИЕ ДЕФЕКТЫ (P0)

### B1: Реализовать Database.check_duplicate()

**Файл:** `database/db.py`
**Проблема:** Метод вызывается в `marketplace_processor.py:161`, но отсутствует → AttributeError

#### Чек-лист:

```bash
# 1. Открыть файл
# Read database/db.py

# 2. Найти место для добавления метода (после get_published_embeddings)

# 3. Добавить метод check_duplicate
# (Код добавляется через Edit tool)
```

**Код для добавления в database/db.py (после строки 268):**

```python
def check_duplicate(self, embedding: np.ndarray, threshold: float = 0.85) -> bool:
    """
    Проверить является ли текст дубликатом опубликованного

    Args:
        embedding: Embedding текста для проверки
        threshold: Порог схожести (0.0 - 1.0)

    Returns:
        True если найден дубликат
    """
    # Загружаем опубликованные embeddings за последние 60 дней
    published_embeddings = self.get_published_embeddings(days=60)

    if not published_embeddings:
        return False

    # Проверяем схожесть с каждым опубликованным
    for post_id, published_embedding in published_embeddings:
        # Косинусное сходство
        similarity = np.dot(embedding, published_embedding) / (
            np.linalg.norm(embedding) * np.linalg.norm(published_embedding)
        )

        if similarity >= threshold:
            logger.debug(f"Найден дубликат: post_id={post_id}, similarity={similarity:.3f}")
            return True

    return False
```

**Команды после изменения:**

```bash
# 4. Проверить синтаксис
python -c "from database.db import Database; print('✅ Импорт успешен')"

# 5. Проверить git diff
git diff database/db.py
git diff --stat

# 6. Создать простой тест
python -c "
import numpy as np
from database.db import Database

db = Database('./data/test_check_dup.db')
test_embedding = np.random.rand(384)  # Случайный embedding
result = db.check_duplicate(test_embedding, threshold=0.85)
print(f'✅ Метод работает: is_duplicate={result}')
db.close()
" >> logs/migration_$(date +%Y-%m-%d).log 2>&1

# 7. Логирование
echo "[$(date)] B1: Реализован Database.check_duplicate()" >> logs/migration_$(date +%Y-%m-%d).log

# 8. Коммит
git add database/db.py
git commit -m "[B1] Реализовать метод Database.check_duplicate для проверки дубликатов"

# 9. Push
git push origin main
```

**Проверка:**
- ✅ Файл `database/db.py` содержит метод `check_duplicate`
- ✅ Импорт проходит успешно
- ✅ Метод можно вызвать без ошибок
- ✅ Коммит создан и запушен

**Обновить:** Отметить B1 как ✅ в `DOROZHNAYA_KARTA.md`

---

### B2: Добавить статусы обработки сообщений

**Файлы:** `database/db.py`, `services/marketplace_processor.py`
**Проблема:** Только отобранные новости помечаются как processed, остальные переобрабатываются бесконечно

#### Чек-лист:

**Часть 1: Миграция схемы БД**

```bash
# 1. Читаем database/db.py
# Read database/db.py

# 2. Добавляем поле rejection_reason в таблицу raw_messages
# В методе init_db добавить миграцию (через Edit tool)
```

**Изменения в database/db.py (init_db, после строки 66):**

```python
# Добавляем новое поле если его нет
cursor.execute("PRAGMA table_info(raw_messages)")
columns = [col[1] for col in cursor.fetchall()]
if 'rejection_reason' not in columns:
    cursor.execute('ALTER TABLE raw_messages ADD COLUMN rejection_reason TEXT')
    logger.info("Добавлено поле rejection_reason в raw_messages")
```

**Изменения в database/db.py (mark_as_processed, заменить метод):**

```python
def mark_as_processed(self, message_id: int, is_duplicate: bool = False,
                     gemini_score: Optional[int] = None,
                     rejection_reason: Optional[str] = None):
    """
    Пометить сообщение как обработанное

    Args:
        message_id: ID сообщения
        is_duplicate: Является ли дубликатом
        gemini_score: Оценка от Gemini (если отобрано)
        rejection_reason: Причина отклонения (если не опубликовано)
    """
    cursor = self.conn.cursor()
    cursor.execute('''
        UPDATE raw_messages
        SET processed = 1,
            is_duplicate = ?,
            gemini_score = ?,
            rejection_reason = ?
        WHERE id = ?
    ''', (is_duplicate, gemini_score, rejection_reason, message_id))
    self.conn.commit()
```

**Часть 2: Обновление marketplace_processor.py**

```bash
# 3. Читаем marketplace_processor.py
# Read services/marketplace_processor.py

# 4. Обновляем метод _filter_by_keywords (добавить маркировку отклоненных)
# 5. Обновляем метод filter_duplicates (добавить маркировку дубликатов)
# 6. Обновляем метод process_marketplace (помечать ВСЕ рассмотренные)
```

**Изменения в marketplace_processor.py:**

```python
# В методе _filter_by_keywords (после строки 150):
# Помечаем отклоненные как обработанные
for msg in messages:
    if msg not in filtered:
        # Проверяем почему отклонено
        text_lower = msg['text'].lower()
        if any(exclude.lower() in text_lower for exclude in exclude_keywords):
            self.db.mark_as_processed(
                msg['id'],
                rejection_reason='rejected_by_exclude_keywords'
            )
        elif not any(keyword.lower() in text_lower for keyword in keywords):
            self.db.mark_as_processed(
                msg['id'],
                rejection_reason='rejected_by_keywords_mismatch'
            )

# В методе filter_duplicates (после строки 166):
# Помечаем дубликаты
for msg in messages:
    embedding = self.embeddings.encode(msg['text'])
    is_duplicate = self.db.check_duplicate(embedding, self.duplicate_threshold)

    if is_duplicate:
        self.db.mark_as_processed(
            msg['id'],
            is_duplicate=True,
            rejection_reason='is_duplicate'
        )
    else:
        unique.append(msg)

# В методе process_marketplace (после строки 110):
# Помечаем не отобранные Gemini
formatted_ids = {post['source_message_id'] for post in formatted_posts}
for msg in unique_messages:
    if msg['id'] not in formatted_ids:
        self.db.mark_as_processed(
            msg['id'],
            rejection_reason='rejected_by_llm'
        )
```

**Команды после изменений:**

```bash
# 7. Проверка синтаксиса
python -c "from database.db import Database; print('✅ DB импорт OK')"
python -c "from services.marketplace_processor import MarketplaceProcessor; print('✅ Processor импорт OK')"

# 8. Тест миграции БД
python -c "
from database.db import Database
db = Database('./data/test_migration.db')
# Проверяем что поле добавлено
cursor = db.conn.cursor()
cursor.execute('PRAGMA table_info(raw_messages)')
columns = [col[1] for col in cursor.fetchall()]
assert 'rejection_reason' in columns, 'Поле rejection_reason не добавлено!'
print('✅ Миграция БД успешна')
db.close()
" >> logs/migration_$(date +%Y-%m-%d).log 2>&1

# 9. Git diff
git diff --stat

# 10. Логирование
echo "[$(date)] B2: Добавлены статусы обработки сообщений" >> logs/migration_$(date +%Y-%m-%d).log

# 11. Коммит (два отдельных)
git add database/db.py
git commit -m "[B2.1] Добавить поле rejection_reason и обновить mark_as_processed"

git add services/marketplace_processor.py
git commit -m "[B2.2] Помечать ВСЕ рассмотренные сообщения как processed"

# 12. Push
git push origin main
```

**Проверка:**
- ✅ Поле `rejection_reason` добавлено в БД
- ✅ Метод `mark_as_processed` обновлён
- ✅ Все рассмотренные сообщения помечаются
- ✅ Импорты проходят
- ✅ Два коммита созданы

**Обновить:** Отметить B2 как ✅ в `DOROZHNAYA_KARTA.md`

---

### B3: Канал для режима "all"

**Файлы:** `config.yaml`, `services/marketplace_processor.py`
**Проблема:** Режим all публикует в канал Ozon

#### Чек-лист:

```bash
# 1. Читаем config.yaml
# Read config.yaml

# 2. Добавляем секцию all_digest
```

**Изменения в config.yaml (после строки 56):**

```yaml
  # Канал для общего дайджеста (3 категории)
  all_digest:
    enabled: true
    target_channel: "@rnpozwb"  # Можно изменить на другой канал
```

**Изменения в marketplace_processor.py (строка 277):**

```python
# Было:
target_channel = next(
    (mp.target_channel for mp in self.marketplaces.values() if mp.target_channel),
    None,
)

# Стало:
target_channel = (
    self.all_digest_channel
    if self.all_digest_enabled and self.all_digest_channel
    else next(
        (mp.target_channel for mp in self.marketplaces.values() if mp.target_channel),
        None,
    )
)
```

**Команды после изменений:**

```bash
# 3. Проверка синтаксиса YAML
python -c "from utils.config import load_config; c = load_config(); print('✅ Config OK')"

# 4. Проверка что значение читается
python -c "
from utils.config import load_config
c = load_config()
channel = c.get('channels.all_digest.target_channel')
print(f'✅ Канал all_digest: {channel}')
"

# 5. Git diff
git diff --stat

# 6. Логирование
echo "[$(date)] B3: Добавлен канал для режима all" >> logs/migration_$(date +%Y-%m-%d).log

# 7. Коммит
git add config.yaml services/marketplace_processor.py
git commit -m "[B3] Добавить отдельный канал для режима all_digest"

# 8. Push
git push origin main
```

**Проверка:**
- ✅ Секция `all_digest` добавлена в config.yaml
- ✅ Processor использует правильный канал
- ✅ Config загружается без ошибок
- ✅ Коммит создан

**Обновить:** Отметить B3 как ✅ в `DOROZHNAYA_KARTA.md`

**🎉 ВАЖНО:** После B3 создать PR и слить в main!

---

## 🟡 ЭТАП C: ВЫСОКИЙ ПРИОРИТЕТ (P1)

### C1: SQLite Concurrency Fix

**Файлы:** `main.py`, `database/db.py`
**Проблема:** Один Database instance используется в разных потоках

#### Чек-лист:

```bash
# 1. Читаем main.py
# Read main.py

# 2. Изменяем чтобы каждый компонент создавал свой Database instance
```

**Изменения в main.py:**

```python
# В run_listener_mode (строка 42):
# Было:
db = Database(config.db_path)
listener = TelegramListener(config, db)

# Стало:
listener = TelegramListener(config, Database(config.db_path))

# В run_processor_mode (строка 56):
# Processor создаёт свой DB внутри

# В schedule_status_reporter (строка 89):
# StatusReporter создаёт свой DB внутри

# В main (строка 136):
# Удалить: db = Database(config.db_path)
# Передавать только config.db_path
```

**Изменения в database/db.py:**

```python
# Добавить WAL mode для лучшей concurrency (в connect, после строки 31):
self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
self.conn.execute('PRAGMA journal_mode=WAL')  # Добавить эту строку
self.conn.row_factory = sqlite3.Row
```

**Команды:**

```bash
# 3. Проверка
python -c "from database.db import Database; db = Database('./data/test_wal.db'); print('✅ WAL mode OK'); db.close()"

# 4. Git diff
git diff --stat

# 5. Логирование
echo "[$(date)] C1: SQLite concurrency исправлено (WAL mode, отдельные подключения)" >> logs/migration_$(date +%Y-%m-%d).log

# 6. Коммит
git add database/db.py main.py
git commit -m "[C1] Исправить SQLite concurrency: WAL mode + отдельные подключения"

# 7. Push
git push origin main
```

**Проверка:**
- ✅ WAL mode включен
- ✅ Каждый компонент создаёт свой Database
- ✅ Нет shared state
- ✅ Коммит создан

**Обновить:** Отметить C1 как ✅ в `DOROZHNAYA_KARTA.md`

---

### C2: Robustness Gemini (Retry + Validation)

**Файл:** `services/gemini_client.py`
**Проблема:** Нет retry, валидации JSON, обработки ошибок

#### Чек-лист:

```bash
# 1. Добавить зависимости
pip install tenacity pydantic

# 2. Добавить в requirements.txt
echo "tenacity>=8.2.0" >> requirements.txt
echo "pydantic>=2.0.0" >> requirements.txt

# 3. Читаем gemini_client.py
# Read services/gemini_client.py

# 4. Добавить retry декоратор и Pydantic схемы
```

**Изменения в gemini_client.py:**

```python
# В начале файла (после строки 5):
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Optional

# Добавить Pydantic схемы:
class NewsItem(BaseModel):
    id: int
    title: str
    description: str
    score: int = Field(ge=1, le=10)
    reason: Optional[str] = None
    source_link: Optional[str] = None
    source_message_id: Optional[int] = None
    source_channel_id: Optional[int] = None
    text: Optional[str] = None

class CategoryNews(BaseModel):
    wildberries: List[NewsItem] = []
    ozon: List[NewsItem] = []
    general: List[NewsItem] = []

# Добавить retry декоратор к методам:
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((Exception,)),
    reraise=True
)
def select_and_format_marketplace_news(self, messages: List[Dict], marketplace: str, top_n: int = 10) -> List[Dict]:
    # Существующий код...

    # После парсинга JSON добавить валидацию:
    try:
        # Валидация через Pydantic
        validated_items = [NewsItem(**item) for item in selected]
        selected = [item.model_dump() for item in validated_items]
    except ValidationError as e:
        logger.error(f"Ошибка валидации JSON от Gemini: {e}")
        return []
```

**Команды:**

```bash
# 5. Установить зависимости
pip install tenacity pydantic

# 6. Проверка импорта
python -c "from services.gemini_client import GeminiClient; print('✅ Gemini импорт OK')"

# 7. Git diff
git diff --stat

# 8. Логирование
echo "[$(date)] C2: Добавлен retry и валидация Pydantic для Gemini" >> logs/migration_$(date +%Y-%m-%d).log

# 9. Коммит
git add services/gemini_client.py requirements.txt
git commit -m "[C2] Добавить retry logic и Pydantic валидацию для Gemini API"

# 10. Push
git push origin main
```

**Проверка:**
- ✅ Retry декоратор добавлен
- ✅ Pydantic схемы созданы
- ✅ Валидация работает
- ✅ requirements.txt обновлён
- ✅ Коммит создан

**Обновить:** Отметить C2 как ✅ в `DOROZHNAYA_KARTA.md`

---

## 📖 ОСТАЛЬНЫЕ ЭТАПЫ

Для остальных задач (C3-C5, D1-D2, E1-E10) следуйте аналогичному паттерну:

1. **Прочитать** соответствующий файл
2. **Внести** изменения согласно ROADMAP_ANALYSIS.md
3. **Проверить** синтаксис и импорты
4. **Просмотреть** git diff
5. **Залогировать** действие
6. **Закоммитить** с описательным сообщением
7. **Запушить** изменения
8. **Обновить** дорожную карту

---

## 🔄 ЗАВЕРШАЮЩИЙ РИТУАЛ

После каждой сессии выполнить:

```bash
# 1. Проверить все изменения
git status
git log --oneline -5

# 2. Убедиться что всё запушено
git push origin main

# 3. Обновить дорожную карту
# (вручную через Edit tool)

# 4. Записать в журнал прогресса
echo "
## $(date +%Y-%m-%d) (Сессия N)
- ✅ Выполнено: <список задач>
- 🔍 Проверено: <список проверок>
- 📍 Следующий шаг: <код следующей задачи>
" >> DOROZHNAYA_KARTA.md
```

**Напоминание пользователю:**
> ✅ Сессия завершена!
> Выполнено: [список задач]
> Следующий шаг: `Протокол, шаг <код>`
> Не забудьте: `git push origin main`

---

**Версия:** 1.0
**Последнее обновление:** 2025-10-11
