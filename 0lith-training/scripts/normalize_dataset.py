"""
normalize_dataset.py — Normalise un dataset vers le format ChatML pour Qwen3.5-4B.

Convertit les formats Alpaca, ShareGPT, QA simple et cybersec custom en un format
ChatML unifié avec system prompt agent injecté. Applique des filtres de qualité de base.

Usage :
  # Dry-run (aperçu 3 exemples, pas de sauvegarde)
  python scripts/normalize_dataset.py --dataset fenrir-cybersec/fenrir-v2 --agent blue --dry-run

  # Conversion complète
  python scripts/normalize_dataset.py --dataset fenrir-cybersec/fenrir-v2 --agent blue
  python scripts/normalize_dataset.py --dataset path/to/local.jsonl --agent red --format alpaca

  # Forcer un format (sans auto-détection)
  python scripts/normalize_dataset.py --dataset CyberSafetyAI/CyberLLMInstruct --agent red --format cybersec

  # Paramètres avancés
  python scripts/normalize_dataset.py --dataset AttackQA --agent red --split train --max-tokens 2048 --output data/processed/red_attackqa.jsonl

Formats supportés (auto-détectés ou via --format) :
  alpaca    : instruction / [input] / output
  sharegpt  : conversations (liste human/gpt ou user/assistant)
  qa        : question / answer  (ou prompt / response)
  cybersec  : formats hétérogènes Fenrir, CyberLLMInstruct, AttackQA, Trendyol
  auto      : détection automatique sur le premier exemple (défaut)

Format de sortie ChatML :
  {
    "messages": [
      {"role": "system",    "content": "<system prompt agent>"},
      {"role": "user",      "content": "<instruction>"},
      {"role": "assistant", "content": "<think>\\n[raisonnement]\\n</think>\\n\\n<réponse>"}
    ]
  }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# System prompts (identiques aux system_prompt dans les configs YAML)
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS: dict[str, str] = {
    "red": (
        "Tu es Pyrolith, un expert en sécurité offensive spécialisé dans les tests "
        "d'intrusion, l'analyse de vulnérabilités et la génération de stratégies "
        "d'attaque. Tu raisonnes étape par étape avant de répondre."
    ),
    "blue": (
        "Tu es Cryolith, un expert en sécurité défensive spécialisé dans l'analyse "
        "de logs, la détection de menaces, la génération de règles Sigma et la réponse "
        "aux incidents. Tu raisonnes étape par étape avant de répondre."
    ),
}

# Champs "thinking" reconnus dans les datasets cybersec récents
_THINK_FIELDS = ("thinking", "think", "thought", "chain_of_thought", "reasoning", "rationale")

# Rôles ShareGPT canoniques → rôles ChatML
_SHAREGPT_ROLE_MAP: dict[str, str] = {
    "human": "user",
    "user": "user",
    "gpt": "assistant",
    "assistant": "assistant",
    "system": "system",
}


# ---------------------------------------------------------------------------
# Token approximation (sans dépendance tokenizer)
# ---------------------------------------------------------------------------

def _approx_tokens(text: str) -> int:
    """Estime le nombre de tokens (approximation ~4 chars/token).

    Intentionnellement conservateur — la vraie tokenisation Qwen3.5-4B (BPE)
    peut varier, mais cette heuristique est suffisante pour le filtrage de longueur.
    """
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Format auto-détection
# ---------------------------------------------------------------------------

def detect_format(sample: dict) -> str:
    """Détecte le format source depuis les clés du premier exemple."""
    keys = set(sample.keys())

    # ShareGPT : liste de turns
    if "conversations" in keys or "conversation" in keys:
        return "sharegpt"

    # Alpaca : champ "instruction" explicite
    if "instruction" in keys:
        return "alpaca"

    # QA simple : question/answer ou prompt/response
    if ("question" in keys and "answer" in keys) or (
        "prompt" in keys and "response" in keys
    ):
        return "qa"

    # Cybersec hétérogène : tout le reste
    return "cybersec"


# ---------------------------------------------------------------------------
# Construction du contenu assistant avec <think> optionnel
# ---------------------------------------------------------------------------

def _build_assistant_content(response: str, thinking: str | None) -> str:
    """Insère le bloc <think> si une trace de raisonnement est disponible."""
    response = response.strip()
    if thinking:
        thinking = thinking.strip()
        return f"<think>\n{thinking}\n</think>\n\n{response}"
    return response


# ---------------------------------------------------------------------------
# Convertisseurs par format
# ---------------------------------------------------------------------------

def _convert_alpaca(row: dict, system_prompt: str) -> dict | None:
    """Alpaca : instruction / [input] / output.

    Si `input` est non-vide, il est concaténé à l'instruction (pratique standard).
    """
    instruction = str(row.get("instruction") or "").strip()
    inp = str(row.get("input") or "").strip()
    output = str(row.get("output") or "").strip()

    if not instruction or not output:
        return None

    user_content = f"{instruction}\n\n{inp}" if inp else instruction
    thinking = next((str(row[f]).strip() for f in _THINK_FIELDS if f in row and row[f]), None)

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": _build_assistant_content(output, thinking)},
        ]
    }


def _convert_sharegpt(row: dict, system_prompt: str) -> dict | None:
    """ShareGPT : conversations = [{from: human/gpt, value: ...}].

    Supporte aussi le champ "conversation" (singulier) et les rôles user/assistant.
    Les turns "system" internes sont ignorés (on injecte le nôtre).
    Conversations vides ou sans au moins un tour user+assistant sont ignorées.
    """
    raw_convs = row.get("conversations") or row.get("conversation") or []
    if not raw_convs or not isinstance(raw_convs, list):
        return None

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    for turn in raw_convs:
        if not isinstance(turn, dict):
            continue
        raw_role = str(turn.get("from") or turn.get("role") or "").lower()
        content = str(turn.get("value") or turn.get("content") or "").strip()
        role = _SHAREGPT_ROLE_MAP.get(raw_role)

        if role is None or role == "system" or not content:
            continue

        messages.append({"role": role, "content": content})

    # Doit contenir au minimum : system + user + assistant
    non_system = [m for m in messages if m["role"] != "system"]
    if len(non_system) < 2:
        return None

    # Le dernier message doit être de l'assistant
    if messages[-1]["role"] != "assistant":
        return None

    return {"messages": messages}


def _convert_qa(row: dict, system_prompt: str) -> dict | None:
    """QA simple : question/answer ou prompt/response."""
    question = str(row.get("question") or row.get("prompt") or "").strip()
    answer = str(row.get("answer") or row.get("response") or "").strip()

    if not question or not answer:
        return None

    thinking = next((str(row[f]).strip() for f in _THINK_FIELDS if f in row and row[f]), None)

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
            {"role": "assistant", "content": _build_assistant_content(answer, thinking)},
        ]
    }


def _convert_cybersec(row: dict, system_prompt: str) -> dict | None:
    """Formats cybersec hétérogènes : Fenrir, CyberLLMInstruct, AttackQA, Trendyol.

    Stratégie : essayer les combinaisons de champs par ordre de priorité.
    Fenrir v2.0 / Trendyol Defense : instruction + output (+ metadata optionnel)
    CyberLLMInstruct              : instruction + response  (ou output)
    AttackQA                      : question + answer
    Générique                     : input + output  /  text (pré-formaté)
    """
    thinking = next((str(row[f]).strip() for f in _THINK_FIELDS if f in row and row[f]), None)

    # Tentatives dans l'ordre de priorité
    candidates: list[tuple[str | None, str | None]] = [
        (row.get("instruction"), row.get("output")),
        (row.get("instruction"), row.get("response")),
        (row.get("question"), row.get("answer")),
        (row.get("input"), row.get("output")),
        (row.get("prompt"), row.get("completion")),
        (row.get("prompt"), row.get("response")),
    ]

    for raw_user, raw_assistant in candidates:
        user = str(raw_user or "").strip()
        assistant = str(raw_assistant or "").strip()
        if user and assistant:
            # Contexte optionnel (Fenrir/Trendyol peuvent avoir un champ "context")
            context = str(row.get("context") or row.get("background") or "").strip()
            if context:
                user = f"{context}\n\n{user}"
            return {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": _build_assistant_content(assistant, thinking)},
                ]
            }

    # Fallback : champ "text" pré-formaté (déjà en ChatML ou plain text)
    text = str(row.get("text") or "").strip()
    if text:
        # Si le texte contient déjà des markers ChatML on le laisse passer tel quel
        # comme un seul tour user (le trainer le traitera comme prompt complet)
        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
                {"role": "assistant", "content": ""},
            ]
        }

    return None


_CONVERTERS = {
    "alpaca": _convert_alpaca,
    "sharegpt": _convert_sharegpt,
    "qa": _convert_qa,
    "cybersec": _convert_cybersec,
}


# ---------------------------------------------------------------------------
# Filtre qualité
# ---------------------------------------------------------------------------

class QualityFilter:
    """Filtre de qualité en 4 couches : longueur, doublons, encoding, JSON."""

    def __init__(self, min_tokens: int, max_tokens: int) -> None:
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self._seen: set[str] = set()

        # Compteurs pour le rapport final
        self.counts: dict[str, int] = {
            "ok": 0,
            "too_short": 0,
            "too_long": 0,
            "duplicate": 0,
            "empty_content": 0,
        }

    def check(self, example: dict) -> tuple[bool, str]:
        """Retourne (ok, raison_rejet).

        Les exemples passent si ok=True. La raison est "ok" ou un code de rejet.
        """
        messages = example.get("messages", [])

        # Contenu non-vide dans tous les messages
        for msg in messages:
            if not str(msg.get("content") or "").strip():
                # Le message assistant vide du fallback cybersec est exclu
                self.counts["empty_content"] += 1
                return False, "empty_content"

        # Calcul de la longueur totale (tous les messages sauf system)
        full_text = " ".join(
            m["content"] for m in messages if m.get("role") != "system"
        )
        tokens = _approx_tokens(full_text)

        if tokens < self.min_tokens:
            self.counts["too_short"] += 1
            return False, f"too_short ({tokens} tokens estimés)"

        if tokens > self.max_tokens:
            self.counts["too_long"] += 1
            return False, f"too_long ({tokens} tokens estimés)"

        # Déduplication par SHA-256 du contenu complet (tous les messages)
        content_key = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(content_key.encode("utf-8")).hexdigest()
        if content_hash in self._seen:
            self.counts["duplicate"] += 1
            return False, "duplicate"

        self._seen.add(content_hash)
        self.counts["ok"] += 1
        return True, "ok"

    def report(self) -> str:
        total = sum(self.counts.values())
        kept = self.counts["ok"]
        lines = [
            f"  Total traités  : {total}",
            f"  Conservés      : {kept} ({kept / total * 100:.1f}% si total > 0)",
            f"  Trop courts    : {self.counts['too_short']}",
            f"  Trop longs     : {self.counts['too_long']}",
            f"  Doublons       : {self.counts['duplicate']}",
            f"  Contenu vide   : {self.counts['empty_content']}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chargement du dataset
# ---------------------------------------------------------------------------

def _load_rows(dataset_arg: str, split: str) -> Iterator[dict]:
    """Charge un dataset HuggingFace (nom ou chemin local) et yield les lignes."""
    # Chemin local : fichier JSONL
    local = Path(dataset_arg)
    if local.exists() and local.suffix in (".jsonl", ".json"):
        with local.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        return

    # Dossier local ou nom HuggingFace → utiliser datasets
    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        print(
            "ERREUR : la librairie 'datasets' n'est pas installée.\n"
            "  pip install datasets>=3.3.0",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        if local.exists() and local.is_dir():
            ds = load_dataset(str(local), split=split)
        else:
            ds = load_dataset(dataset_arg, split=split, trust_remote_code=False)
    except Exception as exc:
        print(f"ERREUR chargement dataset '{dataset_arg}' : {exc}", file=sys.stderr)
        sys.exit(1)

    yield from ds


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def _dataset_slug(dataset_arg: str) -> str:
    """Extrait un nom de fichier propre depuis le nom/chemin du dataset."""
    slug = Path(dataset_arg).stem if Path(dataset_arg).exists() else dataset_arg.split("/")[-1]
    # Remplacer les caractères invalides pour un nom de fichier
    for ch in r'\/:*?"<>|. ':
        slug = slug.replace(ch, "_")
    return slug.lower().strip("_") or "dataset"


def _print_example(idx: int, example: dict) -> None:
    """Affiche un exemple formaté pour --dry-run."""
    print(f"\n{'─' * 60}")
    print(f"  Exemple #{idx + 1}")
    print(f"{'─' * 60}")
    for msg in example["messages"]:
        role = msg["role"].upper()
        content = msg["content"]
        preview = content[:300] + ("…" if len(content) > 300 else "")
        print(f"\n  [{role}]\n  {preview}")
    print()


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalise un dataset vers le format ChatML pour Qwen3.5-4B (0Lith Training)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Nom HuggingFace (ex: fenrir-cybersec/fenrir-v2) ou chemin local (.jsonl)",
    )
    parser.add_argument(
        "--agent",
        required=True,
        choices=["red", "blue"],
        help="Agent cible : red (Pyrolith) ou blue (Cryolith)",
    )
    parser.add_argument(
        "--format",
        default="auto",
        choices=["auto", "alpaca", "sharegpt", "qa", "cybersec"],
        help="Format source (défaut: auto-détection sur le premier exemple)",
    )
    parser.add_argument(
        "--split",
        default="train",
        help="Split HuggingFace à charger (défaut: train)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Chemin de sortie .jsonl (défaut: data/processed/{agent}_{dataset}.jsonl)",
    )
    parser.add_argument(
        "--min-tokens",
        type=int,
        default=50,
        help="Longueur minimale en tokens estimés (défaut: 50)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Longueur maximale en tokens estimés (défaut: 4096)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Afficher 3 exemples convertis sans sauvegarder",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Afficher les raisons de rejet pour chaque exemple filtré",
    )

    args = parser.parse_args()

    system_prompt = SYSTEM_PROMPTS[args.agent]
    qfilter = QualityFilter(min_tokens=args.min_tokens, max_tokens=args.max_tokens)

    # Chemin de sortie
    if args.output:
        output_path = Path(args.output)
    else:
        slug = _dataset_slug(args.dataset)
        output_path = Path("data/processed") / f"{args.agent}_{slug}.jsonl"

    print(f"\n{'=' * 60}")
    print("  0Lith Training — normalize_dataset.py")
    print(f"{'=' * 60}")
    print(f"  Dataset   : {args.dataset}")
    print(f"  Agent     : {args.agent} ({'Pyrolith Red Team' if args.agent == 'red' else 'Cryolith Blue Team'})")
    print(f"  Format    : {args.format}")
    print(f"  Split     : {args.split}")
    print(f"  Tokens    : [{args.min_tokens}, {args.max_tokens}]")
    if args.dry_run:
        print("  Mode      : DRY-RUN (pas de sauvegarde)")
    else:
        print(f"  Sortie    : {output_path}")
    print(f"{'=' * 60}\n")

    # Chargement du dataset
    rows = _load_rows(args.dataset, args.split)

    detected_format: str | None = None
    converted: list[dict] = []
    dry_run_shown = 0
    total_rows = 0

    # Préparer le fichier de sortie (sauf dry-run)
    out_file = None
    if not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = output_path.open("w", encoding="utf-8")

    try:
        for row in rows:
            if not isinstance(row, dict):
                continue
            total_rows += 1

            # Auto-détection sur le premier exemple
            if detected_format is None:
                detected_format = args.format if args.format != "auto" else detect_format(row)
                print(f"  Format détecté : {detected_format}\n")

            converter = _CONVERTERS[detected_format]
            example = converter(row, system_prompt)

            if example is None:
                if args.verbose:
                    print(f"  [SKIP] ligne {total_rows} : conversion échouée (champs manquants)")
                continue

            ok, reason = qfilter.check(example)
            if not ok:
                if args.verbose:
                    print(f"  [SKIP] ligne {total_rows} : {reason}")
                continue

            if args.dry_run:
                _print_example(dry_run_shown, example)
                dry_run_shown += 1
                if dry_run_shown >= 3:
                    print("  (dry-run : 3 exemples affichés, arrêt anticipé)\n")
                    break
            else:
                out_file.write(json.dumps(example, ensure_ascii=False) + "\n")
                converted.append(example)  # conservé en mémoire pour le rapport

    finally:
        if out_file is not None:
            out_file.close()

    # Rapport final
    print(f"\n{'=' * 60}")
    print("  Rapport")
    print(f"{'=' * 60}")
    print(f"  Lignes lues    : {total_rows}")
    print(qfilter.report())

    if not args.dry_run:
        kept = qfilter.counts["ok"]
        print(f"\n  Fichier sauvegardé : {output_path}")
        print(f"  Exemples écrits    : {kept}")

        # Avertissement si le dataset est trop petit pour un run SFT
        if kept < 500:
            print(
                f"\n  ATTENTION : {kept} exemples est très peu pour un SFT de qualité.\n"
                "  Recommandation : 8 000–12 000 exemples minimum (voir 01_TRAINING_PLAN.md §5.1)."
            )

    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
