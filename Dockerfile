FROM python:3.11-slim

WORKDIR /app

# Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Меняй значение ниже, если Dokploy/Docker отдаёт старый код (всё ниже — без кеша).
# Или в Dokploy включи «Clean cache» / Rebuild без кеша.
ARG IMAGE_REVISION=2026-04-06-pg-lock
RUN echo "build=${IMAGE_REVISION}"

# Код бота и данных
COPY bot.py database.py word_api.py usage_metrics.py ./
COPY grammar/ ./grammar/
COPY content/ ./content/
COPY data/ ./data/

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "bot.py"]
