"""
0Lith — Vault Watcher
=====================
Surveille le vault Obsidian en temps réel via watchdog.
Déclenche ActionEngine après 120s d'inactivité sur un fichier contenant des tags IA.

Mécanisme :
  - Chaque fichier modifié obtient un threading.Timer de 120s.
  - Toute nouvelle modification sur ce fichier réinitialise le timer.
  - Quand le timer expire → ActionEngine.process_file().
  - Les fichiers en cours de traitement sont ignorés (évite les boucles).
  - Cooldown de 30s après traitement (évite re-trigger immédiat).
"""

import sys
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from watchdog.observers import Observer

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    VAULT_PATH,
    VAULT_EXTENSIONS,
    VAULT_IGNORE_DIRS,
    OLITH_DIR,
    WATCHER_INACTIVITY_SECONDS,
    WATCHER_COOLDOWN_SECONDS,
)

from api.action_engine import ActionEngine, ActionResult


class VaultWatcher:
    """
    Surveille le vault Obsidian et déclenche les actions IA après inactivité.

    Thread-safe. Conçu pour tourner en arrière-plan du serveur FastAPI.
    """

    def __init__(
        self,
        action_engine: ActionEngine | None = None,
        inactivity_seconds: int = WATCHER_INACTIVITY_SECONDS,
        cooldown_seconds: int = WATCHER_COOLDOWN_SECONDS,
    ) -> None:
        self._engine = action_engine or ActionEngine()
        self._inactivity = inactivity_seconds
        self._cooldown = cooldown_seconds

        # path (str) → threading.Timer actif
        self._timers: dict[str, threading.Timer] = {}
        self._timers_lock = threading.Lock()

        # Fichiers en cours de traitement par l'IA (on ignore leurs events)
        self._processing: set[str] = set()
        self._processing_lock = threading.Lock()

        # Fichiers en cooldown après traitement {path: expire_timestamp}
        self._cooldowns: dict[str, float] = {}
        self._cooldowns_lock = threading.Lock()

        # Historique des dernières actions (pour /watcher/status)
        self._history: list[dict] = []
        self._history_lock = threading.Lock()
        self._history_max = 50

        self._observer: Observer | None = None
        self._running = False

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Démarre le watcher watchdog en arrière-plan."""
        if self._running:
            return

        self._engine.ensure_config_exists()
        self._observer = Observer()
        handler = _VaultEventHandler(self)
        self._observer.schedule(handler, str(VAULT_PATH), recursive=True)
        self._observer.start()
        self._running = True
        print(
            f"[VaultWatcher] Démarré — vault: {VAULT_PATH} "
            f"— inactivité: {self._inactivity}s — cooldown: {self._cooldown}s"
        )

    def stop(self) -> None:
        """Arrête le watcher et annule tous les timers en cours."""
        self._running = False
        with self._timers_lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        print("[VaultWatcher] Arrêté.")

    # ── Statut ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Retourne l'état courant du watcher (pour l'endpoint /watcher/status)."""
        with self._timers_lock:
            pending = list(self._timers.keys())
        with self._processing_lock:
            processing = list(self._processing)
        with self._history_lock:
            history = list(self._history[-10:])  # 10 dernières actions

        return {
            "running": self._running,
            "vault": str(VAULT_PATH),
            "inactivity_seconds": self._inactivity,
            "pending_files": pending,
            "processing_files": processing,
            "recent_actions": history,
        }

    # ── Gestion des events ────────────────────────────────────────────────────

    def on_file_changed(self, path: str) -> None:
        """
        Appelé par le handler watchdog pour chaque fichier modifié.
        Réinitialise le timer d'inactivité pour ce fichier.
        """
        if not self._should_watch(path):
            return

        # Ignorer si en cours de traitement
        with self._processing_lock:
            if path in self._processing:
                return

        # Si en cooldown : programmer un rattrapage après expiration plutôt que d'ignorer
        with self._cooldowns_lock:
            expire = self._cooldowns.get(path, 0)
            remaining = expire - time.time()
            if remaining > 0:
                with self._timers_lock:
                    if path not in self._timers:
                        timer = threading.Timer(
                            remaining + 0.5,
                            self._trigger,
                            args=(path,),
                        )
                        timer.daemon = True
                        timer.start()
                        self._timers[path] = timer
                return

        with self._timers_lock:
            # Annuler l'ancien timer
            if path in self._timers:
                self._timers[path].cancel()

            # Démarrer un nouveau timer
            timer = threading.Timer(
                self._inactivity,
                self._trigger,
                args=(path,),
            )
            timer.daemon = True
            timer.start()
            self._timers[path] = timer

    # ── Déclenchement ─────────────────────────────────────────────────────────

    def _trigger(self, path: str) -> None:
        """Appelé après {inactivity_seconds} d'inactivité sur un fichier."""
        with self._timers_lock:
            self._timers.pop(path, None)

        file_path = Path(path)
        if not file_path.exists():
            return

        # Marquer comme en cours de traitement
        with self._processing_lock:
            self._processing.add(path)

        try:
            print(f"[VaultWatcher] Traitement : {file_path.name}")
            results = self._engine.process_file(file_path)

            if results:
                for r in results:
                    self._record_history(r)
                    if r.success:
                        print(
                            f"[VaultWatcher] #{r.tag} OK → {file_path.name} "
                            f"({r.output_mode})"
                        )
                    else:
                        print(
                            f"[VaultWatcher] #{r.tag} ERREUR → {file_path.name} : "
                            f"{r.error}"
                        )
        finally:
            with self._processing_lock:
                self._processing.discard(path)

            # Appliquer le cooldown
            with self._cooldowns_lock:
                self._cooldowns[path] = time.time() + self._cooldown

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _should_watch(self, path: str) -> bool:
        """Filtre les fichiers qui doivent être surveillés."""
        p = Path(path)

        # Extension reconnue
        if p.suffix not in VAULT_EXTENSIONS:
            return False

        # Pas dans les dossiers ignorés
        parts = set(p.parts)
        if parts & VAULT_IGNORE_DIRS:
            return False

        # Pas dans .olith/ (évite les boucles sur les logs et backups)
        try:
            p.relative_to(OLITH_DIR)
            return False
        except ValueError:
            pass

        return True

    def _record_history(self, result: ActionResult) -> None:
        """Enregistre une action dans l'historique interne."""
        from datetime import datetime
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tag": result.tag,
            "file": result.file_path,
            "mode": result.output_mode,
            "success": result.success,
            "preview": result.result_preview[:80] if result.success else result.error[:80],
        }
        with self._history_lock:
            self._history.append(entry)
            if len(self._history) > self._history_max:
                self._history.pop(0)


# ── Handler watchdog ──────────────────────────────────────────────────────────

class _VaultEventHandler(FileSystemEventHandler):
    """Handler watchdog délégant au VaultWatcher."""

    def __init__(self, watcher: VaultWatcher) -> None:
        super().__init__()
        self._watcher = watcher

    def on_modified(self, event: FileModifiedEvent) -> None:
        if not event.is_directory:
            self._watcher.on_file_changed(event.src_path)

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self._watcher.on_file_changed(event.src_path)
