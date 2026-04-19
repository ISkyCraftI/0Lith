"""
generate_synthetic.py — Génération de données d'entraînement synthétiques.

Utilise un modèle teacher (local Ollama ou API externe) pour produire des
exemples d'entraînement ChatML à partir de templates YAML.

Usage :
  # Ollama local — gratuit, idéal pour la nuit
  python scripts/generate_synthetic.py --teacher ollama:qwen3:14b --template templates/red_team_generation.yaml
  python scripts/generate_synthetic.py --teacher ollama:qwen3.5-27b --template templates/blue_team_generation.yaml

  # API OpenAI — haute qualité, payant
  python scripts/generate_synthetic.py --teacher openai:gpt-4o --template templates/red_team_generation.yaml
  python scripts/generate_synthetic.py --teacher openai:gpt-4o-mini --template templates/blue_team_generation.yaml

  # API Anthropic — diversité stylistique, payant
  python scripts/generate_synthetic.py --teacher anthropic:claude-sonnet-4-5 --template templates/red_team_generation.yaml

  # Options communes
  python scripts/generate_synthetic.py --teacher ollama:qwen3:14b --template templates/red_team_generation.yaml --dry-run
  python scripts/generate_synthetic.py --teacher ollama:qwen3:14b --template templates/red_team_generation.yaml --category exploitation
  python scripts/generate_synthetic.py --teacher openai:gpt-4o-mini --template templates/red_team_generation.yaml --count 10

  # Mode local uniquement — 0€ de coût API (Phase 1 + Phase 2)
  python scripts/generate_synthetic.py --teacher ollama:qwen3:14b --template templates/red_team_quicktest.yaml --local-only
  python scripts/generate_synthetic.py --teacher ollama:qwen3:14b --template templates/red_team_generation.yaml --local-only

  # Phase 3 ciblée — avec confirmation coût (> 5€) et refus automatique (> 50€)
  python scripts/generate_synthetic.py --teacher openai:gpt-4o-mini --template templates/red_team_generation.yaml --category exploitation --count 15
  python scripts/generate_synthetic.py --teacher openai:gpt-4o --template templates/red_team_generation.yaml --force-expensive  # > 50€, débloqué explicitement

Format de sortie (ChatML, identique à normalize_dataset.py) :
  {
    "messages": [
      {"role": "system",    "content": "<system_prompt>"},
      {"role": "user",      "content": "<prompt généré depuis le template>"},
      {"role": "assistant", "content": "<réponse teacher avec <think>...</think>>"}
    ],
    "metadata": {
      "category": "exploitation",
      "teacher": "openai:gpt-4o",
      "variation": {"technique_name": "SQL Injection"},
      "tokens_in": 420, "tokens_out": 890,
      "generation_time_s": 3.2,
      "template_file": "red_team_generation.yaml",
      "agent": "red"
    }
  }
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Iterator

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR     = Path(__file__).parent.parent
DATA_SYNTH   = BASE_DIR / "data" / "synthetic"
TEMPLATES_DIR = BASE_DIR / "templates"

# ---------------------------------------------------------------------------
# Pricing (per 1M tokens, USD, as of 2025/2026 — update when prices change)
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    "gpt-4o":              {"in": 2.50,  "out": 10.00},
    "gpt-4o-mini":         {"in": 0.15,  "out": 0.60},
    "gpt-4o-mini-2024-11-05": {"in": 0.15, "out": 0.60},
    "claude-sonnet-4-5":   {"in": 3.00,  "out": 15.00},
    "claude-opus-4-6":     {"in": 15.00, "out": 75.00},
    "claude-haiku-4-5":    {"in": 0.80,  "out": 4.00},
}

# USD → EUR rough conversion rate (update if needed)
EUR_RATE = 0.92

# Average token estimates per example (conservative, system+user / response)
AVG_TOKENS_IN  = 400
AVG_TOKENS_OUT = 700

# Cost guard thresholds
COST_WARN_EUR    = 5.0   # > 5€  → ask confirmation
COST_REFUSE_EUR  = 50.0  # > 50€ → refuse without --force-expensive


def is_local_backend(teacher_spec: str) -> bool:
    """Retourne True si le backend est ollama: (local, gratuit)."""
    return teacher_spec.startswith("ollama:")


def estimate_cost(
    categories: "list[CategoryTemplate]",
    teacher_spec: str,
    count_override: int | None,
) -> tuple[float, float, int]:
    """Estime le coût total avant génération.

    Returns:
        (cost_usd, cost_eur, n_examples_total)
    """
    if is_local_backend(teacher_spec):
        total = sum(
            len(c.variations) * (count_override or c.count_per_variation)
            for c in categories
        )
        return 0.0, 0.0, total

    model = teacher_spec.split(":", 1)[-1]
    prices = PRICING.get(model)
    if not prices:
        # Unknown model — assume high cost to be safe (gpt-4o rates)
        prices = {"in": 2.50, "out": 10.00}

    total = sum(
        len(c.variations) * (count_override or c.count_per_variation)
        for c in categories
    )

    tokens_in  = total * AVG_TOKENS_IN
    tokens_out = total * AVG_TOKENS_OUT
    cost_usd = (tokens_in / 1_000_000) * prices["in"] + (tokens_out / 1_000_000) * prices["out"]
    cost_eur = cost_usd * EUR_RATE
    return cost_usd, cost_eur, total


def check_budget(
    categories: "list[CategoryTemplate]",
    teacher_spec: str,
    count_override: int | None,
    force_expensive: bool,
) -> None:
    """Vérifie le budget estimé et demande confirmation si nécessaire.

    Lève SystemExit si le coût est refusé.
    """
    cost_usd, cost_eur, n_total = estimate_cost(categories, teacher_spec, count_override)

    if is_local_backend(teacher_spec):
        print(f"  Coût estimé    : 0€ (local — {teacher_spec})")
        print(f"  Total exemples : ~{n_total}")
        return

    print(f"  Coût estimé    : {cost_eur:.2f}€ (~${cost_usd:.2f} USD, {n_total} exemples)")
    print(f"  Teacher        : {teacher_spec}")
    print(f"  Base : {AVG_TOKENS_IN} tok/in + {AVG_TOKENS_OUT} tok/out par exemple (estimé)")

    if cost_eur > COST_REFUSE_EUR and not force_expensive:
        print(
            f"\n  ✗  Coût estimé {cost_eur:.2f}€ dépasse la limite de {COST_REFUSE_EUR}€.",
            file=sys.stderr,
        )
        print(
            f"     Utilisez --force-expensive pour ignorer cette limite.\n"
            f"     Conseil : réduire --count ou cibler une catégorie avec --category.",
            file=sys.stderr,
        )
        sys.exit(1)

    if cost_eur > COST_REFUSE_EUR and force_expensive:
        print(
            f"  ⚠  AVERTISSEMENT : {cost_eur:.2f}€ estimé — limite {COST_REFUSE_EUR}€ ignorée via --force-expensive."
        )

    if cost_eur > COST_WARN_EUR:
        print(f"\n  ⚠  Coût estimé : {cost_eur:.2f}€ (> seuil {COST_WARN_EUR}€)")
        try:
            answer = input(f"  Continuer ? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("y", "yes", "o", "oui"):
            print("  Annulé.")
            sys.exit(0)


# Refusal phrases that indicate the teacher refused to generate content
REFUSAL_PHRASES = [
    "i cannot", "i can't", "i'm not able", "i am not able",
    "i'm unable", "i am unable", "i won't", "i will not",
    "je ne peux pas", "je ne peux pas", "je suis incapable",
    "it would be unethical", "this is unethical", "harmful content",
    "as an ai", "as a language model", "i apologize",
    "je m'excuse", "ce n'est pas approprié",
]

# Minimum quality thresholds
MIN_LENGTH_CHARS   = 300   # < 300 chars is too short to be useful
MIN_THINK_CHARS    = 50    # <think> block must have some content if present
EXPECTED_THINK_TAG = "<think>"


# ---------------------------------------------------------------------------
# Cost tracker
# ---------------------------------------------------------------------------

@dataclass
class CostTracker:
    """Suit les tokens consommés et le coût API estimé."""
    tokens_in:  int   = 0
    tokens_out: int   = 0
    model:      str   = ""

    def add(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in  += tokens_in
        self.tokens_out += tokens_out

    @property
    def estimated_cost_usd(self) -> float:
        prices = PRICING.get(self.model)
        if not prices:
            return 0.0
        cost = (self.tokens_in / 1_000_000) * prices["in"]
        cost += (self.tokens_out / 1_000_000) * prices["out"]
        return cost

    def summary(self) -> str:
        cost = self.estimated_cost_usd
        cost_str = f"${cost:.4f}" if cost > 0 else "N/A (local)"
        return (
            f"tokens in={self.tokens_in:,}  out={self.tokens_out:,}  "
            f"estimated cost={cost_str}"
        )


# ---------------------------------------------------------------------------
# Quality filter
# ---------------------------------------------------------------------------

def check_quality(
    response: str,
    require_think: bool = False,
) -> tuple[bool, str]:
    """Filtre de qualité sur la réponse du teacher.

    Args:
        response: Réponse brute du teacher.
        require_think: Si True, exige un bloc <think>...</think>.

    Returns:
        (passes: bool, reason: str)
    """
    stripped = response.strip()

    if len(stripped) < MIN_LENGTH_CHARS:
        return False, f"Too short ({len(stripped)} chars < {MIN_LENGTH_CHARS})"

    lower = stripped.lower()
    for phrase in REFUSAL_PHRASES:
        if phrase in lower[:300]:  # Refusal usually at the beginning
            return False, f"Detected refusal phrase: {phrase!r}"

    if require_think:
        if EXPECTED_THINK_TAG not in stripped:
            return False, "Missing <think> block (require_think=True)"
        think_match = re.search(r"<think>(.*?)</think>", stripped, re.DOTALL)
        if think_match and len(think_match.group(1).strip()) < MIN_THINK_CHARS:
            return False, "Empty or too short <think> block"

    return True, "ok"


# ---------------------------------------------------------------------------
# Teacher backends
# ---------------------------------------------------------------------------

class TeacherBackend(ABC):
    """Interface commune pour les backends teacher."""

    @abstractmethod
    def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
        think: bool = False,
    ) -> tuple[str, int, int]:
        """Génère une réponse.

        Returns:
            (response_text, tokens_in, tokens_out)
        """

    @property
    @abstractmethod
    def rate_limit_delay(self) -> float:
        """Délai minimum entre requêtes (secondes)."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Nom affiché dans les logs."""


class OllamaBackend(TeacherBackend):
    """Backend Ollama local via /api/chat."""

    def __init__(self, model: str, base_url: str = "http://localhost:11434") -> None:
        self.model    = model
        self.base_url = base_url.rstrip("/")

    @property
    def rate_limit_delay(self) -> float:
        return 0.0  # Local — pas de limite

    @property
    def display_name(self) -> str:
        return f"ollama:{self.model}"

    def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
        think: bool = False,
    ) -> tuple[str, int, int]:
        import urllib.request

        payload = json.dumps({
            "model":    self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "stream":  False,
            "think":   think,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx":     4096,
            },
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read())

        msg        = data.get("message", {})
        thinking   = msg.get("thinking", "")
        content    = msg.get("content", "")
        if thinking:
            content = f"<think>\n{thinking}\n</think>\n\n{content}"
        tokens_in  = data.get("prompt_eval_count", 0)
        tokens_out = data.get("eval_count", 0)
        return content, tokens_in, tokens_out


class OpenAIBackend(TeacherBackend):
    """Backend OpenAI API (gpt-4o, gpt-4o-mini, etc.)."""

    def __init__(self, model: str) -> None:
        self.model  = model
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable not set. "
                "Export it before running: export OPENAI_API_KEY=sk-..."
            )

    @property
    def rate_limit_delay(self) -> float:
        # GPT-4o: ~60 RPM → 1s delay; GPT-4o-mini: ~500 RPM → 0.15s delay
        if "mini" in self.model:
            return 0.15
        return 1.0

    @property
    def display_name(self) -> str:
        return f"openai:{self.model}"

    def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
        think: bool = False,
    ) -> tuple[str, int, int]:
        import urllib.request

        payload = json.dumps({
            "model":       self.model,
            "messages":    [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())

        content    = data["choices"][0]["message"]["content"]
        usage      = data.get("usage", {})
        tokens_in  = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        return content, tokens_in, tokens_out


class AnthropicBackend(TeacherBackend):
    """Backend Anthropic API (claude-sonnet, claude-opus, etc.)."""

    def __init__(self, model: str) -> None:
        self.model    = model
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
            )

    @property
    def rate_limit_delay(self) -> float:
        return 1.2  # ~50 RPM conservative

    @property
    def display_name(self) -> str:
        return f"anthropic:{self.model}"

    def generate(
        self,
        user_prompt: str,
        system_prompt: str,
        *,
        temperature: float = 0.8,
        max_tokens: int = 2048,
        think: bool = False,
    ) -> tuple[str, int, int]:
        import urllib.request

        payload = json.dumps({
            "model":      self.model,
            "max_tokens": max_tokens,
            "system":     system_prompt,
            "messages":   [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         self._api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())

        content    = data["content"][0]["text"]
        usage      = data.get("usage", {})
        tokens_in  = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)
        return content, tokens_in, tokens_out


def make_backend(teacher_spec: str) -> TeacherBackend:
    """Instancie le backend depuis une spec 'provider:model'.

    Examples:
        make_backend("ollama:qwen3:14b")
        make_backend("openai:gpt-4o-mini")
        make_backend("anthropic:claude-sonnet-4-5")
    """
    if ":" not in teacher_spec:
        raise ValueError(
            f"Invalid teacher spec {teacher_spec!r}. "
            "Format: provider:model (e.g. ollama:qwen3:14b, openai:gpt-4o-mini)"
        )
    provider, _, model = teacher_spec.partition(":")
    if provider == "ollama":
        ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        return OllamaBackend(model, base_url=ollama_url)
    if provider == "openai":
        return OpenAIBackend(model)
    if provider == "anthropic":
        return AnthropicBackend(model)
    raise ValueError(
        f"Unknown provider {provider!r}. "
        "Supported: ollama, openai, anthropic"
    )


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------

@dataclass
class CategoryTemplate:
    """Un template de génération pour une catégorie."""
    name:               str
    mitre_id:           str
    mitre_name:         str
    prompt_template:    str
    variations:         list[dict]
    count_per_variation: int
    require_think:      bool = True

    def render(self, variation: dict) -> str:
        """Rend le prompt_template avec les variables de la variation."""
        try:
            return self.prompt_template.format(
                mitre_id=self.mitre_id,
                mitre_name=self.mitre_name,
                **variation,
            )
        except KeyError as e:
            raise ValueError(
                f"Template variable {e} not found in variation {variation}. "
                f"Template vars: {self.prompt_template}"
            ) from e


@dataclass
class GenerationTemplate:
    """Fichier de template YAML complet."""
    agent:          str   # "red" | "blue"
    description:    str
    system_prompt:  str
    categories:     list[CategoryTemplate]


def load_template(path: Path) -> GenerationTemplate:
    """Charge un fichier YAML de template de génération."""
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    categories = []
    for cat in raw.get("categories", []):
        categories.append(CategoryTemplate(
            name=cat["name"],
            mitre_id=cat.get("mitre_id", ""),
            mitre_name=cat.get("mitre_name", ""),
            prompt_template=cat["prompt_template"].strip(),
            variations=cat.get("variations", [{}]),
            count_per_variation=int(cat.get("count_per_variation", 10)),
            require_think=bool(cat.get("require_think", True)),
        ))

    return GenerationTemplate(
        agent=raw.get("agent", "red"),
        description=raw.get("description", ""),
        system_prompt=raw.get("system_prompt", "").strip(),
        categories=categories,
    )


# ---------------------------------------------------------------------------
# Resume / deduplication
# ---------------------------------------------------------------------------

def load_existing_keys(output_path: Path) -> set[str]:
    """Charge les clés déjà générées depuis un fichier JSONL existant.

    La clé est (category, variation_hash) pour éviter les doublons.
    """
    keys: set[str] = set()
    if not output_path.exists():
        return keys
    with output_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ex = json.loads(line)
                meta = ex.get("metadata", {})
                cat  = meta.get("category", "")
                var  = json.dumps(meta.get("variation", {}), sort_keys=True)
                keys.add(f"{cat}::{var}")
            except (json.JSONDecodeError, KeyError):
                pass
    return keys


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

@dataclass
class GenerationStats:
    """Statistiques de génération par catégorie."""
    category:    str
    attempted:   int = 0
    accepted:    int = 0
    rejected:    int = 0
    errors:      int = 0
    elapsed_s:   float = 0.0

    @property
    def rejection_rate(self) -> float:
        total = self.accepted + self.rejected
        return (self.rejected / total) if total > 0 else 0.0


def generate_for_category(
    cat: CategoryTemplate,
    template: GenerationTemplate,
    backend: TeacherBackend,
    output_path: Path,
    cost_tracker: CostTracker,
    *,
    dry_run: bool = False,
    count_override: int | None = None,
    verbose: bool = False,
) -> GenerationStats:
    """Génère tous les exemples pour une catégorie.

    Args:
        cat: Template de la catégorie.
        template: Template global (system prompt, agent).
        backend: Backend teacher.
        output_path: Fichier JSONL de sortie (append).
        cost_tracker: Accumulateur de coût API.
        dry_run: Si True, génère 1 seul exemple et n'écrit pas sur disque.
        count_override: Overrides count_per_variation.
        verbose: Affiche chaque exemple généré.

    Returns:
        GenerationStats pour cette catégorie.
    """
    stats = GenerationStats(category=cat.name)
    count = 1 if dry_run else (count_override or cat.count_per_variation)
    start_total = time.monotonic()

    # Load existing examples to avoid duplicates (resume support)
    existing = load_existing_keys(output_path) if not dry_run else set()

    for variation in cat.variations:
        generated_for_variation = 0
        attempts_for_variation  = 0
        max_attempts = count * 4  # Allow up to 4x attempts per target

        while (
            generated_for_variation < count
            and attempts_for_variation < max_attempts
        ):
            attempts_for_variation += 1
            stats.attempted += 1

            # Build user prompt from template
            try:
                user_prompt = cat.render(variation)
            except ValueError as e:
                print(f"  ✗ Template error: {e}", file=sys.stderr)
                stats.errors += 1
                break

            # Rate limiting
            if backend.rate_limit_delay > 0 and stats.attempted > 1:
                time.sleep(backend.rate_limit_delay)

            # Generate
            t0 = time.monotonic()
            try:
                response, tok_in, tok_out = backend.generate(
                    user_prompt=user_prompt,
                    system_prompt=template.system_prompt,
                    think=cat.require_think,
                )
                elapsed = time.monotonic() - t0
                cost_tracker.add(tok_in, tok_out)
            except Exception as e:
                elapsed = time.monotonic() - t0
                print(
                    f"  ✗ [{cat.name}/{variation}] Generation error after {elapsed:.1f}s: "
                    f"{type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                stats.errors += 1
                time.sleep(2.0)  # Back off on error
                continue

            # Quality filter
            passes, reason = check_quality(response, require_think=cat.require_think)
            if not passes:
                stats.rejected += 1
                if verbose:
                    print(f"  ✗ REJECTED ({reason}): {response[:80]!r}")
                continue

            # Build ChatML example
            example = {
                "messages": [
                    {"role": "system",    "content": template.system_prompt},
                    {"role": "user",      "content": user_prompt},
                    {"role": "assistant", "content": response.strip()},
                ],
                "metadata": {
                    "category":        cat.name,
                    "mitre_id":        cat.mitre_id,
                    "mitre_name":      cat.mitre_name,
                    "teacher":         backend.display_name,
                    "variation":       variation,
                    "tokens_in":       tok_in,
                    "tokens_out":      tok_out,
                    "generation_time_s": round(elapsed, 2),
                    "template_file":   output_path.name,
                    "agent":           template.agent,
                    "generated_at":    datetime.now(UTC).isoformat(),
                },
            }

            if verbose or dry_run:
                print(f"\n{'='*60}")
                print(f"  Category : {cat.name}  |  Variation: {variation}")
                print(f"  Tokens   : {tok_in} in / {tok_out} out  ({elapsed:.1f}s)")
                print(f"  Response preview:")
                preview = response.strip()[:500]
                print(f"    {preview}")
                if dry_run:
                    print(f"\n[dry-run] Would write to: {output_path}")

            if not dry_run:
                with output_path.open("a", encoding="utf-8") as fout:
                    fout.write(json.dumps(example, ensure_ascii=False) + "\n")

            stats.accepted += 1
            generated_for_variation += 1

            # Progress indicator
            var_label = next(iter(variation.values())) if variation else "(default)"
            print(
                f"  [{cat.name}] {var_label[:40]:<40} "
                f"{generated_for_variation}/{count}  "
                f"{tok_out} tok  {elapsed:.1f}s"
            )

            if dry_run:
                break  # One example in dry-run mode

        if attempts_for_variation >= max_attempts and generated_for_variation < count:
            print(
                f"  ⚠ [{cat.name}] Reached max attempts ({max_attempts}) "
                f"for variation — got {generated_for_variation}/{count}",
                file=sys.stderr,
            )

    stats.elapsed_s = time.monotonic() - start_total
    return stats


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def print_summary(
    all_stats: list[GenerationStats],
    cost_tracker: CostTracker,
    teacher: str,
    output_path: Path | None,
    total_elapsed: float,
) -> None:
    """Affiche le résumé final de génération."""
    total_accepted = sum(s.accepted for s in all_stats)
    total_rejected = sum(s.rejected for s in all_stats)
    total_errors   = sum(s.errors   for s in all_stats)
    total_attempted = sum(s.attempted for s in all_stats)

    print("\n" + "=" * 65)
    print("GÉNÉRATION SYNTHÉTIQUE — RÉSUMÉ FINAL")
    print("=" * 65)
    print(f"  Teacher        : {teacher}")
    print(f"  Durée totale   : {total_elapsed / 60:.1f} min ({total_elapsed:.0f}s)")
    print(f"  Sortie         : {output_path or '[dry-run]'}")
    print()
    print(f"  {'Catégorie':<30} {'Générés':>8} {'Rejetés':>8} {'Rejet%':>7} {'Temps':>8}")
    print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*7} {'-'*8}")
    for s in all_stats:
        reject_pct = f"{s.rejection_rate * 100:.0f}%"
        elapsed_str = f"{s.elapsed_s:.0f}s"
        print(
            f"  {s.category:<30} {s.accepted:>8} {s.rejected:>8} "
            f"{reject_pct:>7} {elapsed_str:>8}"
        )
    print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*7} {'-'*8}")
    print(
        f"  {'TOTAL':<30} {total_accepted:>8} {total_rejected:>8} "
        f"{total_rejected/max(total_attempted,1)*100:>6.0f}% "
        f"{total_elapsed:>7.0f}s"
    )
    if total_errors > 0:
        print(f"\n  ⚠  Erreurs d'appel API : {total_errors}")
    print()
    print(f"  Tokens : {cost_tracker.summary()}")
    print("=" * 65)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Génère des données d'entraînement synthétiques via un modèle teacher.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--teacher", required=True,
        help=(
            "Spec teacher : provider:model. "
            "Ex: ollama:qwen3:14b  openai:gpt-4o-mini  anthropic:claude-sonnet-4-5"
        ),
    )
    p.add_argument(
        "--template", required=True,
        help="Chemin vers le fichier YAML de templates (ex: templates/red_team_generation.yaml)",
    )
    p.add_argument(
        "--output", default=None,
        help=(
            "Répertoire ou fichier JSONL de sortie. "
            "Défaut: data/synthetic/{agent}_{timestamp}.jsonl"
        ),
    )
    p.add_argument(
        "--category", default=None,
        help="Génère uniquement cette catégorie (filtrage par name)",
    )
    p.add_argument(
        "--count", type=int, default=None,
        help="Override count_per_variation pour toutes les catégories",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Génère 1 exemple par variation, affiche mais ne sauvegarde pas",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Affiche le contenu complet de chaque exemple généré",
    )
    p.add_argument(
        "--temperature", type=float, default=0.8,
        help="Température de génération (défaut: 0.8)",
    )
    p.add_argument(
        "--local-only", action="store_true",
        help=(
            "Refuse tout backend non-ollama. "
            "Affiche '0€ de coût API' et échoue proprement si un backend API est passé."
        ),
    )
    p.add_argument(
        "--force-expensive", action="store_true",
        help=(
            f"Ignore la limite de {COST_REFUSE_EUR}€ de coût estimé. "
            "À utiliser uniquement pour des générations API explicitement budgétées."
        ),
    )
    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # ── Load template ──────────────────────────────────────────────────────
    template_path = Path(args.template)
    if not template_path.is_absolute():
        # Resolve relative to BASE_DIR first, then CWD
        candidate = BASE_DIR / template_path
        if candidate.exists():
            template_path = candidate
    if not template_path.exists():
        print(f"✗ Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    template = load_template(template_path)
    print(f"✓ Template loaded: {template_path.name}")
    print(f"  Agent       : {template.agent}")
    print(f"  Description : {template.description}")
    print(f"  Categories  : {len(template.categories)}")

    # ── Filter categories ──────────────────────────────────────────────────
    categories = template.categories
    if args.category:
        categories = [c for c in categories if c.name == args.category]
        if not categories:
            available = [c.name for c in template.categories]
            print(
                f"✗ Category {args.category!r} not found. "
                f"Available: {available}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"  Filtering   : category={args.category}")

    # ── Local-only guard ───────────────────────────────────────────────────
    if args.local_only and not is_local_backend(args.teacher):
        print(
            f"✗ --local-only activé mais teacher '{args.teacher}' est un backend API.",
            file=sys.stderr,
        )
        print(
            "  Mode local uniquement — 0€ de coût API.\n"
            "  Utiliser ollama:qwen3:14b ou ollama:qwen3.5-9b avec ce flag.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Init backend ───────────────────────────────────────────────────────
    try:
        backend = make_backend(args.teacher)
    except ValueError as e:
        print(f"✗ Backend error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Teacher backend: {backend.display_name}")
    if args.local_only:
        print("  Mode local uniquement — 0€ de coût API")

    # ── Cost estimate + budget guard ───────────────────────────────────────
    if not args.dry_run:
        check_budget(categories, args.teacher, args.count, args.force_expensive)

    total_to_generate = sum(
        len(c.variations) * (args.count or c.count_per_variation)
        for c in categories
    )
    print(f"\n  Total à générer : ~{total_to_generate} exemples")
    if args.dry_run:
        print("  Mode           : DRY-RUN (1 exemple par variation, pas de sauvegarde)")

    # ── Output path ────────────────────────────────────────────────────────
    output_path: Path | None = None
    if not args.dry_run:
        if args.output:
            out = Path(args.output)
            if out.is_dir() or str(out).endswith("/") or str(out).endswith("\\"):
                out.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                provider_safe = args.teacher.replace(":", "_").replace("/", "_")
                out = out / f"{template.agent}_{args.category or 'all'}_{provider_safe}_{ts}.jsonl"
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
            output_path = out
        else:
            DATA_SYNTH.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            provider_safe = args.teacher.replace(":", "_").replace("/", "_")
            output_path = DATA_SYNTH / (
                f"{template.agent}_{args.category or 'all'}_{provider_safe}_{ts}.jsonl"
            )

        print(f"  Sortie         : {output_path}")

    # ── Check resume ───────────────────────────────────────────────────────
    if output_path and output_path.exists():
        existing_count = sum(1 for _ in output_path.open(encoding="utf-8"))
        print(f"  Reprise        : {existing_count} exemples existants détectés (resume)")

    # ── Run generation ─────────────────────────────────────────────────────
    print("\n" + "─" * 65)
    cost_tracker  = CostTracker(model=args.teacher.split(":", 1)[-1])
    all_stats:    list[GenerationStats] = []
    global_start  = time.monotonic()

    for cat in categories:
        total_for_cat = len(cat.variations) * (args.count or cat.count_per_variation)
        print(
            f"\n▶ {cat.name}  [{cat.mitre_id}]  "
            f"~{total_for_cat} exemples  ({len(cat.variations)} variations × "
            f"{args.count or cat.count_per_variation})"
        )
        stats = generate_for_category(
            cat=cat,
            template=template,
            backend=backend,
            output_path=output_path or Path("/dev/null"),
            cost_tracker=cost_tracker,
            dry_run=args.dry_run,
            count_override=args.count,
            verbose=args.verbose,
        )
        all_stats.append(stats)

    total_elapsed = time.monotonic() - global_start
    print_summary(all_stats, cost_tracker, args.teacher, output_path, total_elapsed)


if __name__ == "__main__":
    main()
