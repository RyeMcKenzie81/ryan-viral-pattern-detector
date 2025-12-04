FROM python:3.11-slim

# Prevent Python from writing bytecode (.pyc files)
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data/raw_apify data/normalized exports downloads audio_production

# Make start scripts executable
RUN chmod +x start.sh

# Default: Start FastAPI API (override with Railway per-service startCommand)
# Options for startCommand:
#   Streamlit: streamlit run viraltracker/ui/app.py --server.port $PORT --server.address 0.0.0.0
#   FastAPI:   uvicorn viraltracker.api.app:app --host 0.0.0.0 --port $PORT
#   Cron web:  uvicorn viraltracker.web.app:app --host 0.0.0.0 --port $PORT
CMD ["bash", "start.sh"]