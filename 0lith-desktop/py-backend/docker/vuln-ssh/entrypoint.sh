#!/bin/bash
# 0Lith Cyber Range — vuln-ssh entrypoint
# Configure sshd depuis les env vars et démarre en foreground.
set -e

# Génère les host keys si elles n'existent pas encore
ssh-keygen -A 2>/dev/null || true

# Mot de passe root depuis env (défaut intentionnellement faible: toor)
echo "root:${ROOT_PASSWORD:-toor}" | chpasswd

# PermitRootLogin
if grep -q "^PermitRootLogin" /etc/ssh/sshd_config; then
    sed -i "s/^PermitRootLogin.*/PermitRootLogin ${ALLOW_ROOT_LOGIN:-yes}/" /etc/ssh/sshd_config
else
    echo "PermitRootLogin ${ALLOW_ROOT_LOGIN:-yes}" >> /etc/ssh/sshd_config
fi

# PasswordAuthentication
if grep -q "^PasswordAuthentication" /etc/ssh/sshd_config; then
    sed -i "s/^PasswordAuthentication.*/PasswordAuthentication ${PASSWORD_AUTH:-yes}/" /etc/ssh/sshd_config
else
    echo "PasswordAuthentication ${PASSWORD_AUTH:-yes}" >> /etc/ssh/sshd_config
fi

# Répertoire PID requis par sshd
mkdir -p /run/sshd

# Log de démarrage dans auth.log
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "${TS} sshd[1]: Starting sshd (root_login=${ALLOW_ROOT_LOGIN:-yes}, password_auth=${PASSWORD_AUTH:-yes})" >> /var/log/auth.log

# Lance sshd en foreground (-D) avec logs sur stderr (-e → Docker les capture)
exec /usr/sbin/sshd -D -e
