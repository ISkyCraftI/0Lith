"""
0Lith — Obsidian Bridge API
============================
Serveur FastAPI exposant le vault Arkhe et l'IA Monolith (qwen3:14b).

Lancement :
    uvicorn api.main:app --reload --host 127.0.0.1 --port 8765
"""

import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import VAULT_PATH, MODEL_NAME, OLLAMA_URL, WATCHER_INACTIVITY_SECONDS

from api.obsidian_reader import ObsidianIndex
from api.scheduler_agent import SchedulerAgent
from api.vault_watcher import VaultWatcher
from api.action_engine import ActionEngine
from api import ollama_client


# ── Singletons ────────────────────────────────────────────────────────────────

_index = ObsidianIndex(VAULT_PATH)
_scheduler = SchedulerAgent()
_action_engine = ActionEngine()
_watcher = VaultWatcher(action_engine=_action_engine)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Charge l'index et démarre le watcher au démarrage."""
    print(f"[0Lith] Chargement du vault : {VAULT_PATH}")
    _index.load()
    notes = _index.get_all_notes()
    tasks = _index.get_all_tasks()
    print(f"[0Lith] Index prêt — {len(notes)} notes, {len(tasks)} tâches ouvertes")

    _watcher.start()
    yield

    _watcher.stop()


app = FastAPI(
    title="0Lith — Obsidian Bridge",
    description="Connecte le vault Arkhe à l'IA locale Monolith (qwen3:14b).",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Schémas Pydantic ──────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., description="Question à poser à Monolith.")
    context_notes: list[str] = Field(
        default_factory=list,
        description="Chemins relatifs de notes à injecter comme contexte.",
    )


class PlanDayRequest(BaseModel):
    date: Optional[str] = Field(
        None,
        description="Date ISO YYYY-MM-DD (défaut : aujourd'hui).",
    )
    free_slots: list[str] = Field(
        default_factory=lambda: ["09:00-12:00", "14:00-18:00"],
        description="Créneaux disponibles, ex. ['09:00-12:00', '14:00-18:00'].",
    )
    write_to_vault: bool = Field(
        False,
        description="Si True, écrit le planning dans Daily Plans/ du vault.",
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", summary="Statut de l'API et des services")
def health() -> dict:
    """Vérifie que Ollama répond et retourne l'état de l'index."""
    ollama_ok = ollama_client.is_available()
    notes = _index.get_all_notes()
    tasks = _index.get_all_tasks()
    return {
        "status": "ok",
        "ollama": {
            "url": OLLAMA_URL,
            "available": ollama_ok,
            "model": MODEL_NAME,
            "loaded_models": ollama_client.get_loaded_models() if ollama_ok else [],
        },
        "vault": {
            "path": str(VAULT_PATH),
            "notes": len(notes),
            "open_tasks": len(tasks),
        },
    }


@app.post("/refresh", summary="Recharge l'index du vault")
def refresh_index() -> dict:
    """Force le rechargement incrémental de l'index (fichiers modifiés uniquement)."""
    reloaded = _index.refresh()
    return {
        "reloaded_files": reloaded,
        "total_notes": len(_index.get_all_notes()),
        "open_tasks": len(_index.get_all_tasks()),
    }


@app.get("/notes", summary="Toutes les notes du vault")
def get_notes(
    search: Optional[str] = None,
    tag: Optional[str] = None,
) -> list[dict]:
    """
    Retourne toutes les notes indexées.

    Args:
        search: Filtre textuel (titre + contenu).
        tag: Filtre par tag (sans #).
    """
    notes = _index.search_notes(search) if search else _index.get_all_notes()

    if tag:
        notes = [n for n in notes if tag in n.tags]

    return [n.to_dict() for n in notes]


@app.get("/notes/{note_path:path}", summary="Contenu d'une note")
def get_note(note_path: str) -> dict:
    """Retourne le contenu complet d'une note par son chemin relatif."""
    all_notes = _index.get_all_notes()
    note = next((n for n in all_notes if n.path == note_path), None)
    if not note:
        raise HTTPException(status_code=404, detail=f"Note introuvable : {note_path}")
    return note.to_dict_full()


@app.get("/tasks", summary="Tâches non complétées")
def get_tasks(
    priority: Optional[str] = None,
    project: Optional[str] = None,
    tag: Optional[str] = None,
) -> list[dict]:
    """
    Retourne toutes les tâches ouvertes du vault.

    Args:
        priority: Filtre par priorité (critical|high|normal|low).
        project: Filtre par projet.
        tag: Filtre par tag (sans #).
    """
    tasks = _index.get_all_tasks(include_completed=False)

    if priority:
        tasks = [t for t in tasks if t.priority == priority]
    if project:
        tasks = [t for t in tasks if t.project == project]
    if tag:
        tasks = [t for t in tasks if tag in t.tags]

    return [t.to_dict() for t in tasks]


@app.get("/projects", summary="Liste des projets")
def get_projects() -> list[str]:
    """Retourne la liste des projets déduits du vault."""
    return _index.get_projects()


@app.post("/ai/query", summary="Question libre à Monolith")
def ai_query(body: QueryRequest) -> dict:
    """
    Envoie une question à Monolith avec contexte optionnel du vault.

    Le contexte des notes est injecté dans le prompt système.
    """
    if not ollama_client.is_available():
        raise HTTPException(status_code=503, detail="Ollama non disponible.")

    # Construction du contexte à partir des notes demandées
    context_parts: list[str] = []
    if body.context_notes:
        all_notes = {n.path: n for n in _index.get_all_notes()}
        for note_path in body.context_notes:
            note = all_notes.get(note_path)
            if note:
                context_parts.append(f"### {note.title}\n{note.content[:2000]}")

    system = (
        "Tu es Monolith, l'orchestrateur IA du système 0Lith. "
        "Tu as accès au vault Obsidian de Matthieu. "
        "Réponds en français, de manière concise et utile."
    )
    if context_parts:
        system += "\n\n## Contexte du vault\n\n" + "\n\n".join(context_parts)

    try:
        response = ollama_client.generate(prompt=body.question, system=system)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"response": response, "model": MODEL_NAME}


@app.post("/ai/plan-day", summary="Génère le planning journalier")
def ai_plan_day(body: PlanDayRequest) -> dict:
    """
    Demande à Monolith de générer un planning journalier optimisé.

    Injecte les tâches ouvertes du vault avec leurs métadonnées.
    Optionnellement écrit le résultat dans Daily Plans/ du vault.
    """
    if not ollama_client.is_available():
        raise HTTPException(status_code=503, detail="Ollama non disponible.")

    # Parse la date
    if body.date:
        try:
            target_date = date.fromisoformat(body.date)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Date invalide : {body.date}")
    else:
        target_date = date.today()

    tasks = _index.get_all_tasks(include_completed=False)
    if not tasks:
        return {
            "date": target_date.isoformat(),
            "plan": "Aucune tâche ouverte dans le vault.",
            "written_to": None,
        }

    try:
        plan = _scheduler.plan_day(tasks, body.free_slots, target_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    written_to: Optional[str] = None
    if body.write_to_vault:
        path = _scheduler.write_daily_plan(target_date, plan)
        written_to = str(path)

    return {
        "date": target_date.isoformat(),
        "plan": plan,
        "task_count": len(tasks),
        "model": MODEL_NAME,
        "written_to": written_to,
    }


@app.get("/watcher/status", summary="État du watcher et dernières actions")
def watcher_status() -> dict:
    """Retourne les fichiers en attente, en traitement, et les 10 dernières actions."""
    return _watcher.status()


@app.get("/watcher/actions", summary="Liste des tags IA disponibles")
def watcher_actions() -> dict:
    """Retourne tous les tags IA reconnus (built-in + personnalisés)."""
    actions = _action_engine.get_all_actions()
    return {
        name: {
            "output_mode": a.output_mode,
            "description": a.description,
        }
        for name, a in actions.items()
    }


@app.post("/watcher/trigger/{note_path:path}", summary="Forcer le traitement d'une note")
def watcher_trigger(note_path: str) -> dict:
    """
    Force le traitement immédiat d'une note (sans attendre 120s).

    Args:
        note_path: Chemin relatif de la note dans le vault.
    """
    abs_path = VAULT_PATH / note_path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=f"Note introuvable : {note_path}")

    results = _action_engine.process_file(abs_path)
    if not results:
        return {"message": "Aucun tag IA trouvé dans cette note.", "results": []}

    return {
        "results": [
            {
                "tag": r.tag,
                "success": r.success,
                "mode": r.output_mode,
                "preview": r.result_preview[:200] if r.success else r.error,
            }
            for r in results
        ]
    }
