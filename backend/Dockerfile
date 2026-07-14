FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

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

# The operator TUI is a short-lived client image, not part of API/worker runtime.
FROM runtime AS tui

RUN uv sync --frozen --no-dev --extra tui

# Evaluation dependencies and scripts stay out of the production image. The
# isolated deployment builds this target explicitly for reproducible baselines.
FROM runtime AS agent-eval

COPY scripts ./scripts

RUN uv sync --frozen --no-dev --extra agent-evals

FROM runtime AS production
