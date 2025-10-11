# 🔧 COMMON ISSUES
## Частые проблемы и решения

**Версия:** 1.0
**Последнее обновление:** 2025-10-11

---

## 🐍 PYTHON & ИМПОРТЫ

### Проблема: ModuleNotFoundError

```bash
# Ошибка
ModuleNotFoundError: No module named 'xxx'

# Решение 1: Установить зависимость
pip install <пакет>

# Решение 2: Проверить PYTHONPATH
echo $PYTHONPATH
export PYTHONPATH=/root/marketplace-news-bot:$PYTHONPATH

# Решение 3: Запускать из корня проекта
cd /root/marketplace-news-bot
python -c "import services.gemini_client"
```

### Проблема: ImportError в circular imports

```bash
# Ошибка
ImportError: cannot import name 'X' from partially initialized module

# Решение: Переместить импорт внутрь функции
# Было:
from database.db import Database

# Стало:
def my_function():
    from database.db import Database
    db = Database(...)
```

### Проблема: AttributeError

```bash
# Ошибка
AttributeError: 'Database' object has no attribute 'check_duplicate'

# Решение 1: Проверить что метод добавлен
grep "def check_duplicate" database/db.py

# Решение 2: Перезагрузить модуль
python -c "
import importlib
import database.db
importlib.reload(database.db)
"
```

---

## 💾 БАЗА ДАННЫХ

### Проблема: database is locked

```bash
# Ошибка
sqlite3.OperationalError: database is locked

# Причина: Несколько процессов обращаются к БД одновременно

# Решение 1: Включить WAL mode
sqlite3 ./data/marketplace_news.db "PRAGMA journal_mode=WAL;"

# Решение 2: Каждый компонент использует своё подключение
# (См. задачу C1 в дорожной карте)

# Решение 3: Закрыть все подключения
ps aux | grep python
kill <PID_процесса_с_БД>

# Решение 4: Проверить timeout
# В database/db.py при создании connection:
sqlite3.connect(db_path, timeout=30.0)
```

### Проблема: Миграция схемы не применилась

```bash
# Проверить текущую схему
sqlite3 ./data/marketplace_news.db ".schema raw_messages"

# Добавить поле вручную (если автомиграция не сработала)
sqlite3 ./data/marketplace_news.db "ALTER TABLE raw_messages ADD COLUMN rejection_reason TEXT;"

# Проверить что поле добавлено
sqlite3 ./data/marketplace_news.db "PRAGMA table_info(raw_messages);"
```

### Проблема: OperationalError: no such table

```bash
# Ошибка
sqlite3.OperationalError: no such table: raw_messages

# Решение: Инициализировать БД
python -c "
from database.db import Database
db = Database('./data/marketplace_news.db')
print('✅ БД инициализирована')
db.close()
"

# Проверить таблицы
sqlite3 ./data/marketplace_news.db ".tables"
```

---

## 🤖 TELEGRAM

### Проблема: FloodWaitError

```bash
# Ошибка
telethon.errors.FloodWaitError: A wait of X seconds is required

# Причина: Слишком много запросов к Telegram API

# Решение: Добавить задержку
import asyncio
await asyncio.sleep(X)  # X секунд из ошибки
```

### Проблема: SessionPasswordNeededError

```bash
# Ошибка
telethon.errors.SessionPasswordNeededError

# Причина: Аккаунт защищён 2FA

# Решение: Ввести пароль при авторизации
# В main.py или telegram_listener.py:
await client.start(phone=phone, password=lambda: input('2FA password: '))
```

### Проблема: Multiple clients with same session

```bash
# Ошибка
Warnings about multiple sessions

# Решение: Использовать разные имена сессий
# В status_reporter.py:
status_session = config.get('telegram.session_name') + '_status'
```

---

## 🔮 GEMINI API

### Проблема: google.api_core.exceptions.ResourceExhausted

```bash
# Ошибка
ResourceExhausted: 429 Quota exceeded

# Решение 1: Добавить retry с exponential backoff (задача C2)

# Решение 2: Уменьшить частоту запросов
# Добавить задержку между запросами:
import time
time.sleep(2)
```

### Проблема: JSONDecodeError при парсинге ответа

```bash
# Ошибка
json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

# Причина: Gemini вернул не JSON или частичный ответ

# Решение 1: Логировать сырой ответ
logger.error(f"Сырой ответ Gemini: {response.text}")

# Решение 2: Добавить валидацию (задача C2 - Pydantic)

# Решение 3: Fallback на пустой список
try:
    result = json.loads(response_text)
except json.JSONDecodeError:
    logger.error("Не удалось распарсить JSON")
    result = []
```

### Проблема: ValidationError от Pydantic

```bash
# Ошибка
pydantic.ValidationError: 1 validation error for NewsItem

# Решение: Логировать и пропускать невалидные элементы
validated_items = []
for item in selected:
    try:
        validated_items.append(NewsItem(**item))
    except ValidationError as e:
        logger.warning(f"Невалидный элемент: {e}")
        continue
```

---

## 📦 GIT

### Проблема: Merge conflicts

```bash
# Ошибка
CONFLICT (content): Merge conflict in <файл>

# Решение 1: Отменить merge
git merge --abort

# Решение 2: Разрешить конфликт вручную
# Открыть файл, найти:
<<<<<<< HEAD
код из текущей ветки
=======
код из мержащейся ветки
>>>>>>> <branch>

# Выбрать нужный вариант, удалить маркеры, сохранить

# Добавить и закоммитить
git add <файл>
git commit -m "Разрешён конфликт в <файл>"
```

### Проблема: Diverged branches

```bash
# Ошибка
Your branch and 'origin/main' have diverged

# Решение 1: Rebase (если коммиты не запушены)
git pull --rebase origin main

# Решение 2: Merge (безопаснее)
git pull origin main

# Решение 3: Force push (ОПАСНО, только для своей ветки)
git push origin <branch> --force
```

### Проблема: Detached HEAD

```bash
# Ошибка
You are in 'detached HEAD' state

# Решение: Вернуться на ветку
git checkout main

# Или создать новую ветку из текущего состояния
git checkout -b new-branch-name
```

---

## 🔧 КОНФИГУРАЦИЯ

### Проблема: KeyError при чтении config

```bash
# Ошибка
KeyError: 'some.nested.key'

# Решение: Использовать get с дефолтным значением
# Было:
value = config['some']['nested']['key']

# Стало:
value = config.get('some.nested.key', default_value)
```

### Проблема: YAML parsing error

```bash
# Ошибка
yaml.scanner.ScannerError: ...

# Причина: Неправильная структура YAML

# Решение: Проверить синтаксис
python -c "
import yaml
with open('config.yaml') as f:
    config = yaml.safe_load(f)
print('✅ YAML валиден')
"

# Или онлайн: https://www.yamllint.com/
```

---

## 🧪 ТЕСТЫ

### Проблема: Тесты не находятся

```bash
# Ошибка
collected 0 items

# Решение 1: Проверить что файлы называются test_*.py
ls tests/

# Решение 2: Запустить из корня проекта
cd /root/marketplace-news-bot
pytest tests/

# Решение 3: Указать путь явно
pytest tests/test_database.py
```

### Проблема: Fixture not found

```bash
# Ошибка
fixture 'db' not found

# Решение: Добавить conftest.py с фикстурами
# tests/conftest.py:
import pytest
from database.db import Database

@pytest.fixture
def db():
    db = Database(':memory:')
    yield db
    db.close()
```

---

## 📊 ПРОИЗВОДИТЕЛЬНОСТЬ

### Проблема: Медленная загрузка модели embeddings

```bash
# Проблема: SentenceTransformer загружается долго (~30 секунд)

# Решение: Lazy loading (задача B1)
# В marketplace_processor.py:
self._embeddings = None

@property
def embeddings(self):
    if self._embeddings is None:
        self._embeddings = EmbeddingService()
    return self._embeddings
```

### Проблема: Долгие запросы к БД

```bash
# Проблема: get_unprocessed_messages() медленная

# Решение 1: Добавить индексы (уже есть)
sqlite3 ./data/marketplace_news.db "CREATE INDEX IF NOT EXISTS idx_processed ON raw_messages(processed, date);"

# Решение 2: Ограничить выборку
messages = db.get_unprocessed_messages(hours=24)  # Вместо hours=168
```

---

## 📝 ЛОГИРОВАНИЕ

### Проблема: Логи не пишутся в файл

```bash
# Проверить конфиг логирования
python -c "
from utils.logger import setup_logger
logger = setup_logger('test')
logger.info('Test message')
"

# Проверить права на директорию
ls -la logs/
mkdir -p logs
chmod 755 logs/
```

### Проблема: Дублирование логов

```bash
# Причина: Множественные вызовы setup_logger

# Решение: Использовать logging.getLogger (задача C7)
import logging
logger = logging.getLogger(__name__)
```

---

## 🔍 ОТЛАДКА

### Включить debug режим

```bash
# В utils/logger.py или main.py:
logging.basicConfig(level=logging.DEBUG)

# Или в config.yaml:
logging:
  level: "DEBUG"
```

### Трассировка ошибок

```bash
# Добавить полный traceback
import traceback
try:
    ...
except Exception as e:
    logger.error(f"Ошибка: {e}")
    logger.error(traceback.format_exc())
```

### Интерактивная отладка

```bash
# Добавить breakpoint
import pdb; pdb.set_trace()

# Или использовать ipdb
pip install ipdb
import ipdb; ipdb.set_trace()
```

---

## 📋 ЧЕК-ЛИСТ: ДИАГНОСТИКА ПРОБЛЕМЫ

1. **Воспроизвести:**
   - [ ] Можете воспроизвести проблему?
   - [ ] В каких условиях появляется?

2. **Логи:**
   - [ ] Есть ли traceback?
   - [ ] Что в логах перед ошибкой?

3. **Изменения:**
   - [ ] Что изменялось последним?
   - [ ] Какой последний рабочий коммит?

4. **Окружение:**
   - [ ] Версия Python: `python --version`
   - [ ] Установлены зависимости: `pip list`
   - [ ] Запуск из корня проекта: `pwd`

5. **Проверки:**
   - [ ] Синтаксис: `python -m py_compile <файл>`
   - [ ] Импорт: `python -c "import <модуль>"`
   - [ ] БД: `sqlite3 <db> ".tables"`

---

## 📝 ШАБЛОН ЗАПИСИ ПРОБЛЕМЫ

Копируйте и заполняйте:

```
### ПРОБЛЕМА: <краткое описание> - YYYY-MM-DD HH:MM

**Категория:** Python / БД / Telegram / Gemini / Git / Конфиг / Тесты / Другое

**Симптомы:**
<описание ошибки>

**Воспроизведение:**
```bash
<команды для воспроизведения>
```

**Traceback:**
```
<полный traceback если есть>
```

**Решение:**
```bash
<команды для решения>
```

**Причина:** <анализ причины>
**Профилактика:** <как предотвратить в будущем>
```

Сохранить в: `logs/issue_YYYY-MM-DD_HH-MM.log`

---

**Версия:** 1.0
**Будет дополняться** по мере выполнения миграции
