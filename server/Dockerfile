# Canon API: FastAPI on uvicorn, installed with uv.
# Build context: server/

ARG PYTHON_IMAGE=python:3.12.15-slim-trixie

FROM ghcr.io/astral-sh/uv:0.11.33 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first, so source edits reuse this layer.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
# git reads a workspace's repository: its docs, their history and CODEOWNERS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 canon \
 && useradd --system --uid 10001 --gid canon --create-home --home-dir /home/canon canon

COPY --from=build /app/.venv /app/.venv
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# Repositories and caches the API writes while reading a workspace. A new volume takes this owner.
RUN mkdir -p /data && chown canon:canon /data

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FALKORDB_HOST=falkordb \
    FALKORDB_PORT=6379 \
    CANON_PROFILE=prod \
    CANON_DATA_DIR=/data

USER canon
WORKDIR /home/canon
EXPOSE 8790

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["canon", "serve", "--host", "0.0.0.0", "--port", "8790"]
