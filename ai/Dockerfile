# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.12.0 AS uv

FROM python:3.13.14-slim-bookworm

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace/ai

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY tests ./tests

RUN uv sync --locked

CMD ["uv", "run", "--no-sync", "pytest", "-m", "not live_provider"]
