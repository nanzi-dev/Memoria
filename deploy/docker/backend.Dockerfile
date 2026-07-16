FROM python:3.11-slim

ARG TORCH_VERSION=2.2.2+cpu
ARG PYTORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
RUN pip install --upgrade pip \
    && pip install --extra-index-url "${PYTORCH_CPU_INDEX_URL}" "torch==${TORCH_VERSION}" \
    && pip install -r requirements.txt

COPY src ./src
COPY config ./config

RUN mkdir -p /app/data/sqlite_db /app/data/chroma_db /app/models

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/ready', timeout=5).read()"

CMD ["uvicorn", "memoria.main:app", "--host", "0.0.0.0", "--port", "8001"]
