FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY deploy ./deploy
COPY .env.example ./
COPY config.example.yaml ./

RUN pip install --no-cache-dir .[dev]

RUN mkdir -p /app/data /app/logs /app/exports

CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]
