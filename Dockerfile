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

RUN pip install \
      "devpi-server>=6.10,<7" \
      "devpi-web>=5.0,<6" \
      "devpi-client>=7.0,<8"

COPY theme /app/theme
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 3141

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
