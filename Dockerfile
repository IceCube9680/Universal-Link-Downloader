FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies (ffmpeg, aria2, ca-certificates, build tools for cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    aria2 \
    ca-certificates \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create runtime directories and non-root user
RUN mkdir -p /app/data /app/downloads /app/temp /app/logs && \
    useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app

USER botuser

VOLUME ["/app/data", "/app/downloads", "/app/logs"]

CMD ["python", "main.py"]
