FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

COPY requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --requirement requirements.lock

COPY backend ./backend
COPY .env.example ./

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "aura_med.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
