FROM python:3.11-slim

WORKDIR /app

# Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код бота и данных
COPY bot.py database.py word_api.py ./
COPY data/ ./data/

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "bot.py"]
