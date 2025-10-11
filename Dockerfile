FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

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

# По умолчанию запускаем listener
CMD ["python", "main.py", "listener"]
