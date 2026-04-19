"""
Purple Team — Cyber Range Lifecycle Manager
============================================
Gestion du cycle de vie Docker Compose pour les environnements de simulation.

Le Cyber Range est un micro-réseau conteneurisé éphémère :
- Réseau Docker --internal (aucun accès internet)
- Runtime gVisor (--runtime=runsc) pour isolation syscall
- cap_drop: ALL sur chaque conteneur
- Détruit intégralement après chaque match (docker compose down -v)

Example:
    async with CyberRange(config) as cyber_range:
        await cyber_range.wait_healthy(timeout=60)
        result = await cyber_range.exec_command("vuln-webapp", "ls /")
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .scenario_generator import ScenarioConfig, ServiceConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPOSE_FILE_HEADER = """\
# Généré dynamiquement par Purple Team — NE PAS ÉDITER
# seed={seed}  difficulty={difficulty}
# AVERTISSEMENT: Ce fichier configure des services intentionnellement vulnérables.
#                Ne jamais exposer sur un réseau de production.
"""

NOISE_GEN_IMAGE = "0lith/noise-gen:latest"
SIEM_LITE_IMAGE = "0lith/siem-lite:latest"
NOISE_GEN_IP_SUFFIX = ".100"  # ex: 10.42.1.100
SIEM_LITE_IP_SUFFIX = ".200"  # ex: 10.42.1.200

DOCKER_NETWORK_NAME = "cyber-range-net"
GVISOR_RUNTIME = "runsc"

# Timeout health check par défaut (secondes)
DEFAULT_HEALTH_TIMEOUT = 120
# Intervalle de polling health check (secondes)
HEALTH_POLL_INTERVAL = 3

# ---------------------------------------------------------------------------
# Security filter constants for exec_command
# ---------------------------------------------------------------------------

# Patterns qui bloquent immédiatement une commande (accès hôte / escape)
_BLOCKED_SUBSTRINGS = [
    "docker",    # pas de docker-in-docker
    "mount",     # pas de montage filesystem
    "nsenter",   # pas d'escape namespace
    "/proc/1",   # accès aux processus hôte
    "/proc/self",
]

# Regex pour détecter les adresses IP dans une commande
_IP_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")


# ---------------------------------------------------------------------------
# Status & Result types
# ---------------------------------------------------------------------------

class RangeStatus(Enum):
    """États du Cyber Range."""
    IDLE = "idle"
    DEPLOYING = "deploying"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    TEARING_DOWN = "tearing_down"
    DESTROYED = "destroyed"
    ERROR = "error"


@dataclass
class ServiceHealth:
    """Résultat du health check d'un service.

    Attributes:
        name: Nom logique du service.
        ip: Adresse IP dans le réseau interne.
        port: Port exposé.
        healthy: True si le service répond correctement.
        latency_ms: Latence de la vérification en millisecondes.
        error: Message d'erreur si unhealthy, None sinon.
    """

    name: str
    ip: str
    port: int
    healthy: bool
    latency_ms: float = 0.0
    error: str | None = None


@dataclass
class ExecResult:
    """Résultat d'une commande exécutée dans un conteneur.

    Attributes:
        service: Nom du service cible.
        command: Commande exécutée.
        stdout: Sortie standard.
        stderr: Sortie d'erreur.
        exit_code: Code de retour (0 = succès).
        duration_ms: Durée d'exécution en millisecondes.
        truncated: True si la sortie a été tronquée pour sécurité.
    """

    service: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float = 0.0
    truncated: bool = False

    @property
    def success(self) -> bool:
        """True si exit_code == 0."""
        return self.exit_code == 0


# ---------------------------------------------------------------------------
# Cyber Range Manager
# ---------------------------------------------------------------------------

class CyberRange:
    """Gère le cycle de vie complet d'un environnement de simulation Docker.

    Peut être utilisé comme context manager async ou manuellement via
    deploy() / teardown().

    Attributes:
        config: ScenarioConfig définissant les services à déployer.
        logs_dir: Répertoire de sortie pour les logs SIEM.
        status: État courant du range.
        compose_file: Chemin vers le docker-compose.yml généré.

    Example:
        range = CyberRange(scenario_config, logs_dir=Path("/tmp/olith-logs"))
        await range.deploy()
        await range.wait_healthy(timeout=120)
        result = await range.exec_command("vuln-webapp", "cat /flag.txt")
        await range.teardown()
    """

    def __init__(
        self,
        config: ScenarioConfig,
        logs_dir: Path | None = None,
        use_gvisor: bool = True,
        project_name: str | None = None,
    ) -> None:
        """Initialise le Cyber Range.

        Args:
            config: ScenarioConfig du scénario à déployer.
            logs_dir: Répertoire pour les logs SIEM. Si None, crée un tmpdir.
            use_gvisor: Si True, utilise le runtime gVisor (runsc).
                        Mettre False si gVisor n'est pas installé (dev/test).
            project_name: Nom du projet Docker Compose.
                          Si None, généré depuis le seed.
        """
        self.config = config
        self.logs_dir = logs_dir or Path(tempfile.mkdtemp(prefix="olith-siem-"))
        self.use_gvisor = use_gvisor
        self.status = RangeStatus.IDLE
        self._project_name = project_name or f"olith-range-{config.seed}"
        self._compose_dir: Path | None = None
        self.compose_file: Path | None = None
        self._service_healths: dict[str, ServiceHealth] = {}

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "CyberRange":
        """Deploy le range au début du context."""
        await self.deploy()
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Teardown automatique à la sortie du context."""
        await self.teardown()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def deploy(self) -> None:
        """Déploie le Cyber Range : génère le compose, lance les conteneurs.

        Raises:
            RuntimeError: Si le Range est déjà déployé ou si Docker échoue.
            OSError: Si docker / docker-compose n'est pas disponible.
        """
        if self.status not in (RangeStatus.IDLE, RangeStatus.DESTROYED):
            raise RuntimeError(f"Cannot deploy: current status is {self.status}")

        self.status = RangeStatus.DEPLOYING
        logger.info(f"Deploying Cyber Range seed={self.config.seed}")

        self._compose_dir = Path(tempfile.mkdtemp(prefix="olith-range-"))
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        compose_content = self._generate_compose_yaml()
        self.compose_file = self._compose_dir / "docker-compose.yml"
        self.compose_file.write_text(compose_content, encoding="utf-8")

        logger.debug(f"Compose file written to {self.compose_file}")

        await self._run_compose_up()

    async def teardown(self, force: bool = False) -> None:
        """Détruit entièrement le Cyber Range (docker compose down -v).

        Args:
            force: Si True, force même si status est DEPLOYING.
        """
        if self.status == RangeStatus.DESTROYED:
            return
        if self.status == RangeStatus.IDLE and not force:
            return

        self.status = RangeStatus.TEARING_DOWN
        logger.info(f"Tearing down Cyber Range seed={self.config.seed}")

        try:
            await self._run_compose_down()
        finally:
            if self._compose_dir and self._compose_dir.exists():
                shutil.rmtree(self._compose_dir, ignore_errors=True)
            self.status = RangeStatus.DESTROYED
            logger.info("Cyber Range destroyed")

    async def wait_healthy(self, timeout: int = DEFAULT_HEALTH_TIMEOUT) -> bool:
        """Attend que tous les services soient healthy.

        Args:
            timeout: Temps maximum d'attente en secondes.

        Returns:
            True si tous les services sont healthy avant timeout, False sinon.
        """
        # TODO: Implémenter le polling des health checks Docker par service
        # Stratégie: docker inspect --format='{{.State.Health.Status}}' <container>
        # Fallback: tenter une connexion TCP sur (ip, port)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            healths = await self.check_health()
            all_healthy = all(h.healthy for h in healths.values())
            if all_healthy:
                self.status = RangeStatus.HEALTHY
                logger.info("All services healthy")
                return True
            await asyncio.sleep(HEALTH_POLL_INTERVAL)

        unhealthy = [n for n, h in self._service_healths.items() if not h.healthy]
        logger.warning(f"Health timeout after {timeout}s — unhealthy: {unhealthy}")
        self.status = RangeStatus.DEGRADED
        return False

    async def check_health(self) -> dict[str, ServiceHealth]:
        """Vérifie la santé de tous les services déployés.

        Exécute les health checks de tous les services en parallèle.
        Timeout global implicite : 5 tentatives × 2s backoff = 10s max par service.

        Returns:
            Dict nom_service → ServiceHealth.
        """
        results = await asyncio.gather(
            *[self._check_service_health(svc) for svc in self.config.services],
            return_exceptions=False,
        )
        for health in results:
            self._service_healths[health.name] = health
        return self._service_healths

    async def _check_service_health(
        self,
        svc: "ServiceConfig",
        max_retries: int = 5,
        backoff: float = 2.0,
        connect_timeout: float = 3.0,
    ) -> ServiceHealth:
        """Vérifie la santé d'un service individuel avec retry.

        Strategy:
        - vuln-webapp (port HTTP) : GET http://{ip}:{port}/
        - vuln-ssh               : TCP connect port 22
        - siem-lite              : UDP send/recv port 5514
        - autres                 : TCP connect sur le port déclaré

        Args:
            svc: Configuration du service à vérifier.
            max_retries: Nombre de tentatives avant d'abandonner.
            backoff: Pause en secondes entre deux tentatives.
            connect_timeout: Timeout par tentative de connexion.

        Returns:
            ServiceHealth avec healthy=True si au moins une tentative réussit.
        """
        loop = asyncio.get_event_loop()
        last_error: str | None = None

        for attempt in range(max_retries):
            t0 = time.monotonic()
            try:
                if "webapp" in svc.name:
                    # HTTP check
                    await loop.run_in_executor(
                        None, self._http_check, svc.ip, svc.port, connect_timeout
                    )
                elif "siem" in svc.name:
                    # UDP check — siem-lite écoute sur UDP 5514
                    await loop.run_in_executor(
                        None, self._udp_check, svc.ip, 5514, connect_timeout
                    )
                else:
                    # TCP connect (SSH, db, ftp, …)
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(svc.ip, svc.port),
                        timeout=connect_timeout,
                    )
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass

                latency_ms = (time.monotonic() - t0) * 1000
                logger.info(
                    f"  ✅ {svc.name} ({svc.ip}:{svc.port}) "
                    f"healthy ({latency_ms:.0f}ms, attempt {attempt + 1})"
                )
                return ServiceHealth(
                    name=svc.name,
                    ip=svc.ip,
                    port=svc.port,
                    healthy=True,
                    latency_ms=latency_ms,
                )

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < max_retries - 1:
                    await asyncio.sleep(backoff)

        logger.warning(
            f"  ❌ {svc.name} ({svc.ip}:{svc.port}) unhealthy "
            f"after {max_retries} attempts: {last_error}"
        )
        return ServiceHealth(
            name=svc.name,
            ip=svc.ip,
            port=svc.port,
            healthy=False,
            error=last_error,
        )

    @staticmethod
    def _http_check(ip: str, port: int, timeout: float = 3.0) -> None:
        """GET http://{ip}:{port}/ — lève une exception si non-200 ou timeout.

        Raises:
            urllib.error.URLError: Si la connexion échoue.
            urllib.error.HTTPError: Si le status HTTP est >= 400 et < 500.
        """
        url = f"http://{ip}:{port}/"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(256)  # consomme quelques octets pour valider la connexion

    @staticmethod
    def _udp_check(ip: str, port: int, timeout: float = 2.0) -> None:
        """Envoie un paquet UDP à {ip}:{port} et vérifie l'absence d'ICMP unreachable.

        Note: UDP étant sans connexion, une absence d'erreur indique que le port
        est vraisemblablement ouvert. Certains OS retournent ConnectionRefusedError
        via ICMP unreachable si le port est fermé.

        Raises:
            OSError: Si un ICMP port-unreachable est reçu immédiatement.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.connect((ip, port))
            s.send(b"\x00")
            # On attend brièvement pour capter un ICMP unreachable éventuel.
            # S'il n'arrive pas dans le délai, on considère le port ouvert.
            try:
                s.recvfrom(64)
            except socket.timeout:
                pass  # Pas de réponse = siem-lite opérationnel (rsyslog n'ACKe pas)

    async def exec_command(
        self,
        service_name: str,
        command: str,
        timeout: int = 30,
        max_output_bytes: int = 4096,
    ) -> ExecResult:
        """Exécute une commande dans un conteneur (proxy Purple Team).

        Le Purple Team exécute la commande et retourne le résultat à Red.
        Red n'a JAMAIS accès direct aux conteneurs — c'est le proxy de sécurité.

        Args:
            service_name: Nom du service cible (ex: "vuln-webapp").
            command: Commande shell à exécuter.
            timeout: Timeout en secondes.
            max_output_bytes: Taille max de la sortie (troncature de sécurité).

        Returns:
            ExecResult avec stdout, stderr, exit_code.

        Raises:
            ValueError: Si le service_name n'existe pas dans le scénario.
            RuntimeError: Si le Range n'est pas en état HEALTHY ou DEGRADED.
        """
        if self.status not in (RangeStatus.HEALTHY, RangeStatus.DEGRADED):
            raise RuntimeError(f"Cannot exec: range status is {self.status}")

        svc = self._get_service(service_name)
        if svc is None:
            raise ValueError(f"Unknown service: {service_name!r}")

        # ── Filtrage de sécurité ──────────────────────────────────────────────
        block_reason = self._check_command_security(command)
        if block_reason:
            logger.warning(
                f"exec_command BLOCKED [{service_name}]: {command!r} — {block_reason}"
            )
            return ExecResult(
                service=service_name,
                command=command,
                stdout="",
                stderr=f"[SECURITY] Command blocked: {block_reason}",
                exit_code=126,  # 126 = permission denied (convention POSIX)
            )

        logger.debug(f"exec_command [{service_name}]: {command!r}")

        # Nom du conteneur Docker Compose: {project_name}-{service_name}-1
        container = f"{self._project_name}-{service_name}-1"
        cmd_args = ["docker", "exec", container, "sh", "-c", command]

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            return ExecResult(
                service=service_name,
                command=command,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=124,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ExecResult(
                service=service_name,
                command=command,
                stdout="",
                stderr=str(e),
                exit_code=1,
                duration_ms=(time.monotonic() - start) * 1000,
            )

        duration_ms = (time.monotonic() - start) * 1000

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        truncated = False

        if len(stdout) > max_output_bytes:
            stdout = stdout[:max_output_bytes] + "\n[TRUNCATED]"
            truncated = True

        return ExecResult(
            service=service_name,
            command=command,
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode or 0,
            duration_ms=duration_ms,
            truncated=truncated,
        )

    def _check_command_security(self, command: str) -> str | None:
        """Vérifie si une commande contient des patterns dangereux.

        Red Team n'a JAMAIS accès direct aux conteneurs — ce filtre est
        la dernière ligne de défense avant docker exec.

        Args:
            command: Commande shell à analyser.

        Returns:
            Raison du blocage (str) si la commande est refusée, None si autorisée.
        """
        lower = command.lower()

        # Patterns structurellement dangereux
        for pattern in _BLOCKED_SUBSTRINGS:
            if pattern in lower:
                return f"blocked pattern: {pattern!r}"

        # IPs hors du subnet autorisé
        allowed_net = ipaddress.ip_network(self.config.subnet, strict=False)
        for m in _IP_RE.finditer(command):
            ip_str = m.group(1)
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ip.is_loopback:
                continue
            if ip not in allowed_net:
                return f"external IP outside {self.config.subnet}: {ip_str}"

        return None

    async def read_siem_logs(self, since_line: int = 0, tail_n: int = 200) -> list[str]:
        """Lit les logs du SIEM-lite depuis la dernière position connue.

        Args:
            since_line: Index de ligne depuis lequel lire (pour lecture incrémentale).
                        Si 0 et tail_n > 0, retourne les dernières tail_n lignes.
            tail_n: Nombre max de lignes à retourner quand since_line == 0.
                    Défaut 200. Ignoré si since_line > 0.

        Returns:
            Liste de lignes de log (sans \\n final).
        """
        all_lines: list[str] = []

        # Cherche les logs dans logs_dir/siem/ puis logs_dir/ en fallback
        search_dirs = [self.logs_dir / "siem", self.logs_dir]
        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            log_files = sorted(search_dir.glob("*.log"))
            for log_file in log_files:
                try:
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    all_lines.extend(lines)
                except OSError as e:
                    logger.warning(f"Cannot read SIEM log {log_file}: {e}")
            if log_files:
                break  # on a trouvé des fichiers dans ce répertoire

        if since_line > 0:
            return all_lines[since_line:]

        # since_line == 0 → retourne les dernières tail_n lignes
        if tail_n > 0:
            return all_lines[-tail_n:]
        return all_lines

    async def cleanup_on_error(self, error: Exception | None = None) -> None:
        """Nettoyage d'urgence après une exception non gérée pendant un match.

        Exécute docker compose down -v --remove-orphans pour s'assurer qu'aucun
        conteneur vulnérable ne reste actif, puis supprime les fichiers temporaires.

        Args:
            error: Exception à logger (peut être None).
        """
        if error is not None:
            logger.error(
                f"Cyber Range cleanup_on_error: {type(error).__name__}: {error}",
                exc_info=error,
            )
        else:
            logger.error("Cyber Range cleanup_on_error called (no exception provided)")

        self.status = RangeStatus.ERROR

        try:
            if self.compose_file and self.compose_file.exists():
                cmd = [
                    "docker", "compose",
                    "-f", str(self.compose_file),
                    "-p", self._project_name,
                    "down", "-v", "--remove-orphans",
                ]
                await self._run_docker_cmd(cmd, error_context="cleanup_on_error", check=False)
        except Exception as e:
            logger.error(f"cleanup_on_error: docker compose down failed: {e}")
        finally:
            if self._compose_dir and self._compose_dir.exists():
                shutil.rmtree(self._compose_dir, ignore_errors=True)
            self.compose_file = None
            self.status = RangeStatus.DESTROYED
            logger.info("Cyber Range destroyed (cleanup_on_error)")

    def get_service_info_for_red(self) -> dict:
        """Construit le briefing réseau visible par Red Team.

        Returns:
            Dict avec la surface d'attaque visible (IPs, ports, services actifs).
            Les vulnérabilités exactes ne sont PAS incluses.
        """
        return {
            "network_summary": f"Internal network: {self.config.subnet}",
            "discovered_hosts": [
                {
                    "ip": svc.ip,
                    "port": svc.port,
                    "service_hint": svc.name.replace("vuln-", ""),  # ex: "webapp", "ssh"
                    # NB: pas de svc.vulns — Red doit les découvrir
                }
                for svc in self.config.services
            ],
            "objective": self.config.objective,
        }

    def get_service_info_for_blue(self) -> dict:
        """Construit le briefing infrastructure visible par Blue Team.

        Returns:
            Dict avec le schéma infra à défendre.
            Les vulnérabilités exactes ne sont PAS incluses.
        """
        return {
            "network_summary": f"Defending network: {self.config.subnet}",
            "infrastructure": [
                {
                    "service": svc.name,
                    "ip": svc.ip,
                    "port": svc.port,
                    "role": svc.name.replace("vuln-", ""),
                    # NB: pas de svc.vulns — Blue ne sait pas quelles vulns existent
                }
                for svc in self.config.services
            ],
            "siem_endpoint": "logs available via read_siem_logs()",
            "note": "Monitor SIEM logs to detect intrusion attempts.",
        }

    # ------------------------------------------------------------------
    # Docker Compose generation
    # ------------------------------------------------------------------

    def _generate_compose_yaml(self) -> str:
        """Génère le contenu du docker-compose.yml pour ce scénario.

        Returns:
            Contenu YAML du fichier docker-compose (string).
        """
        # TODO: Utiliser PyYAML ou ruamel.yaml pour la génération propre
        # Pour l'instant, génération manuelle pour éviter une dépendance supplémentaire
        runtime_line = f"    runtime: {GVISOR_RUNTIME}\n" if self.use_gvisor else ""

        header = COMPOSE_FILE_HEADER.format(
            seed=self.config.seed,
            difficulty=self.config.difficulty,
        )

        # Calcule l'IP de base depuis le subnet (ex: 10.42 depuis "10.42.0.0/16")
        subnet_prefix = ".".join(self.config.subnet.split(".")[:2])  # "10.42"

        lines = [header, "version: \"3.9\"\n\n"]

        # Network
        lines.append("networks:\n")
        lines.append(f"  {DOCKER_NETWORK_NAME}:\n")
        lines.append("    internal: true\n")
        lines.append("    driver: bridge\n")
        lines.append("    ipam:\n")
        lines.append("      config:\n")
        lines.append(f"        - subnet: {self.config.subnet}\n\n")

        # Volumes (pour logs SIEM)
        lines.append("volumes:\n")
        lines.append("  siem-logs:\n\n")

        lines.append("services:\n")

        # Services vulnérables
        for svc in self.config.services:
            lines.extend(self._render_service_yaml(svc, runtime_line))
            lines.append("\n")

        # noise-gen
        noise_ip = f"{subnet_prefix}.1.100"
        target_ips = ",".join(svc.ip for svc in self.config.services)
        lines.append(f"  noise-gen:\n")
        lines.append(f"    image: {NOISE_GEN_IMAGE}\n")
        if self.use_gvisor:
            lines.append(f"    runtime: {GVISOR_RUNTIME}\n")
        lines.append(f"    networks:\n")
        lines.append(f"      {DOCKER_NETWORK_NAME}:\n")
        lines.append(f"        ipv4_address: {noise_ip}\n")
        lines.append(f"    environment:\n")
        lines.append(f"      - INTENSITY={self.config.noise_intensity}\n")
        lines.append(f"      - TARGETS={target_ips}\n")
        lines.append(f"    depends_on:\n")
        for svc in self.config.services:
            lines.append(f"      - {svc.name}\n")
        lines.append(f"    cap_drop:\n      - ALL\n\n")

        # siem-lite
        siem_ip = f"{subnet_prefix}.1.200"
        lines.append(f"  siem-lite:\n")
        lines.append(f"    image: {SIEM_LITE_IMAGE}\n")
        if self.use_gvisor:
            lines.append(f"    runtime: {GVISOR_RUNTIME}\n")
        lines.append(f"    networks:\n")
        lines.append(f"      {DOCKER_NETWORK_NAME}:\n")
        lines.append(f"        ipv4_address: {siem_ip}\n")
        lines.append(f"    volumes:\n")
        lines.append(f"      - siem-logs:/var/log/siem:rw\n")
        lines.append(f"      - {self.logs_dir}:/var/log/export:rw\n")
        lines.append(f"    cap_drop:\n      - ALL\n")

        return "".join(lines)

    def _render_service_yaml(
        self, svc: ServiceConfig, runtime_line: str
    ) -> list[str]:
        """Génère le bloc YAML d'un service.

        Args:
            svc: Configuration du service.
            runtime_line: Ligne runtime (gVisor ou vide).

        Returns:
            Liste de lignes YAML pour ce service.
        """
        lines = []
        lines.append(f"  {svc.name}:\n")
        lines.append(f"    image: {svc.image}\n")
        if runtime_line:
            lines.append(runtime_line)
        lines.append(f"    networks:\n")
        lines.append(f"      {DOCKER_NETWORK_NAME}:\n")
        lines.append(f"        ipv4_address: {svc.ip}\n")
        if svc.env_overrides:
            lines.append(f"    environment:\n")
            for k, v in svc.env_overrides.items():
                lines.append(f"      - {k}={v}\n")
        lines.append(f"    cap_drop:\n      - ALL\n")
        lines.append(f"    read_only: true\n")
        lines.append(f"    tmpfs:\n      - /tmp:size=50M\n")
        return lines

    # ------------------------------------------------------------------
    # Docker subprocess helpers
    # ------------------------------------------------------------------

    async def _run_compose_up(self) -> None:
        """Lance docker compose up -d.

        Raises:
            RuntimeError: Si la commande retourne un code non-nul.
        """
        # TODO: Ajouter --wait pour attendre que les health checks Docker passent
        cmd = [
            "docker", "compose",
            "-f", str(self.compose_file),
            "-p", self._project_name,
            "up", "-d",
        ]
        await self._run_docker_cmd(cmd, error_context="compose up")

    async def _run_compose_down(self) -> None:
        """Lance docker compose down -v pour détruire les conteneurs et volumes."""
        if not self.compose_file or not self.compose_file.exists():
            logger.warning("No compose file found during teardown — skipping")
            return
        cmd = [
            "docker", "compose",
            "-f", str(self.compose_file),
            "-p", self._project_name,
            "down", "-v",
        ]
        await self._run_docker_cmd(cmd, error_context="compose down", check=False)

    async def _run_docker_cmd(
        self, cmd: list[str], error_context: str, check: bool = True
    ) -> tuple[str, str, int]:
        """Exécute une commande docker et retourne (stdout, stderr, returncode).

        Args:
            cmd: Commande et arguments.
            error_context: Label pour les messages d'erreur.
            check: Si True, raise RuntimeError si returncode != 0.

        Returns:
            Tuple (stdout, stderr, returncode).

        Raises:
            RuntimeError: Si check=True et returncode != 0.
        """
        logger.debug(f"Running: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        rc = proc.returncode or 0

        if rc != 0:
            logger.error(f"Docker {error_context} failed (rc={rc}): {stderr[:500]}")
            if check:
                raise RuntimeError(
                    f"docker {error_context} failed (rc={rc}): {stderr[:200]}"
                )

        return stdout, stderr, rc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_service(self, name: str) -> ServiceConfig | None:
        """Trouve un ServiceConfig par nom.

        Args:
            name: Nom logique du service.

        Returns:
            ServiceConfig ou None si introuvable.
        """
        return next((s for s in self.config.services if s.name == name), None)
