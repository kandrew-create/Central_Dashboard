FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY server ./server
COPY collector ./collector
COPY shared ./shared
COPY deploy/requirements.lock ./deploy/requirements.lock
RUN pip install --no-cache-dir -r deploy/requirements.lock && pip install --no-deps --no-cache-dir . \
    && useradd --uid 10001 --create-home scada \
    && chmod -R a+rX /app
USER 10001:10001
CMD ["uvicorn", "server.app.ingestion:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS test
USER root
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir '.[test]'
COPY tests ./tests
COPY deploy/bootstrap_roles.sql ./deploy/bootstrap_roles.sql
CMD ["pytest", "-q"]
