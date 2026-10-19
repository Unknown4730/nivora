FROM node:22.14.0-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_BASE_PATH=/app/
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
RUN npm run build

FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    AURA_MED_DATA_DIR=/app/.runtime \
    AURA_MED_FRONTEND_DIR=/app/frontend/dist

WORKDIR /app

COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --requirement requirements.lock

COPY backend ./backend
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.runtime \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn aura_med.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
