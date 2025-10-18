# Техническое задание на исправление провалившихся тестов

**Дата**: 2025-10-18
**Автор**: Claude Code
**Статус тестов**: 5 failed, 205 passed (97.6% success rate)
**Приоритет**: СРЕДНИЙ (функциональность работает, но есть edge cases)

---

## 1. PHONE MASKING SECURITY (auth.py) - ВЫСОКИЙ ПРИОРИТЕТ

### 1.1 Проблема: Функция не идемпотентна
**Тест**: `test_auth_security.py::TestPhoneMaskingSecurity::test_mask_idempotent`

**Текущее поведение**:
```python
mask_phone("+79252124626")  # → "+79****4626" ✅
mask_phone("+79****4626")   # → "+79****4626" ❌ (ожидается "***")
```

**Root Cause**:
- Функция `mask_phone()` не проверяет, содержит ли входная строка уже маску `****`
- При повторном применении берет первые 3 символа и последние 4, что для замаскированного номера дает тот же результат

**Требуемое поведение**:
- Если строка уже содержит `"****"` (уже замаскирована), вернуть `"***"`
- Защита от случайного логирования уже замаскированных номеров

**Решение**:
```python
def mask_phone(phone: str) -> str:
    """Маскирует номер телефона для безопасного логирования"""
    if not phone or len(phone) < 8:
        return "***"

    # Проверка на уже замаскированный номер
    if "****" in phone:
        return "***"

    # Маскировка: показываем +XX (2 символа кода страны) + 1 первую цифру + **** + 4 последних цифры
    return phone[:4] + "****" + phone[-4:]
```

---

### 1.2 Проблема: Показывает 6 цифр вместо 7
**Тест**: `test_auth_security.py::TestPhoneMaskingCompliance::test_mask_minimal_exposure`

**Текущее поведение**:
```python
mask_phone("+79252124626")  # → "+79****4626"
# Видимые цифры: 7, 9, 4, 6, 2, 6 = 6 цифр ❌
```

**Ожидаемое поведение**:
```python
mask_phone("+79252124626")  # → "+792****4626"
# Видимые цифры: 7, 9, 2, 4, 6, 2, 6 = 7 цифр ✅
# 3 префикс (код страны + 1 цифра) + 4 суффикс
```

**Root Cause**:
- Текущая реализация: `phone[:3] + "****" + phone[-4:]` показывает "+79" (только 2 цифры)
- Комментарий в тесте: "3 prefix + 4 suffix" означает 3 ЦИФРЫ, не включая "+"

**Решение**: Включено в код выше - `phone[:4]` вместо `phone[:3]`

**Файл**: `/root/tg-news-bot/auth.py:14-26`

**Критичность**: ВЫСОКАЯ (безопасность, PII compliance)

---

## 2. NEWSPROCESSOR EMBEDDING SERVICE - СРЕДНИЙ ПРИОРИТЕТ

### Проблема: AttributeError при использовании __new__()
**Тесты**:
- `test_processor_statuses.py::test_process_all_categories_marks_all_outcomes`
- `test_processor_statuses.py::test_process_all_categories_marks_moderator_rejections`

**Ошибка**:
```
AttributeError: 'NewsProcessor' object has no attribute '_embedding_service'
```

**Root Cause**:
1. Тесты используют `NewsProcessor.__new__(NewsProcessor)` для создания объекта **без вызова __init__**
2. `__init__` устанавливает `self._embedding_service = None` (строка 33)
3. Property `embeddings` (строка 139) проверяет `if self._embedding_service is None`
4. Атрибут не существует → AttributeError

**Текущий тестовый код** (`test_processor_statuses.py:74-122`):
```python
def make_processor(messages, moderation_enabled=False):
    processor = NewsProcessor.__new__(NewsProcessor)  # ❌ Обходит __init__
    processor.config = SimpleNamespace(...)
    processor.db = FakeDB(messages)
    # ... множество ручных установок атрибутов
    processor._gemini_client = SimpleNamespace(...)  # Мокает gemini
    # ❌ НЕ мокает _embedding_service!
    return processor
```

**Решение 1 (РЕКОМЕНДУЕТСЯ)**: Исправить тесты
```python
def make_processor(messages, moderation_enabled=False):
    processor = NewsProcessor.__new__(NewsProcessor)
    processor.config = SimpleNamespace(...)
    processor.db = FakeDB(messages)

    # ✅ Инициализируем все приватные атрибуты
    processor._embedding_service = None
    processor._gemini_client = None
    processor._rate_limiter = None
    processor._cached_published_embeddings = None
    processor._published_embeddings_matrix = None
    processor._published_embeddings_ids = None

    # ... остальная настройка

    # Мокаем embedding service
    fake_embedding_service = SimpleNamespace(
        encode_batch_async=lambda texts, batch_size=32: asyncio.coroutine(lambda: [[0.0] * 384] * len(texts))()
    )
    processor._embedding_service = fake_embedding_service

    processor._gemini_client = SimpleNamespace(...)
    return processor
```

**Решение 2 (АЛЬТЕРНАТИВА)**: Сделать property устойчивым
```python
# В services/news_processor.py:137-146
@property
def embeddings(self) -> EmbeddingService:
    # ✅ Используем hasattr вместо прямой проверки
    if not hasattr(self, '_embedding_service') or self._embedding_service is None:
        self._embedding_service = EmbeddingService(...)
    return self._embedding_service
```

**Файлы**:
- `/root/tg-news-bot/tests/test_processor_statuses.py:74-122`
- `/root/tg-news-bot/services/news_processor.py:137-146`

**Критичность**: СРЕДНЯЯ (тесты не проходят, но основной функционал работает)

**Рекомендация**: Использовать **Решение 1** - исправить тесты, т.к. это правильный паттерн моков

---

## 3. RATE LIMITER EDGE CASE - НИЗКИЙ ПРИОРИТЕТ

### Проблема: IndexError при max_requests=0
**Тест**: `test_rate_limiter.py::TestRateLimiterEdgeCases::test_zero_max_requests`

**Ошибка**:
```python
IndexError: deque index out of range
# В строке: sleep_time = self.per_seconds - (now - self.requests[0]).total_seconds()
```

**Root Cause**:
- При `max_requests=0` deque всегда пустой
- Условие `if len(self.requests) >= self.max_requests` → `if len([]) >= 0` → True
- Попытка обратиться к `self.requests[0]` на пустой deque → IndexError

**Текущий код** (`utils/rate_limiter.py:54-66`):
```python
if len(self.requests) >= self.max_requests:
    # ❌ Не проверяет, что deque не пустой
    sleep_time = self.per_seconds - (now - self.requests[0]).total_seconds()
    if sleep_time > 0:
        await asyncio.sleep(sleep_time)
        return await self.acquire()
```

**Решение**:
```python
if len(self.requests) >= self.max_requests:
    # ✅ Проверка на edge case: max_requests = 0
    if self.max_requests == 0:
        # Бесконечная блокировка - лимит установлен в 0 запросов
        logger.error("Rate limiter настроен на 0 запросов - бесконечная блокировка!")
        await asyncio.sleep(float('inf'))  # Или raise ValueError

    # Вычисляем время ожидания до освобождения первого слота
    sleep_time = self.per_seconds - (now - self.requests[0]).total_seconds()
    if sleep_time > 0:
        logger.warning(...)
        await asyncio.sleep(sleep_time)
        return await self.acquire()
```

**Альтернативное решение (валидация в __init__)**:
```python
def __init__(self, max_requests: int = 20, per_seconds: int = 60):
    # ✅ Валидация параметров
    if max_requests < 1:
        raise ValueError(f"max_requests должен быть >= 1, получено: {max_requests}")
    if per_seconds < 1:
        raise ValueError(f"per_seconds должен быть >= 1, получено: {per_seconds}")

    self.max_requests = max_requests
    self.per_seconds = per_seconds
    self.requests: deque[datetime] = deque()
    logger.info(...)
```

**Файл**: `/root/tg-news-bot/utils/rate_limiter.py:27-40, 54-66`

**Критичность**: НИЗКАЯ (edge case, в production не используется 0 запросов)

**Рекомендация**: Добавить валидацию в `__init__` и обновить тест

---

## ПРИОРИТИЗАЦИЯ ИСПРАВЛЕНИЙ

### 🔴 ВЫСОКИЙ ПРИОРИТЕТ (Безопасность)
1. **Phone Masking (auth.py)** - безопасность PII данных
   - Время: 15 минут
   - Сложность: Низкая
   - Риск: Минимальный

### 🟡 СРЕДНИЙ ПРИОРИТЕТ (Качество тестов)
2. **NewsProcessor Embedding Service** - тесты не проходят
   - Время: 30-45 минут
   - Сложность: Средняя
   - Риск: Средний (изменение тестов)

### 🟢 НИЗКИЙ ПРИОРИТЕТ (Edge case)
3. **RateLimiter Zero Requests** - нереалистичный сценарий
   - Время: 10 минут
   - Сложность: Низкая
   - Риск: Минимальный

---

## ПЛАН РЕАЛИЗАЦИИ

### Этап 1: Phone Masking (День 1, 15 мин)
1. Обновить `auth.py:14-26`
2. Запустить `pytest tests/test_auth_security.py::TestPhoneMasking -v`
3. Проверить, что все 28 тестов проходят

### Этап 2: NewsProcessor Tests (День 1, 45 мин)
1. Обновить `tests/test_processor_statuses.py:74-122` (функция `make_processor`)
2. Добавить моки для `_embedding_service` и всех приватных атрибутов
3. Запустить `pytest tests/test_processor_statuses.py -v`
4. Проверить, что 2 провалившихся теста теперь проходят

### Этап 3: RateLimiter Validation (День 2, 10 мин)
1. Добавить валидацию в `utils/rate_limiter.py:27-40`
2. Обновить тест или добавить обработку edge case
3. Запустить `pytest tests/test_rate_limiter.py::TestRateLimiterEdgeCases -v`

### Этап 4: Регрессионное тестирование (День 2, 10 мин)
```bash
pytest tests/ -v --tb=short
```
Ожидаемый результат: **210 passed, 0 failed**

---

## КРИТЕРИИ ПРИЕМКИ

✅ Все 210 тестов проходят
✅ Покрытие кода остается >= 91%
✅ Нет регрессий в существующей функциональности
✅ Phone masking соответствует GDPR/HIPAA требованиям
✅ Документация обновлена (если требуется)

---

## РИСКИ И МИТИГАЦИЯ

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Регрессия в phone masking | Низкая | Высокое | Запустить все 28 тестов безопасности |
| Поломка NewsProcessor | Средняя | Среднее | Запустить интеграционные тесты |
| Изменение API RateLimiter | Низкая | Низкое | Добавить deprecation warning |

---

## ДОПОЛНИТЕЛЬНЫЕ РЕКОМЕНДАЦИИ

1. **CI/CD**: Добавить pre-commit hook для запуска быстрых тестов
2. **Документация**: Обновить комментарии к `mask_phone()` с примерами
3. **Мониторинг**: Добавить метрики для RateLimiter (сколько раз блокировался)
4. **Code Review**: Все изменения должны пройти review перед merge

---

**Общее время на исправление**: 1.5-2 часа
**Сложность**: Низкая-Средняя
**Готовность к production**: После успешного прохождения всех тестов
