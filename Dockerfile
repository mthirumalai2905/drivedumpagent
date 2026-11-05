FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini alembic.ini
COPY alembic alembic
COPY backend backend
COPY main.py main.py

RUN mkdir -p /app/logs && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["python", "main.py"]
