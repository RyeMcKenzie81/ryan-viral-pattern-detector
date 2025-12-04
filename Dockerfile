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

# Make start script executable
RUN chmod +x start.sh

# Start API server (Railway will set PORT environment variable)
CMD ["bash", "start.sh"]