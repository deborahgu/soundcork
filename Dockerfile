FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (ffmpeg needed for RadioBrowser audio)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY soundcork/ soundcork/

# Create non-root user (UID/GID 1000)
RUN addgroup --system --gid 1000 appgroup && \
    adduser --system --uid 1000 --gid 1000 --no-create-home appuser

# The app imports "from soundcork.bmx import ..." so /app must be on PYTHONPATH
# The app reads bmx_services.json, swupdate.xml, and media/ from CWD
ENV PYTHONPATH=/app
WORKDIR /app/soundcork

USER appuser

# Gunicorn with uvicorn workers, bind to all interfaces
# Override log files to stdout/stderr for container logging
CMD ["gunicorn", "-c", "gunicorn_conf.py", "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "--workers", "1", \
     "main:app"]
