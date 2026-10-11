# Use a lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for sentence-transformers & cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the main application and all HTML files
COPY main.py .
COPY *.html .

# Expose the port used by FastAPI (7860 is common for HF Spaces)
EXPOSE 7860

# Command to start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
