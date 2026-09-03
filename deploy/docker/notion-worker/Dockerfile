FROM python:3.11-slim-bookworm

ARG JAA_NOTION_IMAGE_VERSION=development
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JAA_NOTION_IMAGE_VERSION=${JAA_NOTION_IMAGE_VERSION}

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 worker

WORKDIR /app
COPY pyproject.toml /app/
COPY job_application_agents /app/job_application_agents
RUN pip install --no-cache-dir .

USER worker
ENTRYPOINT ["python", "-m", "job_application_agents.plugins.notion.worker"]
