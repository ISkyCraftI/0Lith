#!/usr/bin/env python3
"""
0Lith V1 — Filesystem Tools + Tool-Call Parser
================================================
Outils sandboxés pour read/write/list/search/edit de fichiers.
Parser pour détecter les tool calls JSON dans les réponses IA.
"""

import os
import re
import json
from pathlib import Path

from olith_shared import TEXT_EXTENSIONS, IGNORED_DIRS, log_warn

# ============================================================================
# LIMITES
# ============================================================================

MAX_FILE_SIZE = 500 * 1024       # 500 KB pour read/write
MAX_SEARCH_FILE_SIZE = 50 * 1024 # 50 KB pour search (perf)
MAX_SEARCH_RESULTS = 50
MAX_LIST_FILES = 200
MAX_AGENT_LOOP_ITERATIONS = 10

# Actions par niveau d'autonomie
LEVEL_0_ACTIONS = {"read_file", "list_files", "search_files", "search_mem0", "add_mem0"}
LEVEL_2_ACTIONS = {"write_file", "edit_file"}


# ============================================================================
# PATH VALIDATION (Sandbox)
# ============================================================================

def validate_path(path: str, project_root: str | None) -> Path:
    """Resout un chemin. Les chemins absolus sont acceptes directement.
    Les chemins relatifs sont resolus par rapport au project_root."""
    p = Path(path)

    if p.is_absolute():
        return p.resolve()

    if not project_root:
        raise ValueError("Chemin relatif sans projet ouvert. Utilise un chemin absolu ou set_project_root d'abord.")

    return (Path(project_root).resolve() / path).resolve()


# ============================================================================
# FILESYSTEM TOOLS
# ============================================================================

def tool_read_file(path: str, project_root: str | None, offset: int = 1, limit: int = 500) -> dict:
    """Lit le contenu d'un fichier dans le sandbox."""
    target = validate_path(path, project_root)

    if not target.is_file():
        return {"error": f"Fichier introuvable: {path}"}

    if target.suffix.lower() not in TEXT_EXTENSIONS and target.suffix != "":
        return {"error": f"Type de fichier non supporté: {target.suffix}"}

    size = target.stat().st_size
    if size > MAX_FILE_SIZE:
        return {"error": f"Fichier trop volumineux ({size} bytes, max {MAX_FILE_SIZE})"}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Erreur de lecture: {e}"}

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    start = max(0, offset - 1)
    end = start + limit
    selected = lines[start:end]

    try:
        display_path = str(target.relative_to(Path(project_root).resolve())) if project_root else str(target)
    except ValueError:
        display_path = str(target)

    return {
        "path": display_path,
        "content": "".join(selected),
        "total_lines": total_lines,
        "showing": f"lines {start+1}-{min(end, total_lines)} of {total_lines}",
    }


def tool_list_files(path: str, project_root: str | None, max_depth: int = 3) -> dict:
    """Liste les fichiers d'un repertoire (tree)."""
    target = validate_path(path, project_root)

    if not target.is_dir():
        return {"error": f"Répertoire introuvable: {path}"}

    # Base pour les chemins relatifs dans la sortie
    root = Path(project_root).resolve() if project_root else target
    files = []
    dirs = []

    def _rel(entry: Path) -> str:
        try:
            return str(entry.relative_to(root)).replace("\\", "/")
        except ValueError:
            return str(entry).replace("\\", "/")

    def _walk(dir_path: Path, depth: int):
        if depth > max_depth or len(files) + len(dirs) >= MAX_LIST_FILES:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        for entry in entries:
            if entry.name in IGNORED_DIRS:
                continue
            rel = _rel(entry)
            if entry.is_dir():
                dirs.append(rel + "/")
                _walk(entry, depth + 1)
            elif entry.is_file():
                files.append(rel)

    _walk(target, 0)

    return {
        "path": _rel(target) or ".",
        "files": files[:MAX_LIST_FILES],
        "dirs": dirs[:MAX_LIST_FILES],
        "total": len(files) + len(dirs),
        "truncated": len(files) + len(dirs) >= MAX_LIST_FILES,
    }


def tool_search_files(pattern: str, project_root: str | None, path: str = ".", glob_pattern: str = "") -> dict:
    """Recherche un pattern (regex) dans les fichiers du projet."""
    target = validate_path(path, project_root)
    root = Path(project_root).resolve() if project_root else target

    if not target.is_dir():
        return {"error": f"Répertoire introuvable: {path}"}

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"error": f"Regex invalide: {e}"}

    def _rel(fpath: Path) -> str:
        try:
            return str(fpath.relative_to(root)).replace("\\", "/")
        except ValueError:
            return str(fpath).replace("\\", "/")

    results = []

    for dirpath, dirnames, filenames in os.walk(str(target)):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]

        for fname in filenames:
            if len(results) >= MAX_SEARCH_RESULTS:
                break

            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            if glob_pattern and not fpath.match(glob_pattern):
                continue
            try:
                if fpath.stat().st_size > MAX_SEARCH_FILE_SIZE:
                    continue
            except OSError:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        results.append({
                            "file": _rel(fpath),
                            "line": i,
                            "content": line.rstrip()[:200],
                        })
                        if len(results) >= MAX_SEARCH_RESULTS:
                            break
            except Exception:
                continue

    return {
        "pattern": pattern,
        "results": results,
        "total": len(results),
        "truncated": len(results) >= MAX_SEARCH_RESULTS,
    }


def tool_write_file(path: str, content: str, project_root: str | None) -> dict:
    """Ecrit un fichier complet (cree les repertoires parents si necessaire)."""
    target = validate_path(path, project_root)
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"error": f"Erreur d'écriture: {e}"}

    try:
        display_path = str(target.relative_to(Path(project_root).resolve())) if project_root else str(target)
    except ValueError:
        display_path = str(target)

    return {
        "path": display_path,
        "size": len(content),
        "message": f"Fichier écrit: {path}",
    }


def tool_edit_file(path: str, old_string: str, new_string: str, project_root: str | None) -> dict:
    """Remplace old_string par new_string dans un fichier (exact match unique)."""
    target = validate_path(path, project_root)

    if not target.is_file():
        return {"error": f"Fichier introuvable: {path}"}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Erreur de lecture: {e}"}

    count = content.count(old_string)
    if count == 0:
        return {"error": f"old_string introuvable dans {path}"}
    if count > 1:
        return {"error": f"old_string trouvé {count} fois (doit être unique). Ajoute plus de contexte."}

    new_content = content.replace(old_string, new_string, 1)

    try:
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {"error": f"Erreur d'écriture: {e}"}

    try:
        display_path = str(target.relative_to(Path(project_root).resolve())) if project_root else str(target)
    except ValueError:
        display_path = str(target)

    return {
        "path": display_path,
        "message": f"Édition appliquée dans {path}",
    }


def tool_system_info() -> dict:
    """Retourne les infos systeme : OS, processus actifs, memoire, GPU."""
    import subprocess
    info = {}

    # OS info
    try:
        result = subprocess.run(
            ["wmic", "os", "get", "Caption,Version,TotalVisibleMemorySize", "/format:csv"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 4 and parts[1] and parts[1] != "Caption":
                info["os"] = parts[1].strip()
                info["os_version"] = parts[2].strip()
                total_kb = int(parts[3].strip())
                info["total_ram_gb"] = round(total_kb / 1024 / 1024, 1)
    except Exception:
        info["os"] = "Windows (details unavailable)"

    # Running processes — top 30 by memory
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        processes = []
        for line in result.stdout.strip().splitlines():
            # Format: "name","PID","Session","Session#","Mem Usage"
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 5:
                name = parts[0]
                pid = parts[1]
                mem_str = parts[4].replace('"', '').replace('\xa0', '').replace(' ', '')
                mem_str = ''.join(c for c in mem_str if c.isdigit())
                mem_kb = int(mem_str) if mem_str else 0
                processes.append({"name": name, "pid": int(pid), "mem_mb": round(mem_kb / 1024, 1)})
        # Sort by memory, top 30
        processes.sort(key=lambda p: p["mem_mb"], reverse=True)
        info["processes"] = processes[:30]
        info["total_processes"] = len(processes)
    except Exception as e:
        info["processes_error"] = str(e)

    # GPU info via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    info["gpu"] = {
                        "name": parts[0],
                        "vram_total_mb": int(parts[1]),
                        "vram_used_mb": int(parts[2]),
                        "vram_free_mb": int(parts[3]),
                        "gpu_utilization_pct": int(parts[4]),
                    }
    except FileNotFoundError:
        info["gpu"] = "nvidia-smi not found"
    except Exception as e:
        info["gpu_error"] = str(e)

    return info


def execute_tool(action: str, args: dict, project_root: str | None) -> dict:
    """Execute un outil filesystem et retourne le resultat."""
    dispatch = {
        "read_file":    lambda: tool_read_file(args["path"], project_root, args.get("offset", 1), args.get("limit", 500)),
        "list_files":   lambda: tool_list_files(args.get("path", "."), project_root, args.get("max_depth", 3)),
        "search_files": lambda: tool_search_files(args["pattern"], project_root, args.get("path", "."), args.get("glob", "")),
        "write_file":   lambda: tool_write_file(args["path"], args["content"], project_root),
        "edit_file":    lambda: tool_edit_file(args["path"], args["old_string"], args["new_string"], project_root),
    }

    handler = dispatch.get(action)
    if not handler:
        return {"error": f"Action inconnue: {action}"}

    try:
        return handler()
    except KeyError as e:
        return {"error": f"Paramètre manquant pour {action}: {e}"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        log_warn("tools", f"Tool {action} failed: {e}")
        return {"error": f"Erreur outil {action}: {e}"}


# ============================================================================
# TOOL-CALL PARSER
# ============================================================================

def parse_tool_calls(response_text: str) -> tuple[str, list[dict]]:
    """Parse une reponse d'IA pour extraire les tool calls JSON.

    Detecte les patterns:
      ```json\\n{"action": "...", ...}\\n```
      ou directement {"action": "..."} sur une ligne

    Retourne (texte_sans_tools, liste_de_tool_calls)
    """
    tool_calls = []

    # Pattern 1: blocs ```json ... ``` contenant une action
    code_block_pattern = re.compile(
        r'```(?:json)?\s*\n(\{[^`]*?"action"\s*:\s*"[^"]+?"[^`]*?\})\s*\n```',
        re.DOTALL
    )

    # Pattern 2: JSON brut sur une ligne (fallback)
    inline_pattern = re.compile(
        r'^(\{"action"\s*:\s*"[^"]+?"[^\n]*\})\s*$',
        re.MULTILINE
    )

    clean_text = response_text

    for match in code_block_pattern.finditer(response_text):
        try:
            obj = json.loads(match.group(1))
            if "action" in obj:
                tool_calls.append(obj)
                clean_text = clean_text.replace(match.group(0), "")
        except json.JSONDecodeError:
            continue

    for match in inline_pattern.finditer(clean_text):
        try:
            obj = json.loads(match.group(1))
            if "action" in obj and obj not in tool_calls:
                tool_calls.append(obj)
                clean_text = clean_text.replace(match.group(0), "")
        except json.JSONDecodeError:
            continue

    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

    return clean_text, tool_calls
