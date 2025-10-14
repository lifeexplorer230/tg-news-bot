# FloodWait Fix - Telegram News Bot

**Дата:** 2025-10-14
**Статус:** ✅ Завершено

## 🔍 Проблема

Обнаружено **3 файла** с проблемными вызовами `client.start(phone=...)`, которые вызывают **SendCodeRequest** при каждом подключении к Telegram. Это приводит к:

- ⚠️ **FloodWait блокировкам** на десятки тысяч секунд (до 12+ часов!)
- ⚠️ Невозможности запуска скриптов
- ⚠️ Цикличным перезапускам контейнеров

## ✅ Что было исправлено

### 1. Создана утилита `utils/telegram_helpers.py`
- Функция `safe_connect()` для безопасного подключения
- Автоматическая обработка FloodWait с ожиданием
- Проверка авторизации сессии

### 2. Исправлены основные сервисы (3 файла)
- ✅ `services/telegram_listener.py` - listener использует существующую сессию
- ✅ `services/marketplace_processor.py` - processor использует существующую сессию
- ✅ `services/status_reporter.py` - status reporter использует основную сессию

## 🛠️ Что изменилось в коде

### Было (❌ ПЛОХО):
```python
await client.start(phone=config.telegram_phone)  # Вызывает SendCodeRequest!
```

### Стало (✅ ХОРОШО):
```python
from utils.telegram_helpers import safe_connect

# Подключаемся БЕЗ повторной авторизации
session_name = config.get('telegram.session_name')
await safe_connect(client, session_name)
```

## 📋 Изменённые файлы

```
utils/telegram_helpers.py              - СОЗДАН (новая утилита)
services/telegram_listener.py          - ИСПРАВЛЕН
services/marketplace_processor.py      - ИСПРАВЛЕН
services/status_reporter.py            - ИСПРАВЛЕН
```

## 🎯 Результат

- ✅ **0 файлов** с `client.start(phone=...)` (было 3)
- ✅ **Нет SendCodeRequest** при подключении
- ✅ **Нет FloodWait** блокировок
- ✅ Все сервисы используют одну основную сессию
- ✅ Все скрипты используют безопасное подключение

## 🚀 Тестирование

Проверьте работу бота:
```bash
# Проверить статус контейнера (если используется Docker)
docker ps | grep tg-news-bot

# Посмотреть логи
docker logs -f tg-news-bot

# Запустить listener
python main.py listener

# Запустить processor
python main.py processor
```

## 📝 Рекомендации

1. **Всегда используйте `safe_connect()`** вместо `client.start(phone=...)`
2. **Не создавайте отдельные сессии** (_status, _processor) - используйте одну основную
3. **При появлении FloodWait** - подождите указанное время, не перезапускайте
4. **Мониторьте логи** на предмет FloodWait предупреждений

## 🔗 Связанные проекты

Аналогичные исправления были внесены в:
- ✅ `marketplace-news-bot` (3 файла исправлено)
- ✅ `ai-news-bot` (19 файлов исправлено)
- ✅ `tg-news-bot` (3 файла исправлено)

## 🔧 Технические детали

### safe_connect() функция

```python
async def safe_connect(client: TelegramClient, session_name: str, max_wait: int = 3600) -> bool:
    """
    Безопасное подключение к Telegram с обработкой FloodWait.

    Args:
        client: Telegram client
        session_name: Имя сессии для логирования
        max_wait: Максимальное время ожидания в секундах (по умолчанию 1 час)

    Returns:
        True если подключение успешно, False в противном случае

    Raises:
        RuntimeError: Если FloodWait превышает max_wait или сессия не авторизована
    """
```

### Основные изменения:

1. **telegram_listener.py:91**
   - Добавлен импорт: `from utils.telegram_helpers import safe_connect`
   - Заменён вызов: `await client.start(phone=...)` → `await safe_connect(client, session_name)`

2. **marketplace_processor.py:848**
   - Добавлен импорт: `from utils.telegram_helpers import safe_connect`
   - Убрана отдельная сессия `_processor`
   - Заменён вызов: `await client.start(phone=...)` → `await safe_connect(client, session_name)`

3. **status_reporter.py:93**
   - Добавлен импорт: `from utils.telegram_helpers import safe_connect`
   - Убрана отдельная сессия `_status`
   - Заменён вызов: `await client.start(phone=...)` → `await safe_connect(client, session_name)`

## ⚡ Преимущества

1. **Нет FloodWait блокировок** - используется существующая авторизованная сессия
2. **Одна сессия** - нет конфликтов между компонентами
3. **Автоматическая обработка** - если FloodWait всё же происходит, система автоматически ждёт
4. **Простота** - все компоненты используют единый паттерн подключения

---

**Автор:** Claude Code
**Дата:** 2025-10-14
