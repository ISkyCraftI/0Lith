# 0Lith Cyber Range — Noise Generator
# =====================================
# Génère du trafic HTTP légitime pour simuler des utilisateurs normaux.
# Rend la détection d'attaques plus réaliste pour Blue Team.
#
# Build : docker build -t 0lith/noise-gen:latest .

FROM python:3.12-slim

RUN groupadd -r appuser \
    && useradd -r -g appuser -s /sbin/nologin appuser

WORKDIR /app
COPY --chown=appuser:appuser generator.py .

ENV TARGETS="" \
    INTENSITY=medium \
    PYTHONUNBUFFERED=1

USER appuser

# /tmp writable via tmpfs compose — healthcheck marker écrit par generator.py
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD test -f /tmp/healthy || exit 1

CMD ["python", "generator.py"]
