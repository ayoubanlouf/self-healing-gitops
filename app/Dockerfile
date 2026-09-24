# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime environment
FROM python:3.11-slim AS runner

WORKDIR /app

# Create non-root user
RUN groupadd -g 65532 appgroup && \
    useradd -u 65532 -g appgroup -s /bin/sh -M appuser

# Copy installed wheels and dependencies
COPY --from=builder /install /usr/local
COPY main.py .

# Fix ownership
RUN chown -R 65532:65532 /app

USER 65532:65532

ENV PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
