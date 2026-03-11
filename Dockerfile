FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice \
        fonts-dejavu \
        fonts-liberation \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/output /app/doc_templates \
    && chmod +x /app/docker/entrypoint.sh

ENV LIBREOFFICE_CMD=/usr/bin/soffice \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    APP_RELOAD=false \
    DB_WAIT_TIMEOUT=90 \
    DB_WAIT_INTERVAL=2

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
