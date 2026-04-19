# 0Lith Cyber Range — Vulnerable Web Application
# ================================================
# Flask app avec SQLi / XSS / Auth-Bypass contrôlables via env vars.
# NE JAMAIS déployer en production.
#
# Build : docker build -t 0lith/vuln-webapp:latest .
# Run   : docker run --rm -p 8080:8080 0lith/vuln-webapp:latest

FROM python:3.12-slim

# curl pour le HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir flask==3.0.3 \
    && groupadd -r appuser \
    && useradd -r -g appuser -s /sbin/nologin appuser \
    && mkdir -p /var/log /app \
    && touch /var/log/webapp.log \
    && chown -R appuser:appuser /var/log/webapp.log /app

WORKDIR /app
COPY --chown=appuser:appuser app.py .

# /tmp est writable (tmpfs via compose) pour la DB SQLite
ENV VULN_SQLI=true \
    VULN_XSS=true \
    VULN_AUTH_BYPASS=true \
    ACCESS_LOG_PATH=/var/log/webapp.log \
    FLAG_VALUE=FLAG{0lith_cyber_range_pwned} \
    PYTHONUNBUFFERED=1

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fs http://localhost:8080/health || exit 1

CMD ["python", "app.py"]
