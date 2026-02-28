FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY soundcork/ soundcork/

# The app imports "from soundcork.bmx import ..." so /app must be on PYTHONPATH
# The app reads bmx_services.json, swupdate.xml, and media/ from CWD
ENV PYTHONPATH=/app
WORKDIR /app/soundcork

# Gunicorn with uvicorn workers, bind to all interfaces
# Override log files to stdout/stderr for container logging
CMD ["gunicorn", "-c", "gunicorn_conf.py", "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "--workers", "2", \
     "main:app"]
