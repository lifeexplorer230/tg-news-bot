# 🛠️ Операционный плейбук

**Дата:** 2025-10-14

---

## 🚀 Развертывание

### Первоначальная настройка

1. **Клонирование проекта:**
   ```bash
   git clone https://github.com/lifeexplorer230/tg-news-bot.git
   cd tg-news-bot
   ```

2. **Установка зависимостей:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Конфигурация:**
   ```bash
   # Скопируйте example config
   cp config/base.yaml.example config/base.yaml

   # Создайте .env
   cat > .env <<EOF
   TELEGRAM_API_ID=your_api_id
   TELEGRAM_API_HASH=your_api_hash
   TELEGRAM_PHONE=+1234567890
   GEMINI_API_KEY=your_gemini_key
   EOF
   ```

4. **Авторизация Telegram:**
   ```bash
   python auth.py
   # Введите код из SMS
   ```

5. **Проверка:**
   ```bash
   # Проверьте что сессия создана
   ls -lh *.session

   # Запустите listener
   python main.py listener
   ```

---

## 🐳 Docker Deployment

### Сборка и запуск

```bash
# Сборка образа
docker compose build

# Запуск listener
docker compose up -d listener

# Запуск processor
docker compose up -d processor

# Проверка статуса
docker compose ps

# Логи
docker compose logs -f listener
```

### Обновление

```bash
# Остановка
docker compose down

# Pull новой версии
git pull origin main

# Пересборка
docker compose build

# Запуск
docker compose up -d
```

---

## 📊 Мониторинг

### Проверка работоспособности

1. **Healthcheck listener:**
   ```bash
   cat logs/listener.heartbeat
   # Должна быть свежая timestamp (< 3 минут)
   ```

2. **Логи:**
   ```bash
   tail -f logs/bot.log
   ```

3. **Статистика БД:**
   ```bash
   sqlite3 data/news_bot.db "
   SELECT
     COUNT(*) as total,
     SUM(CASE WHEN processed = 1 THEN 1 ELSE 0 END) as processed,
     SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) as published
   FROM raw_messages;
   "
   ```

4. **Docker статус:**
   ```bash
   docker ps
   docker stats
   ```

---

## 🔧 Обслуживание

### Очистка старых данных

```bash
# Удалить сообщения старше 30 дней
sqlite3 data/news_bot.db "
DELETE FROM raw_messages
WHERE date < datetime('now', '-30 days');
"

# Vacuum БД
sqlite3 data/news_bot.db "VACUUM;"
```

### Резервное копирование

```bash
# Бэкап БД
cp data/news_bot.db data/backups/news_bot_$(date +%Y%m%d).db

# Бэкап логов
tar -czf logs/backups/logs_$(date +%Y%m%d).tar.gz logs/*.log

# Автоматический бэкап (cron)
0 3 * * * /root/tg-news-bot/scripts/backup.sh
```

### Ротация логов

```bash
# Очистить старые логи (> 7 дней)
find logs/ -name "*.log" -mtime +7 -delete

# Сжать логи (> 1 дня)
find logs/ -name "*.log" -mtime +1 -exec gzip {} \;
```

---

## 🚨 Устранение неполадок

### Listener не работает

1. **Проверьте процесс:**
   ```bash
   ps aux | grep listener
   ```

2. **Проверьте логи:**
   ```bash
   tail -100 logs/bot.log | grep ERROR
   ```

3. **Проверьте сессию:**
   ```bash
   ls -lh *.session
   # Если файл < 1KB - пересоздайте через auth.py
   ```

4. **Перезапуск:**
   ```bash
   # Docker
   docker compose restart listener

   # Direct
   pkill -f "main.py listener"
   python main.py listener
   ```

### Processor не обрабатывает

1. **Проверьте необработанные сообщения:**
   ```bash
   sqlite3 data/news_bot.db "
   SELECT COUNT(*) FROM raw_messages WHERE processed = 0;
   "
   ```

2. **Проверьте Gemini API:**
   ```bash
   echo $GEMINI_API_KEY
   ```

3. **Запустите вручную:**
   ```bash
   python main.py processor
   ```

### БД заблокирована

1. **Проверьте процессы:**
   ```bash
   fuser data/news_bot.db
   ```

2. **Закройте процессы:**
   ```bash
   pkill -f "main.py"
   ```

3. **Проверьте WAL mode:**
   ```bash
   sqlite3 data/news_bot.db "PRAGMA journal_mode;"
   # Должно быть: wal
   ```

---

## 📈 Масштабирование

### Увеличение производительности

1. **Увеличить workers для processor:**
   ```yaml
   # config/base.yaml
   processor:
     batch_size: 100  # увеличить с 50
     max_workers: 4   # параллельная обработка
   ```

2. **Оптимизировать БД:**
   ```bash
   # Увеличить cache
   sqlite3 data/news_bot.db "PRAGMA cache_size = -64000;"
   ```

3. **Использовать отдельные профили:**
   ```bash
   # Разные listener для разных доменов
   docker compose up -d listener-marketplace
   docker compose up -d listener-ai
   ```

---

## 🔒 Безопасность

### Регулярные проверки

1. **Проверка secrets:**
   ```bash
   # Убедитесь что .env не в git
   git ls-files | grep .env
   # Должно быть пусто
   ```

2. **Обновление зависимостей:**
   ```bash
   pip list --outdated
   pip install --upgrade -r requirements.txt
   ```

3. **Проверка логов на ошибки:**
   ```bash
   grep -i "error\|exception\|traceback" logs/bot.log | tail -20
   ```

---

## 📝 Чек-лист деплоя

Перед релизом новой версии:

- [ ] Тесты пройдены: `pytest tests/ -v`
- [ ] Линтеры пройдены: `ruff check .`
- [ ] Бэкап БД создан
- [ ] Логи проверены на ошибки
- [ ] Healthcheck работает
- [ ] Docker образ собран
- [ ] Документация обновлена
- [ ] Changelog обновлен

---

## 📞 Эскалация

При критических проблемах:

1. Остановите listener: `docker compose stop listener`
2. Создайте бэкап: `./scripts/backup.sh`
3. Соберите диагностику:
   ```bash
   tar -czf diagnostic_$(date +%Y%m%d).tar.gz \
     logs/ \
     config/ \
     data/news_bot.db
   ```
4. Создайте GitHub issue с диагностикой

---

_Последнее обновление: 2025-10-14_
