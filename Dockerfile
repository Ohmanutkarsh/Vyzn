FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies: FFmpeg and graphics libraries for headless OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency definition and install
COPY requirements-edge.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY vyzn/ /app/vyzn/
COPY frontend/ /app/frontend/
COPY public/ /app/public/
COPY static/ /app/static/
COPY config/ /app/config/
COPY run_edge.py /app/

# Ensure storage directory exists
RUN mkdir -p /data/clips

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/api/status || exit 1

ENTRYPOINT ["sh", "-c", "python run_edge.py --simulate 3 --api --port ${PORT:-8000}"]
