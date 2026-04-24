from pathlib import Path

from olith_shared import log_info
from olith_tools import tool_read_file, tool_list_files, tool_search_files


def cmd_set_project_root(backend, request: dict) -> dict:
    path = request.get("path", "").strip()
    if not path:
        return {"message": "Path vide", "status": "error"}
    p = Path(path).resolve()
    if not p.is_dir():
        return {"message": f"Répertoire introuvable: {path}", "status": "error"}
    backend.project_root = str(p)
    log_info("project", f"Project root set: {backend.project_root}")
    return {"project_root": backend.project_root, "message": f"Projet ouvert: {backend.project_root}"}


def cmd_read_file(backend, request: dict) -> dict:
    return tool_read_file(
        request.get("path", ""),
        backend.project_root,
        request.get("offset", 1),
        request.get("limit", 500),
    )


def cmd_list_files(backend, request: dict) -> dict:
    return tool_list_files(
        request.get("path", "."),
        backend.project_root,
        request.get("max_depth", 3),
    )


def cmd_search_files(backend, request: dict) -> dict:
    return tool_search_files(
        request.get("pattern", ""),
        backend.project_root,
        request.get("path", "."),
        request.get("glob", ""),
    )
