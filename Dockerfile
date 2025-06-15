# Use Python 3.9 slim image
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
ENV RAILWAY_ENVIRONMENT=production

# Install system dependencies for Chromium
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    xvfb \
    fonts-liberation \
    fonts-dejavu-core \
    fontconfig \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create tmp directory for workflows
RUN mkdir -p tmp/logs

# Expose port (Railway will set PORT env var)
EXPOSE $PORT

# Start command with virtual display and dynamic port
CMD xvfb-run -a -s '-screen 0 1920x1080x24' python -m uvicorn backend.api:app --host 0.0.0.0 --port ${PORT:-8000} 