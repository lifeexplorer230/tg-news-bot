# 🔧 Частые проблемы и решения

**Дата:** 2025-10-14

---

## 🚫 Telegram FloodWait

### Проблема: FloodWaitError при запуске

**Симптомы:**
```
telethon.errors.rpcerrorlist.FloodWaitError: A wait of 12345 seconds is required
```

**Причина:** Использование `client.start(phone=...)` вызывает SendCodeRequest

**Решение:**
✅ Используйте `safe_connect()` вместо `client.start(phone=...)`

```python
from utils.telegram_helpers import safe_connect

# ❌ ПЛОХО
await client.start(phone=config.telegram_phone)

# ✅ ХОРОШО
session_name = config.get('telegram.session_name')
await safe_connect(client, session_name)
```

**Документация:** `FLOODWAIT_FIX.md`

---

### Проблема: Session not authorized

**Симптомы:**
```
RuntimeError: Telegram сессия 'bot_session' не авторизована
```

**Причина:** Отсутствует или невалидный .session файл

**Решение:**
1. Запустите авторизацию:
   ```bash
   python auth.py
   ```
2. Проверьте наличие файла:
   ```bash
   ls -la *.session
   ```
3. Убедитесь что путь к сессии правильный в config.yaml

---

## 🗄️ Database Issues

### Проблема: Database is locked

**Симптомы:**
```
sqlite3.OperationalError: database is locked
```

**Причина:** Concurrent access к SQLite

**Решение:**
1. Проверьте что включен WAL mode:
   ```python
   # database/db.py должен содержать:
   cursor.execute("PRAGMA journal_mode=WAL")
   ```
2. Используйте retry логику (уже реализована)
3. Не открывайте БД в нескольких процессах одновременно

---

### Проблема: No such table

**Симптомы:**
```
sqlite3.OperationalError: no such table: raw_messages
```

**Причина:** БД не инициализирована

**Решение:**
```bash
# Удалите старую БД
rm -f data/news_bot.db

# Перезапустите - схема создастся автоматически
python main.py listener
```

---

## 🤖 Gemini API Issues

### Проблема: API Key invalid

**Симптомы:**
```
google.api_core.exceptions.InvalidArgument: Invalid API key
```

**Причина:** Неверный GEMINI_API_KEY

**Решение:**
1. Проверьте .env файл:
   ```bash
   cat .env | grep GEMINI_API_KEY
   ```
2. Получите новый ключ: https://makersuite.google.com/app/apikey
3. Обновите .env и перезапустите

---

### Проблема: Quota exceeded

**Симптомы:**
```
google.api_core.exceptions.ResourceExhausted: Quota exceeded
```

**Причина:** Превышен лимит запросов к Gemini

**Решение:**
1. Подождите до сброса квоты (обычно 1 минута)
2. Уменьшите частоту запусков processor
3. Оптимизируйте количество сообщений на обработку

---

## 🐳 Docker Issues

### Проблема: Container keeps restarting

**Симптомы:**
```bash
docker ps
# STATUS: Restarting (1) 5 seconds ago
```

**Причина:** Приложение падает при старте

**Решение:**
1. Проверьте логи:
   ```bash
   docker logs tg-news-bot-listener
   ```
2. Проверьте healthcheck:
   ```bash
   docker inspect tg-news-bot-listener | grep -A 10 Health
   ```
3. Временно отключите restart policy:
   ```yaml
   # docker-compose.yml
   restart: "no"  # вместо "always"
   ```

---

### Проблема: Volume permission denied

**Симптомы:**
```
PermissionError: [Errno 13] Permission denied: '/app/data/'
```

**Причина:** Неверные права на volume

**Решение:**
```bash
# Дайте права на директории
sudo chown -R $USER:$USER data/ logs/ sessions/

# Или в docker-compose.yml добавьте:
user: "${UID}:${GID}"
```

---

## 📝 Configuration Issues

### Проблема: Config key not found

**Симптомы:**
```
KeyError: 'telegram.api_id'
```

**Причина:** Отсутствует ключ в config.yaml

**Решение:**
1. Проверьте base.yaml:
   ```bash
   cat config/base.yaml | grep api_id
   ```
2. Проверьте profile:
   ```bash
   cat config/profiles/marketplace.yaml
   ```
3. Убедитесь что загружается правильный профиль

---

### Проблема: Profile not found

**Симптомы:**
```
FileNotFoundError: config/profiles/myprofile.yaml not found
```

**Причина:** Указан несуществующий профиль

**Решение:**
```bash
# Проверьте доступные профили
ls config/profiles/

# Используйте существующий профиль
python main.py --profile marketplace listener
```

---

## 🧪 Testing Issues

### Проблема: Tests fail with "No module"

**Симптомы:**
```
ModuleNotFoundError: No module named 'services'
```

**Причина:** Неверный PYTHONPATH при запуске тестов

**Решение:**
```bash
# Запускайте из корня проекта
cd /root/tg-news-bot
pytest tests/ -v

# Или установите пакет в dev mode
pip install -e .
```

---

### Проблема: Mock не работает

**Симптомы:**
Тесты вызывают реальный API вместо mock

**Причина:** Неверный путь в mock

**Решение:**
```python
# ❌ ПЛОХО
@patch('gemini_client.genai')

# ✅ ХОРОШО
@patch('services.gemini_client.genai')
```

---

## 🔍 Debugging Tips

### Включить debug логи:

```python
# utils/logger.py
logging.basicConfig(level=logging.DEBUG)
```

### Проверить healthcheck:

```bash
cat logs/listener.heartbeat
```

### Проверить сессию:

```bash
ls -lh *.session
# Должен быть > 1KB
```

### Проверить БД:

```bash
sqlite3 data/news_bot.db "SELECT COUNT(*) FROM raw_messages;"
```

---

## 📞 Эскалация

Если проблема не решается:
1. Проверьте логи: `logs/bot.log`
2. Проверьте документацию: `FLOODWAIT_FIX.md`, `README.md`
3. Проверьте архитектуру: `memory-bank/arkhitektura.md`
4. Создайте GitHub issue с полными логами

---

_Последнее обновление: 2025-10-14_
