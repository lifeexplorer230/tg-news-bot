FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Системные зависимости
RUN apt-get update \
    && apt-get install -y --no-install-recommends logrotate \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаём директории для данных и логов
RUN mkdir -p /app/data /app/logs

# Делаем main.py исполняемым
RUN chmod +x main.py

# Healthcheck: проверяем heartbeat-файл, который обновляет listener
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python docker/healthcheck.py || exit 1

# По умолчанию запускаем listener
CMD ["python", "main.py", "listener"]
