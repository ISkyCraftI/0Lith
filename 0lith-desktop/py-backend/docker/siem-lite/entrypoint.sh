#!/bin/sh
# 0Lith Cyber Range — siem-lite entrypoint
set -e

mkdir -p /var/log/siem
touch /var/log/siem/consolidated.log

# Log de démarrage dans le fichier consolidé
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "${TS} | 127.0.0.1 | siem-lite | Starting siem-lite, listening on UDP 5514" >> /var/log/siem/consolidated.log

# Lance rsyslog en foreground (-n) avec la config dédiée
exec rsyslogd -n -f /etc/rsyslog-siem.conf
