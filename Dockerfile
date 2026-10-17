FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEVPI_SERVERDIR=/data/server \
    DEVPI_SECRETFILE=/data/.secret \
    DEVPI_THEME_DIR=/app/theme

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --requirement /app/requirements.txt \
 && pip check

COPY theme /app/theme
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 3141

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
