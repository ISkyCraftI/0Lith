#!/usr/bin/env python3
"""
0Lith V1 — Chat History Persistence
=====================================
Stocke les conversations en fichiers JSON dans ~/.0lith/chats/.
Un fichier par session, nommé par date : 2026-02-21_14-30.json
"""

import json
import time
from pathlib import Path
from datetime import datetime

from olith_shared import log_warn, log_info

CHATS_DIR = Path.home() / ".0lith" / "chats"


class ChatHistory:
    def __init__(self, chats_dir: Path = CHATS_DIR):
        self.chats_dir = chats_dir
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self._current_session: str | None = None

    def _session_path(self, session_id: str) -> Path:
        return self.chats_dir / f"{session_id}.json"

    def _ensure_session(self) -> str:
        """Retourne la session courante, en crée une si nécessaire."""
        if not self._current_session:
            self._current_session = datetime.now().strftime("%Y-%m-%d_%H-%M")
        return self._current_session

    def new_session(self) -> str:
        """Force la création d'une nouvelle session."""
        self._current_session = datetime.now().strftime("%Y-%m-%d_%H-%M")
        return self._current_session

    def save_message(self, session_id: str | None, message: dict) -> str:
        """Ajoute un message à une session. Retourne le session_id utilisé."""
        sid = session_id or self._ensure_session()
        path = self._session_path(sid)

        data = {"session_id": sid, "messages": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log_warn("history", f"Failed to read {path.name}: {e}")

        msg = {**message, "timestamp": message.get("timestamp", int(time.time() * 1000))}
        data["messages"].append(msg)
        data["updated_at"] = int(time.time() * 1000)

        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            log_warn("history", f"Failed to write {path.name}: {e}")

        return sid

    def load_session(self, session_id: str) -> list[dict]:
        """Charge tous les messages d'une session."""
        path = self._session_path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("messages", [])
        except (json.JSONDecodeError, OSError) as e:
            log_warn("history", f"Failed to load {path.name}: {e}")
            return []

    def list_sessions(self) -> list[dict]:
        """Liste toutes les sessions, triées par date décroissante."""
        sessions = []
        for f in sorted(self.chats_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                msgs = data.get("messages", [])
                first_user = next((m for m in msgs if m.get("type") == "user"), None)
                sessions.append({
                    "session_id": f.stem,
                    "message_count": len(msgs),
                    "preview": (first_user["content"][:80] if first_user else ""),
                    "updated_at": data.get("updated_at", 0),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return sessions

    @property
    def current_session(self) -> str | None:
        return self._current_session
