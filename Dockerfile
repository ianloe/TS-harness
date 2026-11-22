FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TS_HARNESS_DATA_DIR=/data \
    TS_HARNESS_CONFIG_PATH=/data/settings.yaml \
    TS_HARNESS_DB__URL=sqlite:////data/ts_harness.db

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY docs ./docs
COPY policies ./policies
COPY workflows ./workflows

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 tsharness \
    && mkdir -p /data \
    && chown -R tsharness:tsharness /app /data

USER tsharness

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["ts-harness", "serve", "--host", "0.0.0.0", "--port", "8000"]
