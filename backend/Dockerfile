FROM ghcr.io/astral-sh/uv@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Freeze third-party production dependency layer before copying frequently changing code.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM deps AS runtime

COPY alembic.ini ./
COPY backend ./backend
COPY docs ./docs

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend/src"

EXPOSE 3334

CMD ["uvicorn", "hypertrade.main:app", "--host", "0.0.0.0", "--port", "3334"]

# The operator TUI is a short-lived client image, not part of API/worker runtime.
FROM deps AS tui-deps

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra tui --no-install-project

FROM tui-deps AS tui

COPY alembic.ini ./
COPY backend ./backend
COPY docs ./docs

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra tui

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend/src"

# Evaluation dependencies and scripts stay out of the production image. The
# isolated deployment builds this target explicitly for reproducible baselines.
FROM runtime AS agent-eval

COPY scripts ./scripts

RUN uv sync --frozen --no-dev --extra agent-evals

# Freeze sandbox dev dependencies independently of `runtime` so code edits only rebuild the thin local package layer.
FROM deps AS sandbox-deps

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project

FROM sandbox-deps AS sandbox

COPY alembic.ini ./
COPY backend ./backend
COPY docs ./docs

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/backend/src"

USER 65532:65532

CMD ["python", "-m", "hypertrade.sandbox_service"]

FROM runtime AS production
