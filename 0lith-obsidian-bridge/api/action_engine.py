"""
0Lith — Action Engine
=====================
Moteur d'actions tag → Monolith → écriture dans le vault.

Tags built-in :
  #TODO      Exécute l'instruction sur la même ligne dans le contexte du doc
  #Rewrite   Réécrit le document entier proprement (Markdown structuré)
  #Summarize Ajoute un résumé en fin de document
  #Translate Traduit le document en anglais

Tags personnalisés : définis dans VAULT_PATH/.olith/tags.md (hot-reload).

Modes de sortie :
  replace_tag  Remplace uniquement le bloc #TAG ... par le résultat
  replace_doc  Remplace tout le contenu (backup automatique)
  append       Ajoute le résultat à la fin du fichier
"""

import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import VAULT_PATH, OLITH_DIR, ACTIONS_CONFIG_FILE, MODEL_NAME

from api import ollama_client


# ── Modèles ───────────────────────────────────────────────────────────────────

@dataclass
class TagAction:
    """Définition d'une action IA associée à un tag."""
    name: str
    system_prompt: str
    output_mode: str        # replace_tag | replace_doc | append
    description: str = ""


@dataclass
class ActionResult:
    """Résultat d'une action exécutée."""
    tag: str
    file_path: str
    output_mode: str
    success: bool
    result_preview: str = ""
    error: str = ""


# ── Actions built-in ─────────────────────────────────────────────────────────

_BUILTIN_ACTIONS: dict[str, TagAction] = {
    "TODO": TagAction(
        name="TODO",
        description="Exécute l'instruction dans le contexte du document.",
        output_mode="replace_tag",
        system_prompt=(
            "Tu es Monolith, l'IA du système 0Lith. "
            "L'utilisateur t'a laissé une instruction dans son vault Obsidian via le tag #TODO. "
            "Exécute l'instruction demandée en te basant sur le contenu du document. "
            "Réponds directement avec le résultat (Markdown), sans explication, sans intro. "
            "Ta réponse remplacera le bloc #TODO dans la note."
        ),
    ),
    "Rewrite": TagAction(
        name="Rewrite",
        description="Réécrit le document entier de manière propre et structurée.",
        output_mode="replace_doc",
        system_prompt=(
            "Tu es Monolith, l'IA du système 0Lith. "
            "Réécris ce document Obsidian de manière propre et structurée : "
            "ajoute des titres `#` / `##` logiques, regroupe les idées similaires, "
            "corrige la syntaxe Markdown, améliore la lisibilité. "
            "Conserve TOUT le contenu original, ne supprime rien. "
            "Réponds UNIQUEMENT avec le Markdown réécrit, sans commentaire."
        ),
    ),
    "Summarize": TagAction(
        name="Summarize",
        description="Génère un résumé et l'ajoute en fin de document.",
        output_mode="append",
        system_prompt=(
            "Tu es Monolith, l'IA du système 0Lith. "
            "Génère un résumé concis de ce document en 3-5 points clés (liste Markdown). "
            "Format attendu :\n\n"
            "## Résumé (généré par 0Lith)\n\n"
            "- Point clé 1\n- Point clé 2\n...\n\n"
            "Réponds UNIQUEMENT avec ce bloc Markdown."
        ),
    ),
    "Translate": TagAction(
        name="Translate",
        description="Traduit le document en anglais.",
        output_mode="replace_doc",
        system_prompt=(
            "Tu es Monolith, l'IA du système 0Lith. "
            "Traduis intégralement ce document en anglais en conservant le format Markdown exact "
            "(titres, listes, liens, code blocks). "
            "Réponds UNIQUEMENT avec le Markdown traduit, sans commentaire."
        ),
    ),
}

# Regex pour détecter #TagName (pas un tag Obsidian standard comme #mot seul)
_RE_ACTION_TAG = re.compile(r"(?:^|\s)#([A-Z][a-zA-Z0-9]+)(?:\s+(.+))?$", re.MULTILINE)

# Regex pour parser le fichier de config tags.md
_RE_SECTION = re.compile(r"^## ([A-Z][a-zA-Z0-9]+)\s*$", re.MULTILINE)
_RE_OUTPUT = re.compile(r"\*\*output\*\*:\s*(\w+)")


# ── Parser config ─────────────────────────────────────────────────────────────

def _parse_tags_config(config_path: Path) -> dict[str, TagAction]:
    """Parse le fichier .olith/tags.md pour les tags personnalisés."""
    if not config_path.exists():
        return {}

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    custom: dict[str, TagAction] = {}
    sections = _RE_SECTION.split(content)

    # sections[0] = intro, sections[1::2] = noms, sections[2::2] = corps
    names = sections[1::2]
    bodies = sections[2::2]

    for name, body in zip(names, bodies):
        name = name.strip()
        body = body.strip()

        # Extraire le mode de sortie
        m = _RE_OUTPUT.search(body)
        output_mode = m.group(1) if m else "replace_tag"
        if output_mode not in ("replace_tag", "replace_doc", "append"):
            output_mode = "replace_tag"

        # Le prompt système = corps sans la ligne **output**
        prompt = _RE_OUTPUT.sub("", body).strip()

        custom[name] = TagAction(
            name=name,
            system_prompt=prompt,
            output_mode=output_mode,
            description=f"Tag personnalisé : {name}",
        )

    return custom


# ── Moteur principal ──────────────────────────────────────────────────────────

class ActionEngine:
    """
    Traite les fichiers du vault contenant des tags d'action IA.

    Thread-safe : peut être appelé depuis le watcher background.
    """

    def __init__(self) -> None:
        self._log_lock = threading.Lock()

    # ── API publique ──────────────────────────────────────────────────────────

    def get_all_actions(self) -> dict[str, TagAction]:
        """Retourne les actions built-in + personnalisées (hot-reload du config)."""
        custom = _parse_tags_config(ACTIONS_CONFIG_FILE)
        # Les custom peuvent surcharger les built-in
        return {**_BUILTIN_ACTIONS, **custom}

    def process_file(self, path: Path) -> list[ActionResult]:
        """
        Analyse un fichier, exécute les actions pour chaque tag trouvé.

        Args:
            path: Chemin absolu du fichier .md.

        Returns:
            Liste des ActionResult (une par tag trouvé).
        """
        results: list[ActionResult] = []

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return [ActionResult(
                tag="?", file_path=str(path), output_mode="?",
                success=False, error=str(e),
            )]

        actions = self.get_all_actions()
        found_tags = self._find_action_tags(content, actions)

        if not found_tags:
            return []

        for tag_name, instruction, full_match in found_tags:
            action = actions[tag_name]
            result = self._run_action(path, content, action, instruction, full_match)
            results.append(result)

            # Recharger le contenu si le fichier a été modifié
            if result.success and action.output_mode in ("replace_tag", "replace_doc"):
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    break

        return results

    def ensure_config_exists(self) -> None:
        """Crée .olith/tags.md si absent (premier lancement)."""
        OLITH_DIR.mkdir(parents=True, exist_ok=True)
        if not ACTIONS_CONFIG_FILE.exists():
            ACTIONS_CONFIG_FILE.write_text(_DEFAULT_CONFIG, encoding="utf-8")
            print(f"[0Lith] Config tags créée : {ACTIONS_CONFIG_FILE}")

    # ── Interne ───────────────────────────────────────────────────────────────

    def _find_action_tags(
        self,
        content: str,
        actions: dict[str, TagAction],
    ) -> list[tuple[str, str, str]]:
        """
        Détecte les tags d'action dans le contenu.

        Returns:
            Liste de (tag_name, instruction, full_match_string).
        """
        found = []
        for match in _RE_ACTION_TAG.finditer(content):
            tag_name = match.group(1)
            if tag_name in actions:
                instruction = (match.group(2) or "").strip()
                full_match = match.group(0).strip()
                found.append((tag_name, instruction, full_match))
        return found

    def _run_action(
        self,
        path: Path,
        content: str,
        action: TagAction,
        instruction: str,
        full_match: str,
    ) -> ActionResult:
        """Exécute une action IA et écrit le résultat."""
        try:
            prompt = self._build_prompt(action, content, instruction)
            response = ollama_client.generate(
                prompt=prompt,
                system=action.system_prompt,
                model=MODEL_NAME,
                num_ctx=8192,
            )
            self._apply_output(path, content, response, action.output_mode, full_match)
            self._log_action(path, action.name, response[:200])

            return ActionResult(
                tag=action.name,
                file_path=str(path),
                output_mode=action.output_mode,
                success=True,
                result_preview=response[:200],
            )
        except Exception as e:
            self._log_action(path, action.name, f"ERREUR : {e}")
            return ActionResult(
                tag=action.name,
                file_path=str(path),
                output_mode=action.output_mode,
                success=False,
                error=str(e),
            )

    def _build_prompt(self, action: TagAction, content: str, instruction: str) -> str:
        """Construit le prompt utilisateur."""
        if action.output_mode == "replace_tag" and instruction:
            return (
                f"Instruction : {instruction}\n\n"
                f"## Contenu du document\n\n{content}"
            )
        return f"## Document à traiter\n\n{content}"

    def _apply_output(
        self,
        path: Path,
        content: str,
        result: str,
        mode: str,
        tag_block: str,
    ) -> None:
        """Applique le résultat selon le mode de sortie."""
        if mode == "replace_tag":
            # Remplace le bloc #TAG ... par le résultat
            new_content = content.replace(tag_block, result, 1)
            path.write_text(new_content, encoding="utf-8")

        elif mode == "replace_doc":
            self._backup(path, content)
            # Préserve le frontmatter YAML si présent
            frontmatter = _extract_frontmatter(content)
            if frontmatter:
                path.write_text(frontmatter + "\n" + result, encoding="utf-8")
            else:
                path.write_text(result, encoding="utf-8")

        elif mode == "append":
            separator = "\n\n---\n\n" if not content.endswith("\n\n") else "---\n\n"
            path.write_text(content + separator + result + "\n", encoding="utf-8")

    def _backup(self, path: Path, content: str) -> None:
        """Sauvegarde le fichier original avant modification destructive."""
        backup_dir = OLITH_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_path = backup_dir / f"{ts}_{path.name}"
        backup_path.write_text(content, encoding="utf-8")

    def _log_action(self, path: Path, tag: str, preview: str) -> None:
        """Ajoute une entrée au log des actions."""
        with self._log_lock:
            log_file = OLITH_DIR / "action_log.md"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                rel = path.relative_to(VAULT_PATH)
            except ValueError:
                rel = path
            entry = (
                f"- `{ts}` | **#{tag}** | `{rel}`\n"
                f"  > {preview[:120].replace(chr(10), ' ')}\n"
            )
            with self._log_lock:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(entry)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_frontmatter(content: str) -> str:
    """Extrait le bloc frontmatter YAML (---...---) s'il existe."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[: end + 3].strip()
    return ""


# ── Contenu par défaut du fichier de config ───────────────────────────────────

_DEFAULT_CONFIG = """\
# 0Lith — Configuration des Tags IA

Ce fichier définit les tags IA reconnus dans ton vault Obsidian.
Chaque `## TagName` crée un nouveau tag. Modifie-le directement dans Obsidian.

**Tags built-in** (toujours actifs) : `#TODO` · `#Rewrite` · `#Summarize` · `#Translate`

**output** possible : `replace_tag` | `replace_doc` | `append`

---

## Summarize
**output**: append
Génère un résumé concis en 3-5 points clés de ce document en français.
Format :
## Résumé (généré par 0Lith)
- Point 1
- Point 2

## Translate
**output**: replace_doc
Traduis intégralement ce document en anglais en conservant le format Markdown exact.

## Outline
**output**: append
Génère un plan hiérarchique (outline) de ce document en Markdown.
"""
