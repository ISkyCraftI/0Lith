"""
0Lith — Obsidian Reader
=======================
Indexe le vault Obsidian en mémoire avec rechargement incrémental.
Supporte les vaults de 5000+ notes via cache par mtime.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import frontmatter  # python-frontmatter

from api.task_parser import Task, parse_tasks

# Ajout du parent pour l'import de config depuis n'importe quel contexte
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import VAULT_PATH, VAULT_EXTENSIONS, VAULT_IGNORE_DIRS


# ── Modèles ───────────────────────────────────────────────────────────────────

@dataclass
class NoteData:
    """Représente une note Obsidian indexée."""

    path: str
    """Chemin relatif au vault."""

    title: str
    """Titre déduit du H1 ou du nom du fichier."""

    content: str
    """Contenu brut (sans frontmatter)."""

    frontmatter: dict
    """Métadonnées YAML du frontmatter."""

    tasks: list[Task]
    """Tâches parsées dans la note."""

    tags: list[str]
    """Tags inline #xxx trouvés dans le contenu."""

    mtime: float
    """Timestamp de dernière modification (os.path.getmtime)."""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "tags": self.tags,
            "frontmatter": self.frontmatter,
            "task_count": len(self.tasks),
            "open_tasks": sum(1 for t in self.tasks if not t.completed),
        }

    def to_dict_full(self) -> dict:
        base = self.to_dict()
        base["content"] = self.content
        base["tasks"] = [t.to_dict() for t in self.tasks]
        return base


_RE_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_RE_TAG = re.compile(r"(?<!\w)#([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ0-9_/-]*)")


# ── Index ─────────────────────────────────────────────────────────────────────

class ObsidianIndex:
    """
    Index en mémoire du vault Obsidian.

    Stratégie de cache :
        - Première charge : scan complet.
        - `refresh()` : recharge uniquement les fichiers dont le mtime a changé.
        - Complexité : O(n) sur les fichiers modifiés, O(1) lecture.
    """

    def __init__(self, vault_path: Path = VAULT_PATH) -> None:
        self.vault_path = vault_path
        # Clé : chemin absolu. Valeur : NoteData
        self._cache: dict[str, NoteData] = {}
        self._loaded = False

    # ── Chargement ────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Charge l'index complet depuis le vault."""
        self._cache.clear()
        for md_file in self._iter_md_files():
            note = self._parse_file(md_file)
            if note:
                self._cache[str(md_file)] = note
        self._loaded = True

    def refresh(self) -> int:
        """
        Rechargement incrémental : reparse uniquement les fichiers modifiés
        et supprime les notes dont les fichiers ont disparu.

        Returns:
            Nombre de fichiers rechargés.
        """
        if not self._loaded:
            self.load()
            return len(self._cache)

        current_files = {str(f): f for f in self._iter_md_files()}
        reloaded = 0

        # Nouvelles notes ou modifiées
        for abs_path, md_file in current_files.items():
            try:
                mtime = md_file.stat().st_mtime
            except OSError:
                continue
            cached = self._cache.get(abs_path)
            if cached is None or cached.mtime != mtime:
                note = self._parse_file(md_file)
                if note:
                    self._cache[abs_path] = note
                    reloaded += 1

        # Fichiers supprimés
        removed = set(self._cache) - set(current_files)
        for path in removed:
            del self._cache[path]

        return reloaded

    # ── Accès ─────────────────────────────────────────────────────────────────

    def get_all_notes(self) -> list[NoteData]:
        """Retourne toutes les notes indexées."""
        if not self._loaded:
            self.load()
        return list(self._cache.values())

    def get_all_tasks(self, include_completed: bool = False) -> list[Task]:
        """Retourne toutes les tâches du vault."""
        if not self._loaded:
            self.load()
        tasks: list[Task] = []
        for note in self._cache.values():
            for task in note.tasks:
                if include_completed or not task.completed:
                    tasks.append(task)
        return tasks

    def get_projects(self) -> list[str]:
        """
        Déduit la liste des projets à partir de :
        1. Champ `project` des tâches.
        2. Sous-dossiers du dossier Projects/ si présent.
        """
        if not self._loaded:
            self.load()

        projects: set[str] = set()

        # Depuis les tâches
        for note in self._cache.values():
            for task in note.tasks:
                if task.project:
                    projects.add(task.project)

        # Depuis la structure Projects/
        projects_dir = self.vault_path / "Projects"
        if projects_dir.exists():
            for item in projects_dir.iterdir():
                if item.is_dir():
                    projects.add(item.name)

        return sorted(projects)

    def search_notes(self, query: str) -> list[NoteData]:
        """Recherche textuelle simple (insensible à la casse)."""
        if not self._loaded:
            self.load()
        q = query.lower()
        return [
            n for n in self._cache.values()
            if q in n.title.lower() or q in n.content.lower()
        ]

    # ── Interne ───────────────────────────────────────────────────────────────

    def _iter_md_files(self):
        """Itère récursivement sur les fichiers .md en ignorant les dossiers système."""
        for file in self.vault_path.rglob("*"):
            if file.suffix not in VAULT_EXTENSIONS:
                continue
            # Ignorer si un segment du chemin est dans VAULT_IGNORE_DIRS
            if any(part in VAULT_IGNORE_DIRS for part in file.parts):
                continue
            yield file

    def _parse_file(self, file: Path) -> Optional[NoteData]:
        """Parse un fichier .md en NoteData. Retourne None si erreur."""
        try:
            mtime = file.stat().st_mtime
            raw = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        # Frontmatter YAML
        try:
            post = frontmatter.loads(raw)
            meta: dict = dict(post.metadata)
            body: str = post.content
        except Exception:
            meta = {}
            body = raw

        # Titre : H1 en priorité, sinon nom du fichier sans extension
        h1 = _RE_H1.search(body)
        title = h1.group(1).strip() if h1 else file.stem

        # Tags inline dans le corps
        tags = list({t for t in _RE_TAG.findall(body)})

        # Chemin relatif au vault
        try:
            rel_path = str(file.relative_to(self.vault_path))
        except ValueError:
            rel_path = str(file)

        # Tâches
        tasks = parse_tasks(body, source_file=rel_path)

        return NoteData(
            path=rel_path,
            title=title,
            content=body,
            frontmatter=meta,
            tasks=tasks,
            tags=tags,
            mtime=mtime,
        )
