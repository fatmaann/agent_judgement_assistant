FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    gpg \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Chromium для Selenium
RUN apt-get update \
    && apt-get install -y wget curl unzip chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем requirements.txt
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY *.py ./

# Создаем необходимые директории
RUN mkdir -p pdfs chroma_db

# Устанавливаем переменные окружения для Chromium
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROME_PATH=/usr/bin/chromium

# Запускаем бота
CMD ["python", "bot.py"]
