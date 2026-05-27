FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY pyproject.toml uv.lock alembic.ini ./
COPY backend ./backend
COPY docs ./docs

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend/src"

EXPOSE 3334

CMD ["uvicorn", "hypertrade.main:app", "--host", "0.0.0.0", "--port", "3334"]

