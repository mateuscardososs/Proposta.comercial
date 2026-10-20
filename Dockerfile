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
        libgomp1 \
        tesseract-ocr \
        tesseract-ocr-por \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY requirements-voice.txt /app/requirements-voice.txt

RUN pip install --upgrade pip \
    && pip install -r /app/requirements-voice.txt \
    && pip install 'pypdfium2>=4.25,<6'

COPY . /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/output /app/doc_templates /app/data/output /app/data/doc_templates \
    && chmod +x /app/docker/entrypoint.sh \
    && chown -R app:app /app

ENV LIBREOFFICE_CMD=/usr/bin/soffice \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    APP_RELOAD=false \
    APP_ENV_FILE=/dev/null \
    DB_WAIT_TIMEOUT=90 \
    DB_WAIT_INTERVAL=2 \
    HF_HUB_OFFLINE=1 \
    TESSERACT_CMD=/usr/bin/tesseract \
    TESSERACT_DATA_DIR=/usr/share/tesseract-ocr/5/tessdata \
    LLM_PROVIDER=gemini

EXPOSE 8000

USER app:app

ENTRYPOINT ["/app/docker/entrypoint.sh"]
