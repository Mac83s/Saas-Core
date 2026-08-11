# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14.6
ARG UV_VERSION=0.11.32
ARG DEPLOYMENT=core-only

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim-trixie AS builder

ARG DEPLOYMENT

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    DEPLOYMENT=${DEPLOYMENT} \
    DEPLOYMENT_PROFILE_PATH=/app/deployment.json

WORKDIR /app

COPY apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY apps/backend/manage.py ./manage.py
COPY apps/backend/src ./src
COPY packages/contracts/site-blocks ./contracts/site-blocks
COPY deployments/${DEPLOYMENT}/deployment.json ./deployment.json

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev && \
    /opt/venv/bin/python manage.py collectstatic --noinput \
      --settings=saas_core.config.settings.test

FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

RUN groupadd --gid ${APP_GID} app && \
    useradd --no-log-init --uid ${APP_UID} --gid ${APP_GID} \
      --home-dir /app --create-home app

ENV DJANGO_SETTINGS_MODULE=saas_core.config.settings.container \
    DEPLOYMENT_PROFILE_PATH=/app/deployment.json \
    SITE_BLOCK_CONTRACTS_PATH=/app/contracts/site-blocks \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /app/manage.py ./manage.py
COPY --from=builder --chown=app:app /app/src ./src
COPY --from=builder --chown=app:app /app/contracts ./contracts
COPY --from=builder --chown=app:app /app/staticfiles ./staticfiles
COPY --from=builder --chown=app:app /app/deployment.json ./deployment.json

USER app:app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live/', timeout=2)"]

CMD ["sh", "-c", "mkdir -p /tmp/prometheus && rm -f /tmp/prometheus/*.db && exec gunicorn saas_core.config.wsgi:application --bind=0.0.0.0:8000 --workers=2 --threads=2 --timeout=30 --graceful-timeout=20 --error-logfile=-"]
