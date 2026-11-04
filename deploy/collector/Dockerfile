# Independent Collector runtime: no Central Server, PostgreSQL server or Ollama.
FROM python:3.12-slim-bookworm AS collector
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY deploy/collector/requirements.lock /tmp/collector-requirements.lock
RUN pip install --no-cache-dir -r /tmp/collector-requirements.lock \
    && useradd --uid 10001 --create-home collector \
    && mkdir -p /var/lib/linker-collector /run/collector-key \
    && chown 10001:10001 /var/lib/linker-collector /run/collector-key \
    && chmod 700 /var/lib/linker-collector /run/collector-key
COPY collector ./collector
COPY shared ./shared
RUN chmod -R a+rX /app
USER 10001:10001
ENTRYPOINT ["python", "-m", "collector", "--config", "/var/lib/linker-collector/setup/config.toml"]
CMD ["run"]
