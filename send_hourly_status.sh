#!/bin/bash
# Скрипт для отправки статуса Marketplace News Bot в Telegram каждый час

# Переходим в директорию проекта
cd /root/marketplace-news-bot

# Логируем время запуска
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Отправка статуса Marketplace News Bot..." >> /root/marketplace-news-bot/logs/hourly_status.log

# Запускаем скрипт статуса внутри контейнера
docker exec marketplace-listener python /app/test_status.py >> /root/marketplace-news-bot/logs/hourly_status.log 2>&1

# Проверяем результат
if [ $? -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Статус успешно отправлен" >> /root/marketplace-news-bot/logs/hourly_status.log
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Ошибка отправки статуса" >> /root/marketplace-news-bot/logs/hourly_status.log
fi

echo "---" >> /root/marketplace-news-bot/logs/hourly_status.log
