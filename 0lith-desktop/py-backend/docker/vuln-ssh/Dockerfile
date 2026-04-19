# 0Lith Cyber Range — Vulnerable SSH Server
# ==========================================
# Simule un serveur SSH intentionnellement mal configuré :
#   - Login root avec mot de passe par défaut (toor)
#   - PasswordAuthentication activé
#   - Flag dans /root/flag.txt
#
# NE JAMAIS exposer sur un réseau de production.
# Exception USER root : SSH server requiert root pour bind port 22 et chpasswd.
#
# Build : docker build -t 0lith/vuln-ssh:latest .

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/log /run/sshd \
    && touch /var/log/auth.log

# Flag dans /root/ (accessible uniquement après login root)
RUN echo "FLAG{0lith_ssh_compromised}" > /root/flag.txt \
    && chmod 600 /root/flag.txt

# Config sshd de base — entrypoint.sh personnalise au runtime
RUN printf '\
Port 22\n\
ListenAddress 0.0.0.0\n\
Protocol 2\n\
HostKey /etc/ssh/ssh_host_rsa_key\n\
HostKey /etc/ssh/ssh_host_ed25519_key\n\
PermitRootLogin yes\n\
PasswordAuthentication yes\n\
UsePAM yes\n\
PrintMotd no\n\
LogLevel INFO\n\
SyslogFacility AUTH\n\
' > /etc/ssh/sshd_config

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV ROOT_PASSWORD=toor \
    ALLOW_ROOT_LOGIN=yes \
    PASSWORD_AUTH=yes

# Root requis — serveur SSH intentionnellement mal configuré
# USER root (défaut)
EXPOSE 22

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD bash -c 'echo > /dev/tcp/localhost/22' 2>/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
