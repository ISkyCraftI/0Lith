"""
0Lith — Obsidian Bridge
=======================
Startup health checks. Run as CLI before launching the scheduler.

Exit code: 0 if all checks pass or only warnings, 1 if any check fails.

Usage:
    python api/health_check.py
    REQUIRED_MODELS=llama3.2 python api/health_check.py
"""

import importlib.util
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DAILY_PLANS_FOLDER, OLLAMA_URL, REQUIRED_MODELS, VAULT_PATH

# ok=True → ✅, ok=False → ❌ (blocking), ok=None → ⚠️  (non-blocking)
CheckResult = dict  # {"name": str, "ok": bool | None, "detail": str}


def _fetch_ollama_tags() -> tuple:
    """Single HTTP call shared by ollama_running and models_available."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        resp.raise_for_status()
        count = len(resp.json().get("models", []))
        result: CheckResult = {
            "name": "ollama_running",
            "ok": True,
            "detail": f"Ollama joignable, {count} modèle(s) disponible(s)",
        }
        return resp, result
    except Exception as e:
        result = {
            "name": "ollama_running",
            "ok": False,
            "detail": f"Ollama injoignable : {e}",
        }
        return None, result


def check_models_available(ollama_resp) -> CheckResult:
    if ollama_resp is None:
        return {
            "name": "models_available",
            "ok": False,
            "detail": "Ollama non disponible",
        }
    models = [m["name"] for m in ollama_resp.json().get("models", [])]
    missing = [m for m in REQUIRED_MODELS if not any(m in name for name in models)]
    if missing:
        return {
            "name": "models_available",
            "ok": False,
            "detail": f"Modèles manquants : {missing} (présents : {models})",
        }
    return {
        "name": "models_available",
        "ok": True,
        "detail": "Tous les modèles requis présents",
    }


def check_vault_readable() -> CheckResult:
    md_files = list(VAULT_PATH.rglob("*.md")) if VAULT_PATH.exists() else []
    if VAULT_PATH.exists() and md_files:
        return {
            "name": "vault_readable",
            "ok": True,
            "detail": f"Vault accessible, {len(md_files)} fichier(s) .md",
        }
    return {
        "name": "vault_readable",
        "ok": False,
        "detail": f"VAULT_PATH introuvable ou vide : {VAULT_PATH}",
    }


def check_daily_plans_folder() -> CheckResult:
    try:
        DAILY_PLANS_FOLDER.mkdir(parents=True, exist_ok=True)
        return {
            "name": "daily_plans_folder",
            "ok": True,
            "detail": f"Dossier existant ou créé : {DAILY_PLANS_FOLDER}",
        }
    except PermissionError as e:
        return {
            "name": "daily_plans_folder",
            "ok": False,
            "detail": f"Impossible de créer le dossier : {e}",
        }


def check_timetree_env() -> CheckResult:
    has_ical = bool(os.environ.get("TIMETREE_ICAL_URL"))
    has_scraper = all(
        os.environ.get(k)
        for k in ["TIMETREE_EMAIL", "TIMETREE_PASSWORD", "TIMETREE_CALENDAR_CODE"]
    )
    if has_ical:
        mode = "ical"
    elif has_scraper:
        mode = "scraper"
    else:
        return {
            "name": "timetree_env",
            "ok": None,
            "detail": "Aucune variable TimeTree — fallback disponibilites.md actif",
        }
    return {
        "name": "timetree_env",
        "ok": True,
        "detail": f"Variables TimeTree présentes ({mode})",
    }


def check_scheduler_importable() -> CheckResult:
    scheduler_path = Path(__file__).parent.parent / "scheduler.py"
    spec = importlib.util.spec_from_file_location("scheduler", scheduler_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return {
            "name": "scheduler_py",
            "ok": True,
            "detail": "scheduler.py importé sans erreur",
        }
    except Exception as e:
        return {
            "name": "scheduler_py",
            "ok": False,
            "detail": f"Erreur d'import scheduler.py : {e}",
        }


def run_all_checks() -> list[CheckResult]:
    ollama_resp, ollama_result = _fetch_ollama_tags()
    return [
        ollama_result,
        check_models_available(ollama_resp),
        check_vault_readable(),
        check_daily_plans_folder(),
        check_timetree_env(),
        check_scheduler_importable(),
    ]


if __name__ == "__main__":
    ICONS = {True: "✅", False: "❌", None: "⚠️ "}

    results = run_all_checks()
    print()
    for r in results:
        icon = ICONS[r["ok"]]
        print(f"  {icon} {r['name']:<30} {r['detail']}")
    print()

    has_error = any(r["ok"] is False for r in results)
    sys.exit(1 if has_error else 0)
