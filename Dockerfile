FROM node:24-bookworm-slim AS ui
WORKDIR /app/frontend
RUN npm install -g pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim
WORKDIR /app
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY src/ src/
COPY sql/ sql/
COPY reports/model_metrics.json reports/model_metrics.json
COPY data/raw/ data/raw/
COPY --from=ui /app/frontend/dist frontend/dist
RUN useradd --create-home research && mkdir -p /app/.runtime /app/.cache /app/data/processed /app/data/features && chown -R research:research /app
USER research
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "src.platform.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
