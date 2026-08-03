# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.12.0 AS uv

FROM python:3.13.14-slim-bookworm AS builder

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /workspace/backend

COPY ai/pyproject.toml /workspace/ai/pyproject.toml
COPY ai/src /workspace/ai/src
COPY backend/pyproject.toml backend/uv.lock ./

RUN uv sync --locked --no-dev


FROM python:3.13.14-slim-bookworm AS runtime

ENV PATH="/workspace/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace/backend

COPY --from=builder /workspace/backend/.venv .venv
COPY --from=builder /workspace/ai /workspace/ai
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY backend/app ./app

EXPOSE 8000

CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
