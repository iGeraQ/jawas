FROM python:3.12-slim

WORKDIR /app

RUN pip install poetry && poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-dev

RUN playwright install chromium && playwright install-deps chromium

COPY src/ ./src/
