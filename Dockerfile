# Этап 1: сборка React фронтенда АРМ оператора
FROM node:22-alpine AS frontend-builder
WORKDIR /app/arm/frontend

COPY arm/frontend/package.json arm/frontend/package-lock.json ./
RUN npm ci

COPY arm/frontend/ ./
RUN npm run build

# Этап 2: среда выполнения Python симулятора и АРМ
FROM python:3.12-slim

# Установка uv из официального образа
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/amrsim-participants:/app" \
    PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Установка зависимостей Python через uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Копирование исходного кода модулей симулятора и контроллера
COPY team_dreamteam_4_0/ ./team_dreamteam_4_0/
COPY amrsim-participants/ ./amrsim-participants/
COPY scenarios/ ./scenarios/
COPY arm/ ./arm/
COPY results/ ./results/

# Копирование собранного SPA фронтенда
COPY --from=frontend-builder /app/arm/frontend/dist ./arm/frontend/dist

# Создание каталога вывода для логов и отчетов
RUN mkdir -p /app/out

EXPOSE 8000

CMD ["python", "arm/server.py", "--host", "0.0.0.0", "--port", "8000"]
