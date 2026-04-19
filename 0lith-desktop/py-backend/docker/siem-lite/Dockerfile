# 0Lith Cyber Range — SIEM-lite
# ================================
# Collecteur syslog léger : reçoit les messages UDP syslog de tous les services
# et les écrit dans /var/log/siem/consolidated.log
#
# Port : 5514/udp (non-root). Pour port 514 standard, ajouter
#        CAP_NET_BIND_SERVICE dans le compose.
#
# Blue Team lit les logs via le volume monté sur /var/log/siem.
#
# Build : docker build -t 0lith/siem-lite:latest .

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends rsyslog \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser \
    && useradd -r -g appuser -s /sbin/nologin appuser \
    && mkdir -p /var/log/siem \
    && chown -R appuser:appuser /var/log/siem

COPY rsyslog-siem.conf /etc/rsyslog-siem.conf
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
    && chown appuser:appuser /etc/rsyslog-siem.conf

# 5514 (non-root) — pas d'accès internet, réseau internal Docker uniquement
EXPOSE 5514/udp

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD test -f /var/log/siem/consolidated.log || exit 1

USER appuser
ENTRYPOINT ["/entrypoint.sh"]
