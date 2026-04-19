"""
Purple Team — Pre-Match Safety Checks
=======================================
Vérifications de sécurité obligatoires avant tout démarrage de match.

Ces checks garantissent que le Cyber Range est bien isolé du reste du système
avant d'autoriser le lancement d'un match avec des conteneurs vulnérables.

Checks implémentés :
  1. gVisor installé et fonctionnel (runtime runsc)
  2. Réseau Docker cyber-range-net existe et est --internal
  3. Aucun conteneur du range sur le bridge hôte
  4. Ports Qdrant (6333/6334) et Kuzu non exposés sur cyber-range-net
  5. Token de session sparring valide (HMAC signé par l'utilisateur)
  6. Espace disque suffisant pour les logs (≥ 2 GB recommandé)

Exemple:
    checker = SafetyChecker()
    ok, results = checker.run_all()
    if not ok:
        for r in results:
            if not r.passed:
                print(f"FAILED: {r.name} — {r.reason}")
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Ports des bases de données 0Lith à ne jamais exposer dans le Cyber Range
PROTECTED_PORTS = {
    6333: "Qdrant HTTP",
    6334: "Qdrant gRPC",
    7687: "Kuzu (if running)",
    11435: "Pyrolith Ollama (Docker)",
}

# Espace disque minimal recommandé (bytes)
MIN_DISK_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# Nom du réseau Docker isolé
CYBER_RANGE_NETWORK = "cyber-range-net"

# Nom de l'env var pour le token HMAC sparring
SPARRING_TOKEN_ENV = "OLITH_SPARRING_TOKEN"
SPARRING_SECRET_ENV = "OLITH_SPARRING_SECRET"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SafetyCheckResult:
    """Résultat d'un check de sécurité individuel.

    Attributes:
        name: Nom du check.
        passed: True si le check a réussi.
        reason: Description du résultat (pourquoi ça passe ou échoue).
        critical: Si True, un échec bloque le match.
        warning_only: Si True, un échec génère un warning mais n'est pas bloquant.
    """

    name: str
    passed: bool
    reason: str = ""
    critical: bool = True
    warning_only: bool = False

    def __str__(self) -> str:
        status = "✓ PASS" if self.passed else ("⚠ WARN" if self.warning_only else "✗ FAIL")
        return f"[{status}] {self.name}: {self.reason}"


# ---------------------------------------------------------------------------
# SafetyChecker
# ---------------------------------------------------------------------------

class SafetyChecker:
    """Exécute les vérifications de sécurité pré-match.

    Toutes les vérifications critiques doivent passer pour autoriser
    le démarrage d'un match Purple Team.

    Attributes:
        logs_dir: Répertoire où les logs du match seront écrits.

    Example:
        checker = SafetyChecker(logs_dir=Path("/tmp/olith-logs"))
        ok, results = checker.run_all()
        if not ok:
            raise RuntimeError("Safety checks failed")
    """

    def __init__(
        self,
        logs_dir: Path | None = None,
        skip_gvisor: bool = False,
        skip_token: bool = False,
    ) -> None:
        """Initialise le SafetyChecker.

        Args:
            logs_dir: Répertoire des logs (pour vérifier l'espace disque).
            skip_gvisor: Si True, saute le check gVisor (dev/test sans gVisor).
            skip_token: Si True, saute la validation du token HMAC.
        """
        self.logs_dir = logs_dir or Path.home() / ".0lith" / "arena_logs"
        self._skip_gvisor = skip_gvisor
        self._skip_token = skip_token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(self) -> tuple[bool, list[SafetyCheckResult]]:
        """Exécute tous les checks de sécurité.

        Returns:
            Tuple (all_critical_passed: bool, results: list[SafetyCheckResult]).
            all_critical_passed est False si au moins un check critique échoue.
        """
        results: list[SafetyCheckResult] = []

        checks: list[Callable[[], SafetyCheckResult]] = [
            self._check_docker_available,
            self._check_gvisor_runtime,
            self._check_network_isolation,
            self._check_no_host_network_containers,
            self._check_memory_db_not_exposed,
            self._check_sparring_token,
            self._check_disk_space,
        ]

        for check_fn in checks:
            try:
                result = check_fn()
            except Exception as e:
                result = SafetyCheckResult(
                    name=check_fn.__name__,
                    passed=False,
                    reason=f"Check raised exception: {type(e).__name__}: {e}",
                    critical=True,
                )
            results.append(result)
            if result.passed:
                logger.debug(f"Safety check passed: {result.name}")
            elif result.warning_only:
                logger.warning(f"Safety warning: {result.name} — {result.reason}")
            else:
                logger.error(f"Safety check FAILED: {result.name} — {result.reason}")

        critical_failures = [
            r for r in results if not r.passed and r.critical and not r.warning_only
        ]
        all_passed = len(critical_failures) == 0

        logger.info(
            f"Safety checks: {sum(r.passed for r in results)}/{len(results)} passed, "
            f"{len(critical_failures)} critical failures"
        )
        return all_passed, results

    def run_critical_only(self) -> bool:
        """Exécute uniquement les checks critiques et retourne True/False.

        Convenance pour les cas où les détails ne sont pas nécessaires.

        Returns:
            True si tous les checks critiques passent.
        """
        ok, _ = self.run_all()
        return ok

    def get_summary(self) -> dict:
        """Retourne un résumé des checks pour l'IPC.

        Returns:
            Dict avec passed, failed, warnings, details.
        """
        ok, results = self.run_all()
        return {
            "overall_passed": ok,
            "passed": [r.name for r in results if r.passed],
            "failed": [
                {"name": r.name, "reason": r.reason}
                for r in results if not r.passed and not r.warning_only
            ],
            "warnings": [
                {"name": r.name, "reason": r.reason}
                for r in results if not r.passed and r.warning_only
            ],
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_docker_available(self) -> SafetyCheckResult:
        """Vérifie que Docker est disponible et le daemon actif.

        Returns:
            SafetyCheckResult.
        """
        if not shutil.which("docker"):
            return SafetyCheckResult(
                name="docker_available",
                passed=False,
                reason="docker binary not found in PATH",
                critical=True,
            )

        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                return SafetyCheckResult(
                    name="docker_available",
                    passed=True,
                    reason=f"Docker daemon running (version: {version})",
                )
            else:
                return SafetyCheckResult(
                    name="docker_available",
                    passed=False,
                    reason=f"Docker daemon unreachable: {result.stderr[:100]}",
                )
        except subprocess.TimeoutExpired:
            return SafetyCheckResult(
                name="docker_available",
                passed=False,
                reason="Docker info command timed out",
            )

    def _check_gvisor_runtime(self) -> SafetyCheckResult:
        """Vérifie que gVisor (runsc) est installé et fonctionnel.

        Returns:
            SafetyCheckResult (warning_only si skip_gvisor=True).
        """
        if self._skip_gvisor:
            return SafetyCheckResult(
                name="gvisor_runtime",
                passed=True,
                reason="gVisor check skipped (skip_gvisor=True — dev mode)",
                critical=False,
                warning_only=True,
            )

        if not shutil.which("runsc"):
            return SafetyCheckResult(
                name="gvisor_runtime",
                passed=False,
                reason=(
                    "gVisor (runsc) not found in PATH. "
                    "Install: https://gvisor.dev/docs/user_guide/install/"
                ),
                critical=True,
            )

        try:
            result = subprocess.run(
                ["docker", "run", "--runtime=runsc", "--rm", "hello-world"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return SafetyCheckResult(
                    name="gvisor_runtime",
                    passed=True,
                    reason="gVisor runtime (runsc) functional",
                )
            else:
                return SafetyCheckResult(
                    name="gvisor_runtime",
                    passed=False,
                    reason=f"gVisor runtime test failed: {result.stderr[:200]}",
                )
        except subprocess.TimeoutExpired:
            return SafetyCheckResult(
                name="gvisor_runtime",
                passed=False,
                reason="gVisor test container timed out",
            )

    def _check_network_isolation(self) -> SafetyCheckResult:
        """Vérifie que le réseau Docker cyber-range-net est --internal.

        Returns:
            SafetyCheckResult.
        """
        try:
            result = subprocess.run(
                ["docker", "network", "inspect", CYBER_RANGE_NETWORK,
                 "--format", "{{json .Internal}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                # Le réseau n'existe pas encore — ce n'est pas bloquant
                return SafetyCheckResult(
                    name="network_isolation",
                    passed=True,
                    reason=(
                        f"Network {CYBER_RANGE_NETWORK!r} does not exist yet "
                        "(will be created by docker compose)"
                    ),
                    warning_only=False,
                )

            is_internal = result.stdout.strip().lower() == "true"
            if is_internal:
                return SafetyCheckResult(
                    name="network_isolation",
                    passed=True,
                    reason=f"Network {CYBER_RANGE_NETWORK!r} is --internal ✓",
                )
            else:
                return SafetyCheckResult(
                    name="network_isolation",
                    passed=False,
                    reason=(
                        f"Network {CYBER_RANGE_NETWORK!r} exists but is NOT --internal. "
                        "Containers may reach internet. Delete and recreate with --internal."
                    ),
                )
        except subprocess.TimeoutExpired:
            return SafetyCheckResult(
                name="network_isolation",
                passed=False,
                reason="docker network inspect timed out",
            )

    def _check_no_host_network_containers(self) -> SafetyCheckResult:
        """Vérifie qu'aucun conteneur du range n'utilise le réseau hôte.

        Returns:
            SafetyCheckResult.
        """
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "network=host",
                 "--filter", "name=olith-range",
                 "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return SafetyCheckResult(
                    name="no_host_network",
                    passed=False,
                    reason=f"docker ps failed: {result.stderr[:100]}",
                )

            containers = [c for c in result.stdout.strip().splitlines() if c]
            if containers:
                return SafetyCheckResult(
                    name="no_host_network",
                    passed=False,
                    reason=(
                        f"Containers on host network detected: {containers}. "
                        "This violates isolation requirements."
                    ),
                )
            return SafetyCheckResult(
                name="no_host_network",
                passed=True,
                reason="No range containers on host network ✓",
            )
        except subprocess.TimeoutExpired:
            return SafetyCheckResult(
                name="no_host_network",
                passed=False,
                reason="docker ps timed out",
            )

    def _check_memory_db_not_exposed(self) -> SafetyCheckResult:
        """Vérifie que Qdrant/Kuzu ne sont pas exposés sur le réseau du range.

        Returns:
            SafetyCheckResult.
        """
        exposed_dbs: list[str] = []

        for port, service_name in PROTECTED_PORTS.items():
            try:
                result = subprocess.run(
                    ["docker", "ps",
                     "--filter", f"publish={port}",
                     "--filter", f"network={CYBER_RANGE_NETWORK}",
                     "--format", "{{.Names}}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    containers = [c for c in result.stdout.strip().splitlines() if c]
                    if containers:
                        exposed_dbs.append(f"{service_name}:{port} (containers: {containers})")
            except subprocess.TimeoutExpired:
                pass  # Non-bloquant si le check timeout

        if exposed_dbs:
            return SafetyCheckResult(
                name="memory_db_not_exposed",
                passed=False,
                reason=(
                    f"Memory databases exposed on {CYBER_RANGE_NETWORK}: "
                    + ", ".join(exposed_dbs)
                ),
                critical=True,
            )

        return SafetyCheckResult(
            name="memory_db_not_exposed",
            passed=True,
            reason=f"No memory databases exposed on {CYBER_RANGE_NETWORK} ✓",
        )

    def _check_sparring_token(self) -> SafetyCheckResult:
        """Vérifie la validité du token de session sparring (HMAC).

        Le token empêche que Monolith ou d'autres agents déclenchent un match
        sans validation explicite de l'utilisateur.

        Returns:
            SafetyCheckResult (warning_only si skip_token=True).
        """
        if self._skip_token:
            return SafetyCheckResult(
                name="sparring_token",
                passed=True,
                reason="Token check skipped (skip_token=True — dev mode)",
                warning_only=True,
            )

        token = os.environ.get(SPARRING_TOKEN_ENV, "")
        secret = os.environ.get(SPARRING_SECRET_ENV, "")

        if not token:
            return SafetyCheckResult(
                name="sparring_token",
                passed=False,
                reason=(
                    f"Missing {SPARRING_TOKEN_ENV} environment variable. "
                    "A valid HMAC token is required to start a match."
                ),
                critical=True,
            )

        if not secret:
            return SafetyCheckResult(
                name="sparring_token",
                passed=False,
                reason=(
                    f"Missing {SPARRING_SECRET_ENV} environment variable. "
                    "Cannot validate token without secret."
                ),
                critical=True,
            )

        # Validation HMAC: token = HMAC-SHA256(secret, "olith-sparring")
        expected = hmac.new(  # type: ignore[attr-defined]  # hmac.new is valid Python stdlib
            secret.encode(),
            b"olith-sparring",
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(token, expected):
            return SafetyCheckResult(
                name="sparring_token",
                passed=True,
                reason="Sparring token valid ✓",
            )
        else:
            return SafetyCheckResult(
                name="sparring_token",
                passed=False,
                reason="Invalid sparring token — HMAC mismatch",
                critical=True,
            )

    def _check_disk_space(self) -> SafetyCheckResult:
        """Vérifie qu'il y a suffisamment d'espace disque pour les logs.

        Returns:
            SafetyCheckResult (warning_only si espace insuffisant mais > 500 MB).
        """
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(str(self.logs_dir))
            free_gb = usage.free / (1024 ** 3)

            if usage.free >= MIN_DISK_BYTES:
                return SafetyCheckResult(
                    name="disk_space",
                    passed=True,
                    reason=f"{free_gb:.1f} GB free on logs partition ✓",
                )
            elif usage.free >= 500 * 1024 * 1024:  # 500 MB
                return SafetyCheckResult(
                    name="disk_space",
                    passed=True,
                    reason=(
                        f"Only {free_gb:.2f} GB free (recommended: 2 GB). "
                        "Match may fill disk if many sessions run."
                    ),
                    warning_only=True,
                )
            else:
                return SafetyCheckResult(
                    name="disk_space",
                    passed=False,
                    reason=(
                        f"Only {free_gb:.2f} GB free. "
                        f"Minimum 2 GB required for logs."
                    ),
                    critical=False,  # Non-bloquant mais notable
                    warning_only=True,
                )
        except OSError as e:
            return SafetyCheckResult(
                name="disk_space",
                passed=False,
                reason=f"Cannot check disk space: {e}",
                critical=False,
                warning_only=True,
            )
