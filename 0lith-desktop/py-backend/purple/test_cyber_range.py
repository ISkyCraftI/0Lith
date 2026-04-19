"""
Tests for purple/cyber_range.py — security filter + health checks.
Run: python -m pytest py-backend/purple/test_cyber_range.py -v
  or: python py-backend/purple/test_cyber_range.py
"""

from __future__ import annotations

import asyncio
import socket
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from purple.cyber_range import CyberRange, ExecResult, RangeStatus, ServiceHealth
from purple.scenario_generator import ScenarioConfig, ServiceConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svc(name: str, ip: str = "10.42.1.10", port: int = 80) -> ServiceConfig:
    return ServiceConfig(
        name=name,
        image=f"0lith/{name}:latest",
        ip=ip,
        port=port,
        vulns=[],
        credentials=None,
    )


def _make_config(
    services: list[ServiceConfig] | None = None,
    subnet: str = "10.42.0.0/16",
) -> ScenarioConfig:
    svcs = services or [_make_svc("vuln-webapp", port=5000)]
    return ScenarioConfig(
        seed=42,
        difficulty="easy",
        services=svcs,
        objective="Capture the flag",
        objective_techniques=["T1190"],
        max_rounds=5,
        time_budget_minutes=30,
        subnet=subnet,
    )


def _make_range(services: list[ServiceConfig] | None = None, subnet: str = "10.42.0.0/16") -> CyberRange:
    """Crée un CyberRange avec un statut HEALTHY sans déploiement Docker réel."""
    cr = CyberRange(_make_config(services, subnet=subnet), use_gvisor=False)
    cr.status = RangeStatus.HEALTHY
    return cr


# ---------------------------------------------------------------------------
# Security filter tests (_check_command_security)
# ---------------------------------------------------------------------------

class TestCommandSecurityFilter(unittest.TestCase):
    """Vérifie que le filtre de sécurité bloque les commandes dangereuses."""

    def setUp(self) -> None:
        self.cr = _make_range()

    # ── Commandes bloquées ───────────────────────────────────────────────────

    def test_blocks_docker(self) -> None:
        reason = self.cr._check_command_security("docker ps")
        self.assertIsNotNone(reason)
        self.assertIn("docker", reason)

    def test_blocks_docker_case_insensitive(self) -> None:
        reason = self.cr._check_command_security("DOCKER ps")
        self.assertIsNotNone(reason)

    def test_blocks_mount(self) -> None:
        reason = self.cr._check_command_security("mount /dev/sda1 /mnt")
        self.assertIsNotNone(reason)
        self.assertIn("mount", reason)

    def test_blocks_nsenter(self) -> None:
        reason = self.cr._check_command_security("nsenter -t 1 -m -u -i -n")
        self.assertIsNotNone(reason)

    def test_blocks_proc_1(self) -> None:
        reason = self.cr._check_command_security("cat /proc/1/environ")
        self.assertIsNotNone(reason)
        self.assertIn("/proc/1", reason)

    def test_blocks_proc_self(self) -> None:
        reason = self.cr._check_command_security("ls /proc/self/fd")
        self.assertIsNotNone(reason)
        self.assertIn("/proc/self", reason)

    def test_blocks_external_ip_google_dns(self) -> None:
        reason = self.cr._check_command_security("curl http://8.8.8.8/")
        self.assertIsNotNone(reason)
        self.assertIn("8.8.8.8", reason)

    def test_blocks_external_ip_arbitrary(self) -> None:
        reason = self.cr._check_command_security("wget 192.168.1.1")
        self.assertIsNotNone(reason)
        self.assertIn("192.168.1.1", reason)

    def test_blocks_external_ip_in_nmap(self) -> None:
        reason = self.cr._check_command_security("nmap -sV 1.2.3.4")
        self.assertIsNotNone(reason)

    # ── Commandes autorisées ─────────────────────────────────────────────────

    def test_allows_ls(self) -> None:
        self.assertIsNone(self.cr._check_command_security("ls /var/www/html"))

    def test_allows_cat_flag(self) -> None:
        self.assertIsNone(self.cr._check_command_security("cat /flag.txt"))

    def test_allows_id(self) -> None:
        self.assertIsNone(self.cr._check_command_security("id"))

    def test_allows_internal_ip(self) -> None:
        # 10.42.1.5 est dans 10.42.0.0/16 → autorisé
        self.assertIsNone(self.cr._check_command_security("curl http://10.42.1.5:5000/"))

    def test_allows_loopback(self) -> None:
        self.assertIsNone(self.cr._check_command_security("curl http://127.0.0.1:8080/"))

    def test_allows_whoami(self) -> None:
        self.assertIsNone(self.cr._check_command_security("whoami"))

    def test_allows_python_script(self) -> None:
        self.assertIsNone(
            self.cr._check_command_security("python3 /tmp/exploit.py --target 10.42.1.10")
        )

    def test_allows_nmap_internal(self) -> None:
        self.assertIsNone(
            self.cr._check_command_security("nmap -sV 10.42.1.0/24")
        )

    def test_allows_proc_other(self) -> None:
        # /proc/cpuinfo n'est pas /proc/1 ni /proc/self
        self.assertIsNone(self.cr._check_command_security("cat /proc/cpuinfo"))

    def test_custom_subnet_blocks_outside(self) -> None:
        # Range configuré en 172.16.0.0/12 — 10.42.1.5 doit être bloqué
        cr = _make_range(subnet="172.16.0.0/12")
        self.assertIsNotNone(cr._check_command_security("curl 10.42.1.5"))

    def test_custom_subnet_allows_inside(self) -> None:
        cr = _make_range(subnet="172.16.0.0/12")
        self.assertIsNone(cr._check_command_security("curl 172.20.1.1"))


# ---------------------------------------------------------------------------
# exec_command integration (security filter path, no real Docker)
# ---------------------------------------------------------------------------

class TestExecCommandSecurityPath(unittest.IsolatedAsyncioTestCase):
    """Vérifie que exec_command retourne exit_code=126 pour les commandes bloquées."""

    def setUp(self) -> None:
        self.cr = _make_range()

    async def test_blocked_command_returns_126(self) -> None:
        result = await self.cr.exec_command("vuln-webapp", "docker ps")
        self.assertIsInstance(result, ExecResult)
        self.assertEqual(result.exit_code, 126)
        self.assertIn("[SECURITY]", result.stderr)
        self.assertEqual(result.stdout, "")

    async def test_blocked_nsenter_returns_126(self) -> None:
        result = await self.cr.exec_command("vuln-webapp", "nsenter -t 1 -m")
        self.assertEqual(result.exit_code, 126)

    async def test_blocked_external_ip_returns_126(self) -> None:
        result = await self.cr.exec_command("vuln-webapp", "wget 8.8.8.8")
        self.assertEqual(result.exit_code, 126)
        self.assertIn("8.8.8.8", result.stderr)

    async def test_raises_on_unknown_service(self) -> None:
        with self.assertRaises(ValueError):
            await self.cr.exec_command("ghost-service", "ls")

    async def test_raises_when_not_healthy(self) -> None:
        self.cr.status = RangeStatus.IDLE
        with self.assertRaises(RuntimeError):
            await self.cr.exec_command("vuln-webapp", "ls")


# ---------------------------------------------------------------------------
# Health check tests (mock socket / asyncio.open_connection)
# ---------------------------------------------------------------------------

class TestCheckHealth(unittest.IsolatedAsyncioTestCase):
    """Tests des health checks avec connexions réseau mockées."""

    def _make_ssh_range(self) -> CyberRange:
        svcs = [_make_svc("vuln-ssh", ip="10.42.1.2", port=22)]
        return _make_range(services=svcs)

    def _make_webapp_range(self) -> CyberRange:
        svcs = [_make_svc("vuln-webapp", ip="10.42.1.3", port=5000)]
        return _make_range(services=svcs)

    def _make_siem_range(self) -> CyberRange:
        svcs = [_make_svc("siem-lite", ip="10.42.1.200", port=5514)]
        return _make_range(services=svcs)

    # ── SSH TCP check ─────────────────────────────────────────────────────────

    async def test_ssh_healthy_on_tcp_success(self) -> None:
        cr = self._make_ssh_range()

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_reader = MagicMock()

        with patch("asyncio.open_connection", AsyncMock(return_value=(mock_reader, mock_writer))):
            healths = await cr.check_health()

        self.assertTrue(healths["vuln-ssh"].healthy)
        self.assertIsNone(healths["vuln-ssh"].error)

    async def test_ssh_unhealthy_on_connection_refused(self) -> None:
        cr = self._make_ssh_range()
        # max_retries=1 pour que le test ne dure pas 10s (backoff=2s × 5)
        svc = cr.config.services[0]

        with patch("asyncio.open_connection", AsyncMock(side_effect=ConnectionRefusedError())):
            health = await cr._check_service_health(svc, max_retries=1, backoff=0.0)

        self.assertFalse(health.healthy)
        self.assertIsNotNone(health.error)

    async def test_ssh_retries_then_succeeds(self) -> None:
        """Échoue 2 fois puis réussit à la 3e tentative."""
        cr = self._make_ssh_range()
        svc = cr.config.services[0]

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_reader = MagicMock()

        call_count = 0

        async def open_conn_flaky(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionRefusedError("not ready yet")
            return mock_reader, mock_writer

        with patch("asyncio.open_connection", side_effect=open_conn_flaky):
            health = await cr._check_service_health(svc, max_retries=5, backoff=0.0)

        self.assertTrue(health.healthy)
        self.assertEqual(call_count, 3)

    async def test_ssh_all_retries_exhausted(self) -> None:
        cr = self._make_ssh_range()
        svc = cr.config.services[0]

        with patch("asyncio.open_connection", AsyncMock(side_effect=ConnectionRefusedError())):
            health = await cr._check_service_health(svc, max_retries=3, backoff=0.0)

        self.assertFalse(health.healthy)
        self.assertIn("ConnectionRefusedError", health.error or "")

    # ── HTTP check (vuln-webapp) ──────────────────────────────────────────────

    async def test_webapp_healthy_on_http_200(self) -> None:
        cr = self._make_webapp_range()
        svc = cr.config.services[0]

        with patch.object(CyberRange, "_http_check", return_value=None) as mock_http:
            health = await cr._check_service_health(svc, max_retries=1, backoff=0.0)

        self.assertTrue(health.healthy)
        mock_http.assert_called_once_with(svc.ip, svc.port, 3.0)

    async def test_webapp_unhealthy_on_http_error(self) -> None:
        import urllib.error
        cr = self._make_webapp_range()
        svc = cr.config.services[0]

        with patch.object(
            CyberRange,
            "_http_check",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            health = await cr._check_service_health(svc, max_retries=1, backoff=0.0)

        self.assertFalse(health.healthy)

    # ── UDP check (siem-lite) ─────────────────────────────────────────────────

    async def test_siem_healthy_on_udp_no_error(self) -> None:
        cr = self._make_siem_range()
        svc = cr.config.services[0]

        with patch.object(CyberRange, "_udp_check", return_value=None) as mock_udp:
            health = await cr._check_service_health(svc, max_retries=1, backoff=0.0)

        self.assertTrue(health.healthy)
        mock_udp.assert_called_once_with(svc.ip, 5514, 3.0)

    async def test_siem_unhealthy_on_connection_refused(self) -> None:
        cr = self._make_siem_range()
        svc = cr.config.services[0]

        with patch.object(
            CyberRange,
            "_udp_check",
            side_effect=ConnectionRefusedError("ICMP unreachable"),
        ):
            health = await cr._check_service_health(svc, max_retries=1, backoff=0.0)

        self.assertFalse(health.healthy)

    # ── check_health (multi-service) ─────────────────────────────────────────

    async def test_check_health_all_healthy(self) -> None:
        svcs = [
            _make_svc("vuln-webapp", ip="10.42.1.3", port=5000),
            _make_svc("vuln-ssh", ip="10.42.1.2", port=22),
        ]
        cr = _make_range(services=svcs)

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_reader = MagicMock()

        with (
            patch.object(CyberRange, "_http_check", return_value=None),
            patch("asyncio.open_connection", AsyncMock(return_value=(mock_reader, mock_writer))),
        ):
            healths = await cr.check_health()

        self.assertEqual(len(healths), 2)
        self.assertTrue(all(h.healthy for h in healths.values()))

    async def test_check_health_partial_failure(self) -> None:
        svcs = [
            _make_svc("vuln-webapp", ip="10.42.1.3", port=5000),
            _make_svc("vuln-ssh", ip="10.42.1.2", port=22),
        ]
        cr = _make_range(services=svcs)

        with (
            patch.object(CyberRange, "_http_check", return_value=None),
            patch(
                "asyncio.open_connection",
                AsyncMock(side_effect=ConnectionRefusedError()),
            ),
        ):
            healths = await cr.check_health()

        self.assertTrue(healths["vuln-webapp"].healthy)
        self.assertFalse(healths["vuln-ssh"].healthy)


# ---------------------------------------------------------------------------
# read_siem_logs tests
# ---------------------------------------------------------------------------

class TestReadSiemLogs(unittest.IsolatedAsyncioTestCase):

    async def test_returns_empty_when_no_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cr = CyberRange(_make_config(), logs_dir=Path(tmpdir), use_gvisor=False)
            lines = await cr.read_siem_logs()
        self.assertEqual(lines, [])

    async def test_reads_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "siem"
            log_dir.mkdir()
            (log_dir / "events.log").write_text("line1\nline2\nline3\n")
            cr = CyberRange(_make_config(), logs_dir=Path(tmpdir), use_gvisor=False)
            lines = await cr.read_siem_logs(tail_n=0)
        self.assertEqual(lines, ["line1", "line2", "line3"])

    async def test_tail_n_limits_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "siem"
            log_dir.mkdir()
            content = "\n".join(f"line{i}" for i in range(300))
            (log_dir / "events.log").write_text(content)
            cr = CyberRange(_make_config(), logs_dir=Path(tmpdir), use_gvisor=False)
            lines = await cr.read_siem_logs(tail_n=50)
        self.assertEqual(len(lines), 50)
        self.assertEqual(lines[-1], "line299")

    async def test_since_line_incremental(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "siem"
            log_dir.mkdir()
            (log_dir / "events.log").write_text("a\nb\nc\nd\ne\n")
            cr = CyberRange(_make_config(), logs_dir=Path(tmpdir), use_gvisor=False)
            lines = await cr.read_siem_logs(since_line=3)
        self.assertEqual(lines, ["d", "e"])

    async def test_fallback_to_logs_dir_root(self) -> None:
        """Sans sous-dossier 'siem/', tombe sur logs_dir/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "output.log").write_text("alpha\nbeta\n")
            cr = CyberRange(_make_config(), logs_dir=Path(tmpdir), use_gvisor=False)
            lines = await cr.read_siem_logs(tail_n=0)
        self.assertEqual(lines, ["alpha", "beta"])


# ---------------------------------------------------------------------------
# cleanup_on_error tests
# ---------------------------------------------------------------------------

class TestCleanupOnError(unittest.IsolatedAsyncioTestCase):

    async def test_cleanup_sets_status_destroyed(self) -> None:
        cr = _make_range()
        with patch.object(cr, "_run_docker_cmd", new=AsyncMock()):
            await cr.cleanup_on_error()
        self.assertEqual(cr.status, RangeStatus.DESTROYED)

    async def test_cleanup_calls_compose_down_remove_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cr = _make_range()
            cr._compose_dir = Path(tmpdir)
            compose_path = Path(tmpdir) / "docker-compose.yml"
            compose_path.write_text("# dummy")
            cr.compose_file = compose_path

            mock_run = AsyncMock()
            with patch.object(cr, "_run_docker_cmd", new=mock_run):
                await cr.cleanup_on_error()

        cmd_called = mock_run.call_args[0][0]
        self.assertIn("--remove-orphans", cmd_called)
        self.assertIn("down", cmd_called)

    async def test_cleanup_removes_compose_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inner_dir = Path(tmpdir) / "range-tmp"
            inner_dir.mkdir()
            cr = _make_range()
            cr._compose_dir = inner_dir
            compose_path = inner_dir / "docker-compose.yml"
            compose_path.write_text("# dummy")
            cr.compose_file = compose_path

            with patch.object(cr, "_run_docker_cmd", new=AsyncMock()):
                await cr.cleanup_on_error()

        self.assertFalse(inner_dir.exists())

    async def test_cleanup_with_no_compose_file(self) -> None:
        """Doit fonctionner même si compose_file n'existe pas encore."""
        cr = _make_range()
        cr.compose_file = None
        # Ne doit pas lever d'exception
        with patch.object(cr, "_run_docker_cmd", new=AsyncMock()) as mock_run:
            await cr.cleanup_on_error()
        mock_run.assert_not_called()
        self.assertEqual(cr.status, RangeStatus.DESTROYED)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
