FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus

WORKDIR /app

# OCR 是运行时能力；中文语言包由 Debian 仓库统一管理，避免启动时联网下载。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the multilingual embedding model into the image so production does not
# download model files on the first user request.
ARG EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ENV EMBEDDING_CACHE_DIR=/opt/fastembed-cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${EMBEDDING_MODEL}', cache_dir='/opt/fastembed-cache')"

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "rm -rf /tmp/prometheus && mkdir -p /tmp/prometheus && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2}"]
