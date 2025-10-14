# 📜 Правила разработки

**Дата:** 2025-10-14

---

## ✅ Best Practices

### 1. FloodWait Protection

**ВСЕГДА используйте safe_connect():**

```python
# ❌ ПЛОХО - вызывает SendCodeRequest
await client.start(phone=config.telegram_phone)

# ✅ ХОРОШО - использует существующую сессию
from utils.telegram_helpers import safe_connect
session_name = config.get('telegram.session_name')
await safe_connect(client, session_name)
```

**Причина:** `client.start(phone=...)` запрашивает SMS код каждый раз, вызывая FloodWait блокировку.

---

### 2. Session Management

**Правила работы с сессиями:**

- ✅ Одна сессия для всех компонентов
- ✅ Храните .session в sessions/
- ✅ Добавьте *.session в .gitignore
- ❌ НЕ создавайте отдельные сессии (_status, _processor)
- ❌ НЕ коммитьте .session файлы

---

### 3. Database Access

**WAL mode обязателен:**

```python
# database/db.py
cursor.execute("PRAGMA journal_mode=WAL")
```

**Retry логика:**

```python
# Используйте существующий retry декоратор
@retry_on_locked(max_retries=5, delay=0.5)
def my_database_operation():
    ...
```

**Не открывайте БД в нескольких процессах:**
- Каждый компонент должен иметь свой Database instance
- Или использовать connection pooling

---

### 4. Configuration

**Структура профилей:**

```
config/
  ├── base.yaml          # Общие настройки
  └── profiles/
      ├── marketplace.yaml  # Переопределения
      └── ai.yaml
```

**Загрузка:**

```python
# main.py
config = load_config(profile='marketplace')

# Приоритет: profile > base
value = config.get('key.subkey', default_value)
```

---

### 5. Logging

**Структурированные логи:**

```python
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Хорошие логи
logger.info(f"Обработано {count} сообщений за {duration}s")
logger.error(f"Ошибка API: {error}", exc_info=True)

# Плохие логи
logger.info("ok")
logger.debug("test")
```

**Уровни логирования:**
- DEBUG: Детальная диагностика
- INFO: Нормальные события
- WARNING: Необычные ситуации
- ERROR: Ошибки с recovery
- CRITICAL: Фатальные ошибки

---

### 6. Gemini API

**Retry логика обязательна:**

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10)
)
def call_gemini_api():
    ...
```

**Валидация ответов:**

```python
from pydantic import BaseModel

class GeminiResponse(BaseModel):
    posts: list
    reasoning: str

# Валидируйте JSON
response = GeminiResponse.parse_obj(json_data)
```

---

### 7. Testing

**Структура тестов:**

```
tests/
  ├── test_database.py
  ├── test_gemini_client.py
  ├── test_embeddings.py
  └── conftest.py  # Fixtures
```

**Используйте mocks:**

```python
from unittest.mock import patch, MagicMock

@patch('services.gemini_client.genai')
def test_gemini_call(mock_genai):
    mock_genai.generate_content.return_value = MagicMock()
    ...
```

**Запуск тестов:**

```bash
# Все тесты
pytest tests/ -v

# С coverage
pytest tests/ --cov --cov-report=html

# Конкретный тест
pytest tests/test_database.py::test_save_message -v
```

---

### 8. Git Workflow

**Commit messages:**

```bash
# Хорошие
git commit -m "fix: FloodWait protection в listener"
git commit -m "feat: Добавлен профиль для AI новостей"
git commit -m "docs: Обновлен README"

# Плохие
git commit -m "fix"
git commit -m "update"
git commit -m "changes"
```

**Формат:**
- `fix:` - исправление бага
- `feat:` - новая функциональность
- `docs:` - изменения документации
- `refactor:` - рефакторинг без изменения функциональности
- `test:` - добавление тестов
- `chore:` - обслуживание (зависимости, конфигурация)

---

## 🚫 Что НЕ делать

### 1. Telegram API

- ❌ НЕ используйте `client.start(phone=...)`
- ❌ НЕ создавайте несколько сессий с одним phone
- ❌ НЕ игнорируйте FloodWaitError
- ❌ НЕ делайте rate limiting самостоятельно (используйте Telethon встроенный)

### 2. Database

- ❌ НЕ используйте check_same_thread=False без WAL mode
- ❌ НЕ делайте long-running transactions
- ❌ НЕ открывайте БД в нескольких процессах одновременно
- ❌ НЕ игнорируйте "database is locked" ошибки

### 3. Configuration

- ❌ НЕ хардкодьте значения в коде
- ❌ НЕ коммитьте .env файлы
- ❌ НЕ храните секреты в git
- ❌ НЕ изменяйте base.yaml напрямую (используйте profiles)

### 4. Code Style

- ❌ НЕ используйте `import *`
- ❌ НЕ игнорируйте type hints
- ❌ НЕ пишите функции > 50 строк (разбивайте)
- ❌ НЕ игнорируйте warnings от ruff/black

---

## 🔧 Рефакторинг

### Когда рефакторить:

- ✅ Функция > 50 строк
- ✅ Дублирование кода (DRY principle)
- ✅ Сложная циклическая сложность
- ✅ Плохая читаемость

### Как рефакторить:

1. **Напишите тесты** для текущего поведения
2. **Рефакторьте** код
3. **Запустите тесты** - они должны пройти
4. **Commit** с описанием изменений

### Не рефакторьте:

- ❌ Без тестов
- ❌ Вместе с новой функциональностью
- ❌ Критичные компоненты без review

---

## 📦 Dependencies

### Добавление новых зависимостей:

1. **Проверьте необходимость** - возможно уже есть альтернатива
2. **Проверьте лицензию** - должна быть совместимой
3. **Добавьте в requirements.txt** с версией:
   ```
   new-package==1.2.3
   ```
4. **Обновите Docker** если нужны системные пакеты
5. **Протестируйте** установку

### Обновление зависимостей:

```bash
# Проверить outdated
pip list --outdated

# Обновить конкретный пакет
pip install --upgrade package-name

# Заморозить версии
pip freeze > requirements.txt
```

---

## 🐳 Docker

### Best practices:

- ✅ Используйте multi-stage builds
- ✅ Минимизируйте количество layers
- ✅ Кэшируйте зависимости
- ✅ Используйте .dockerignore
- ❌ НЕ используйте latest tags
- ❌ НЕ запускайте как root

### Volumes:

```yaml
volumes:
  - ./data:/app/data          # БД
  - ./logs:/app/logs          # Логи
  - ./sessions:/app/sessions  # Сессии
```

---

## 📊 Performance

### Оптимизация:

1. **Batch operations** где возможно
   ```python
   # ✅ Batch
   embeddings = model.encode(texts, batch_size=32)

   # ❌ Loop
   embeddings = [model.encode(text) for text in texts]
   ```

2. **Lazy loading** для тяжелых сервисов
   ```python
   @property
   def embedding_service(self):
       if self._embedding_service is None:
           self._embedding_service = EmbeddingService()
       return self._embedding_service
   ```

3. **Кэширование** где уместно
   ```python
   from functools import lru_cache

   @lru_cache(maxsize=128)
   def expensive_operation(param):
       ...
   ```

---

## 🔐 Security

### Секреты:

- ✅ Используйте .env для локальной разработки
- ✅ Используйте environment variables в production
- ✅ Используйте GitHub Secrets для CI/CD
- ❌ НЕ коммитьте API keys
- ❌ НЕ логируйте секреты

### Валидация входных данных:

```python
# Валидируйте данные от пользователя
if not message.text or len(message.text) > 10000:
    return

# Санитизация для SQL
# (SQLite параметризованные запросы безопасны)
cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
```

---

_Последнее обновление: 2025-10-14_
