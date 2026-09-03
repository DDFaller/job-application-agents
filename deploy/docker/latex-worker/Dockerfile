FROM python:3.11-slim-bookworm

ARG JAA_RENDER_IMAGE_VERSION=development
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JAA_RENDER_IMAGE_VERSION=${JAA_RENDER_IMAGE_VERSION}

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      texlive-xetex texlive-fonts-recommended texlive-fonts-extra texlive-latex-extra poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 worker

WORKDIR /app
COPY pyproject.toml /app/
COPY job_application_agents /app/job_application_agents
RUN pip install --no-cache-dir .

ENV PORT=8080
EXPOSE 8080

USER worker
ENTRYPOINT ["python", "-m", "job_application_agents.render_service.worker"]
