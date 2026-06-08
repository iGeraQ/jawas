FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema necesarias para Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry && poetry config virtualenvs.create false

# 1. Copiar los archivos de configuración primero (para aprovechar el caché de Docker)
COPY pyproject.toml poetry.lock* ./

# 2. Copiar el código fuente ANTES de instalar
COPY src/ ./src/

# 3. Ahora que el código existe, poetry podrá instalar el proyecto local
RUN poetry install --only main

# 4. Instalar Playwright
RUN playwright install chromium && playwright install-deps chromium