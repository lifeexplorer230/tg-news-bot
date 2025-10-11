#!/bin/bash
# Скрипт для автоматического запуска processor через cron
# Запускается ежедневно в 7:00 утра по Москве

cd /root/marketplace-news-bot

# Логирование
LOG_FILE="/root/marketplace-news-bot/logs/processor_cron.log"
mkdir -p /root/marketplace-news-bot/logs

echo "===========================================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Запуск processor через cron" >> "$LOG_FILE"
echo "===========================================================" >> "$LOG_FILE"

# Запускаем processor через docker compose
docker compose run --rm marketplace-listener python main.py processor >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Processor завершился успешно" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ Processor завершился с ошибкой (код: $EXIT_CODE)" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"
