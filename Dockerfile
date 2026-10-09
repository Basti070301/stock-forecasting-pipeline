# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS wheels
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements-docker.lock ./
RUN pip wheel --no-cache-dir --require-hashes -r requirements-docker.lock -w /wheels

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/app/.cache/huggingface HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
RUN groupadd --gid 10001 stockintel && useradd --uid 10001 --gid 10001 --no-create-home stockintel
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/*.whl && rm -rf /wheels
WORKDIR /app
COPY src/ src/
COPY sql/ sql/
COPY reports/model_metrics.json reports/model_metrics.json
COPY data/raw/ reference/raw/
RUN mkdir -p /app/data/raw/prices /app/data/raw/profiles /app/data/processed /app/data/features /app/.runtime /app/.cache/huggingface && chown -R 10001:10001 /app/data /app/.runtime /app/.cache
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=8s --start-period=60s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=5)"]
CMD ["python", "-m", "uvicorn", "src.platform.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-server-header"]
