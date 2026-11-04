FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    ABACUS_DATA_DIR=/data \
    ABACUS_RUNS_DIR=/data/runs

WORKDIR /app

COPY pyproject.toml ./
COPY alembic.ini ./
COPY abacus/ ./abacus/
COPY practice/ ./practice/
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY frontend/ ./frontend/
RUN pip install --no-cache-dir . \
    && groupadd --system abacus \
    && useradd --system --gid abacus --uid 10001 --home-dir /nonexistent abacus

COPY problems/ ./problems/

RUN mkdir -p /data && chown -R abacus:abacus /data

USER 10001:10001
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]

CMD ["python", "-m", "uvicorn", "abacus.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
