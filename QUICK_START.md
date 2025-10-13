# ⚡ Быстрый старт Marketplace News Bot

## 📝 Чек-лист подготовки

- [ ] Отдельный Telegram аккаунт (НЕ тот же что для AI News Bot!)
- [ ] API credentials от Telegram (<https://my.telegram.org/apps>)
- [ ] Gemini API key (<https://makersuite.google.com/app/apikey>)
- [ ] Два Telegram канала созданы (для Ozon и Wildberries)
- [ ] Подписал новый аккаунт на 200 каналов про маркетплейсы

---

## 🚀 5 шагов до запуска

### 1️⃣ Настрой .env

```bash
cp .env.example .env
nano .env
```

Заполни:

```
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=abc123...
TELEGRAM_PHONE=+79123456789

GEMINI_API_KEY=AIza...

MY_PERSONAL_ACCOUNT=@username
OZON_CHANNEL=@your_ozon_channel
WB_CHANNEL=@your_wb_channel
```

### 2️⃣ Настрой профили `config/profiles/*.yaml`

```yaml
publication:
  channel: "@your_digest_channel"
  preview_channel: "@your_preview_channel"
  header_template: "📌 Главные новости маркетплейсов за {date}"
  footer_template: "____________________________________\nПодпишись, чтобы быть в курсе: {channel}"
  notify_account: "@your_username"

marketplaces:
  - name: "ozon"
    target_channel: "@your_ozон_channel"
    keywords: ["ozon", "озон"]
  - name: "wildberries"
    target_channel: "@your_wb_channel"
    keywords: ["wildberries", "вб"]

status:
  enabled: true
  message_template: |
    🤖 **{bot_name} - Статус на {time}**
    📅 Дата: {date}
    📊 Собрано: {messages_today}, опубликовано: {published_today}
```

### 3️⃣ Собери Docker образ

```bash
docker-compose build
# ☕ Подожди 10-15 минут (скачивает torch ~2GB)
```

### 4️⃣ Авторизуйся в Telegram

```bash
docker-compose run marketplace-listener python main.py listener

# Введи код из Telegram
# После успешной авторизации: Ctrl+C
```

### 5️⃣ Запусти

```bash
# Listener в фоне (собирает сообщения 24/7)
docker-compose up -d marketplace-listener

# Проверь логи
docker-compose logs -f marketplace-listener
```

---

## ✅ Проверка работы

### Listener работает?

```bash
docker-compose ps
# Должен быть: marketplace-listener   Up

docker-compose logs marketplace-listener | tail -20
# Должно быть: "Подключение к Telegram успешно"
```

### БД заполняется?

```bash
sqlite3 data/marketplace_news.db "SELECT COUNT(*) FROM raw_messages"
# Должно расти со временем
```

---

## 🎯 Первый запуск обработки

```bash
# Запусти processor вручную (по умолчанию профиль marketplace)
docker-compose run --rm marketplace-processor python main.py processor

# Запуск с профилем ai
docker-compose run --rm marketplace-processor python main.py processor --profile ai

# Что произойдёт:
# 1. Обработает сообщения за последние 24 часа
# 2. Отберёт новости через Gemini по шаблонам профиля
# 3. Отправит на модерацию (инструкция из профиля)
# 4. После ответа модератора опубликует с заданным header/footer и уведомлениями
```

---

## ⏰ Автоматизация (cron)

```bash
crontab -e

# Добавь (обработка каждый день в 09:00):
0 9 * * * cd /root/marketplace-news-bot && docker-compose run --rm marketplace-processor python main.py processor >> /root/marketplace-news-bot/logs/cron.log 2>&1
```

---

## 🆘 Проблемы?

### "Session already running"

```bash
docker-compose down
sleep 5
docker-compose up -d marketplace-listener
```

### "Database locked"

```bash
docker-compose stop marketplace-listener
sleep 3
docker-compose up -d marketplace-listener
```

### "Gemini API error"

- Проверь API key в `.env`
- Проверь квоту: <https://makersuite.google.com/>

---

## 📊 Полезные команды

```bash
# Статус
docker-compose ps  # status должен быть "healthy" для listener

# Логи listener
docker-compose logs -f marketplace-listener

# Перезапуск
docker-compose restart marketplace-listener

# Остановить всё
docker-compose down

# Ребилд после изменений
docker-compose build --no-cache
```

---

## 🎉 Готово

Теперь бот:

- ✅ Собирает сообщения из 200 каналов 24/7
- ✅ Обрабатывает и отбирает лучшие новости через Gemini
- ✅ Публикует в два канала: Ozon и Wildberries

**Подробности:** см. [README.md](README.md)
