FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser --disabled-password --gecos "" spendwise && \
    chown -R spendwise:spendwise /app

COPY --chown=spendwise:spendwise app ./app
COPY --chown=spendwise:spendwise alembic.ini ./alembic.ini
COPY --chown=spendwise:spendwise migrations ./migrations

USER spendwise

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
