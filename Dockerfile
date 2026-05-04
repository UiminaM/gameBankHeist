FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -e . --no-cache-dir

COPY src/ ./src/
COPY soul/ ./soul/
COPY skills/ ./skills/
COPY prompts/ ./prompts/

EXPOSE 8000 9100

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
