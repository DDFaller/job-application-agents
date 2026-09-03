FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install Playwright and dependencies
RUN pip install --no-cache-dir \
    playwright \
    google-cloud-firestore \
    google-cloud-storage \
    pyyaml

# Install Chromium browser binary
RUN playwright install chromium

# Copy application package
COPY . /workspace/
RUN pip install --no-cache-dir -e .

CMD ["python", "-m", "job_application_agents.auto_apply.worker"]
