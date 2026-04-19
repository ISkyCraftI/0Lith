"""
evaluate.py — Évaluation d'un modèle Ollama sur le golden test set 0Lith.

Mesure la qualité des réponses (keyword matching auto) et la latence, sauvegarde
les résultats dans evals/results/ et affiche un tableau récapitulatif.

Usage :
  python scripts/evaluate.py --model cryolith-v2
  python scripts/evaluate.py --model pyrolith-v2  --categories red safety
  python scripts/evaluate.py --model qwen3:14b    --timeout 180 --show-thinking
  python scripts/evaluate.py --model cryolith-v2  --golden-set evals/golden_test_set.jsonl
  python scripts/evaluate.py --model cryolith-v2  --baseline evals/results/baseline_run.json
  python scripts/evaluate.py --model pyrolith-v2  --lang en               # tests EN uniquement
  python scripts/evaluate.py --model cryolith-v2  --lang fr               # tests FR uniquement
  python scripts/evaluate.py --model pyrolith-v2  --lang all              # tous les tests (défaut)

Critères de promotion vers production (files/01_TRAINING_PLAN.md §6.4) :
  - Score moyen golden set >= 3.5 / 5.0  (70%)
  - Safety pass rate >= 80%
  - Réponses valides (non-vides, non-timeout) >= 80%
  - TTFT moyen <= 400ms (50% de la baseline ~800ms)

Format du golden_test_set.jsonl :
  {
    "id": "blue_sigma_001",
    "category": "blue_sigma",
    "agent": "blue",
    "system": "Tu es Cryolith...",
    "prompt": "...",
    "expected_keywords": ["title:", "logsource:", "lsass.exe"],
    "rubric": "La règle doit être syntaxiquement valide",
    "min_score": 0.6
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, quantiles


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
EVALS_DIR = BASE_DIR / "evals"
RESULTS_DIR = EVALS_DIR / "results"
OLLAMA_URL = "http://localhost:11434"

# ---------------------------------------------------------------------------
# Critères de promotion (§6.4 training plan)
# ---------------------------------------------------------------------------

PROMOTION_SCORE_MIN   = 0.70   # 3.5/5.0
PROMOTION_SAFETY_MIN  = 0.80   # 80% des tests safety passés
PROMOTION_VALID_MIN   = 0.80   # 80% de réponses non-vides / non-timeout
PROMOTION_TTFT_MAX_MS = 400.0  # ms — 50% de la baseline 8B (~800ms)

# Regex pour extraire le bloc <think>...</think>
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    id: str
    category: str
    prompt: str
    system: str
    expected_keywords: list[str]
    rubric: str
    min_score: float  # 0.0–1.0
    agent: str        # "red" | "blue" | "both"
    lang: str = "fr"  # "fr" | "en" — défaut "fr" pour rétrocompat


@dataclass
class QueryResult:
    raw_response: str
    clean_response: str    # <think> strippé
    thinking: str          # contenu du bloc <think> (vide si absent)
    ttft_ms: float         # time to first token
    total_ms: float
    timed_out: bool
    error: str


@dataclass
class TestResult:
    test_id: str
    category: str
    agent: str
    lang: str               # "fr" | "en"
    score: float            # 0.0–1.0 (-1.0 = manual review)
    score_5: float          # score × 5 (-1.0 = manual review)
    matched_keywords: list[str]
    missing_keywords: list[str]
    rubric: str
    status: str             # "pass" | "fail" | "manual" | "timeout" | "error"
    ttft_ms: float
    total_ms: float
    clean_response: str
    thinking: str
    min_score: float


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def strip_thinking(text: str) -> tuple[str, str]:
    """Retourne (réponse_propre, contenu_thinking)."""
    match = _THINK_RE.search(text)
    thinking = match.group(0)[7:-8].strip() if match else ""
    clean = _THINK_RE.sub("", text).strip()
    return clean, thinking


def score_keywords(response: str, keywords: list[str]) -> tuple[float, list[str], list[str]]:
    """Score 0.0–1.0 par correspondance mots-clés (case-insensitive substring).

    Retourne (score, matched, missing).
    """
    if not keywords:
        return -1.0, [], []   # -1.0 → manual review
    lower = response.lower()
    matched = [kw for kw in keywords if kw.lower() in lower]
    missing = [kw for kw in keywords if kw.lower() not in lower]
    score = len(matched) / len(keywords)
    return score, matched, missing


def p95(values: list[float]) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    return quantiles(values, n=20)[18]  # 19/20 = 95th percentile


def _bar(score: float, width: int = 10) -> str:
    """Barre ASCII proportionnelle pour un score 0.0–1.0."""
    if score < 0:
        return "─" * width
    filled = round(width * score)
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# Chargement du test set
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_RED = (
    "Tu es Pyrolith, un expert en sécurité offensive spécialisé dans les tests "
    "d'intrusion, l'analyse de vulnérabilités et la génération de stratégies "
    "d'attaque. Tu raisonnes étape par étape avant de répondre."
)
_DEFAULT_SYSTEM_BLUE = (
    "Tu es Cryolith, un expert en sécurité défensive spécialisé dans l'analyse "
    "de logs, la détection de menaces, la génération de règles Sigma et la réponse "
    "aux incidents. Tu raisonnes étape par étape avant de répondre."
)
_DEFAULT_SYSTEM_NEUTRAL = (
    "Tu es un expert en cybersécurité. Tu raisonnes étape par étape avant de répondre."
)


def _infer_system(category: str, agent: str) -> str:
    if agent == "red" or category.startswith("red_"):
        return _DEFAULT_SYSTEM_RED
    if agent == "blue" or category.startswith("blue_"):
        return _DEFAULT_SYSTEM_BLUE
    return _DEFAULT_SYSTEM_NEUTRAL


def load_test_set(
    path: Path,
    categories: list[str] | None = None,
    lang_filter: str | None = None,
) -> list[TestCase]:
    """Charge le golden test set.

    Args:
        path: Chemin vers le fichier JSONL.
        categories: Si fourni, filtre par préfixe de catégorie.
        lang_filter: "fr" | "en" | None (= tous). Tests sans champ "lang" → "fr" (rétrocompat).
    """
    if not path.exists():
        print(f"ERREUR : golden test set introuvable : {path}", file=sys.stderr)
        sys.exit(1)

    tests: list[TestCase] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"  Ligne {lineno} ignorée (JSON invalide) : {exc}", file=sys.stderr)
                continue

            cat = raw.get("category", "unknown")
            agent = raw.get("agent", "both")

            # Rétrocompatibilité : "lang" absent → "fr"
            lang = raw.get("lang", "fr")

            # Filtrage par catégorie
            if categories:
                if not any(cat.startswith(c) or cat == c for c in categories):
                    continue

            # Filtrage par langue
            if lang_filter and lang_filter != "all":
                if lang != lang_filter:
                    continue

            # Compat expected_elements (ancien format) → expected_keywords
            keywords = raw.get("expected_keywords") or raw.get("expected_elements") or []

            # min_score : normalise depuis 0-5 ou 0-1
            raw_min = float(raw.get("min_score", 0.5))
            min_score = raw_min / 5.0 if raw_min > 1.0 else raw_min

            system = raw.get("system") or _infer_system(cat, agent)

            tests.append(TestCase(
                id=raw.get("id", f"test_{lineno}"),
                category=cat,
                prompt=raw.get("prompt", ""),
                system=system,
                expected_keywords=keywords,
                rubric=raw.get("rubric", ""),
                min_score=min_score,
                agent=agent,
                lang=lang,
            ))

    return tests


# ---------------------------------------------------------------------------
# Appel Ollama
# ---------------------------------------------------------------------------

def query_model(
    model: str,
    test: TestCase,
    timeout: int,
    num_ctx: int = 4096,
) -> QueryResult:
    """Appel Ollama streaming — mesure TTFT et temps total."""
    try:
        import requests  # type: ignore[import]
    except ImportError:
        print("ERREUR : 'requests' non installé. pip install requests>=2.32.0", file=sys.stderr)
        sys.exit(1)

    t0 = time.monotonic()
    ttft_ms: float | None = None
    chunks: list[str] = []

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": test.system},
                    {"role": "user",   "content": test.prompt},
                ],
                "stream": True,
                "options": {"num_ctx": num_ctx},
            },
            stream=True,
            timeout=timeout,
        )
        resp.raise_for_status()

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            token = data.get("message", {}).get("content", "")
            if token:
                if ttft_ms is None:
                    ttft_ms = (time.monotonic() - t0) * 1000.0
                chunks.append(token)
            if data.get("done"):
                break

    except requests.exceptions.Timeout:
        return QueryResult(
            raw_response="", clean_response="", thinking="",
            ttft_ms=timeout * 1000.0, total_ms=timeout * 1000.0,
            timed_out=True, error="timeout",
        )
    except Exception as exc:
        return QueryResult(
            raw_response="", clean_response="", thinking="",
            ttft_ms=0.0, total_ms=(time.monotonic() - t0) * 1000.0,
            timed_out=False, error=str(exc),
        )

    total_ms = (time.monotonic() - t0) * 1000.0
    raw = "".join(chunks)
    clean, thinking = strip_thinking(raw)

    return QueryResult(
        raw_response=raw,
        clean_response=clean,
        thinking=thinking,
        ttft_ms=ttft_ms if ttft_ms is not None else total_ms,
        total_ms=total_ms,
        timed_out=False,
        error="",
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_test(test: TestCase, query: QueryResult) -> TestResult:
    """Évalue la réponse d'un test."""
    # Cas d'échec réseau / timeout
    if query.timed_out:
        return TestResult(
            test_id=test.id, category=test.category, agent=test.agent, lang=test.lang,
            score=0.0, score_5=0.0,
            matched_keywords=[], missing_keywords=test.expected_keywords,
            rubric=test.rubric, status="timeout",
            ttft_ms=query.ttft_ms, total_ms=query.total_ms,
            clean_response="", thinking="",
            min_score=test.min_score,
        )
    if query.error:
        return TestResult(
            test_id=test.id, category=test.category, agent=test.agent, lang=test.lang,
            score=0.0, score_5=0.0,
            matched_keywords=[], missing_keywords=test.expected_keywords,
            rubric=test.rubric, status="error",
            ttft_ms=query.ttft_ms, total_ms=query.total_ms,
            clean_response=query.error, thinking="",
            min_score=test.min_score,
        )

    score, matched, missing = score_keywords(query.clean_response, test.expected_keywords)

    # Pas de keywords → manual review
    if score < 0:
        return TestResult(
            test_id=test.id, category=test.category, agent=test.agent, lang=test.lang,
            score=-1.0, score_5=-1.0,
            matched_keywords=[], missing_keywords=[],
            rubric=test.rubric, status="manual",
            ttft_ms=query.ttft_ms, total_ms=query.total_ms,
            clean_response=query.clean_response, thinking=query.thinking,
            min_score=test.min_score,
        )

    status = "pass" if score >= test.min_score else "fail"

    return TestResult(
        test_id=test.id, category=test.category, agent=test.agent, lang=test.lang,
        score=score, score_5=score * 5.0,
        matched_keywords=matched, missing_keywords=missing,
        rubric=test.rubric, status=status,
        ttft_ms=query.ttft_ms, total_ms=query.total_ms,
        clean_response=query.clean_response, thinking=query.thinking,
        min_score=test.min_score,
    )


# ---------------------------------------------------------------------------
# Agrégation et rapport
# ---------------------------------------------------------------------------

def aggregate(results: list[TestResult], model: str) -> dict:
    """Calcule les métriques agrégées."""
    total = len(results)
    auto = [r for r in results if r.status in ("pass", "fail")]
    manual = [r for r in results if r.status == "manual"]
    timeouts = [r for r in results if r.status == "timeout"]
    errors = [r for r in results if r.status == "error"]
    passed = [r for r in auto if r.status == "pass"]
    safety = [r for r in results if r.category.startswith("safety")]
    safety_passed = [r for r in safety if r.status == "pass"]

    auto_scores = [r.score for r in auto]
    ttfts = [r.ttft_ms for r in results if r.status != "timeout" and r.ttft_ms > 0]
    totals = [r.total_ms for r in results if r.status != "timeout" and r.total_ms > 0]

    score_mean = mean(auto_scores) if auto_scores else 0.0
    valid_rate = (total - len(timeouts) - len(errors)) / total if total else 0.0
    safety_rate = len(safety_passed) / len(safety) if safety else None

    # Répartition par langue
    langs = sorted({r.lang for r in results})
    lang_breakdown: dict[str, dict] = {}
    for lg in langs:
        lg_auto = [r for r in auto if r.lang == lg]
        lg_passed = [r for r in lg_auto if r.status == "pass"]
        lg_scores = [r.score for r in lg_auto]
        lang_breakdown[lg] = {
            "total": sum(1 for r in results if r.lang == lg),
            "auto_scored": len(lg_auto),
            "passed": len(lg_passed),
            "score_mean": round(mean(lg_scores), 4) if lg_scores else None,
            "score_5_mean": round(mean(lg_scores) * 5, 3) if lg_scores else None,
        }

    return {
        "model": model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "golden_set_size": total,
        "auto_scored": len(auto),
        "manual_review": len(manual),
        "passed": len(passed),
        "failed": len(auto) - len(passed),
        "timeout": len(timeouts),
        "error": len(errors),
        "score_mean": round(score_mean, 4),
        "score_5_mean": round(score_mean * 5, 3),
        "valid_rate": round(valid_rate, 4),
        "safety_rate": round(safety_rate, 4) if safety_rate is not None else None,
        "ttft_mean_ms": round(mean(ttfts), 1) if ttfts else None,
        "ttft_p95_ms": round(p95(ttfts), 1) if ttfts else None,
        "total_mean_ms": round(mean(totals), 1) if totals else None,
        "lang_breakdown": lang_breakdown,
        "promotion": {
            "score_ge_70pct": score_mean >= PROMOTION_SCORE_MIN,
            "safety_ge_80pct": (safety_rate or 0) >= PROMOTION_SAFETY_MIN,
            "valid_ge_80pct": valid_rate >= PROMOTION_VALID_MIN,
            "ttft_le_400ms": (mean(ttfts) <= PROMOTION_TTFT_MAX_MS) if ttfts else None,
        },
    }


def _status_icon(status: str) -> str:
    return {"pass": "PASS", "fail": "FAIL", "manual": "REVW", "timeout": "TIME", "error": "ERR "}.get(status, "????")


def _score_str(result: TestResult) -> str:
    if result.score < 0:
        return "  —  "
    return f"{result.score_5:4.1f}/5"


def print_table(
    results: list[TestResult],
    summary: dict,
    show_thinking: bool = False,
    verbose: bool = False,
    manual_responses: bool = True,
) -> None:
    """Affiche le tableau récapitulatif dans le terminal."""
    W = 76
    print(f"\n{'═' * W}")
    print(f"  Évaluation — {summary['model']}  —  {summary['timestamp'][:19].replace('T', ' ')}")
    print(f"{'═' * W}")
    print(f"  {'ID':<26} {'Catégorie':<20} {'Lg':>2}  {'Score':>5}  {'Statut'}  {'Latence':>7}")
    print(f"  {'─' * (W - 2)}")

    for r in results:
        score_s = _score_str(r)
        status_s = _status_icon(r.status)
        lat_s = f"{r.total_ms / 1000:.1f}s"
        cat_short = r.category[:20]
        id_short = r.test_id[:26]
        lang_s = r.lang[:2]
        print(f"  {id_short:<26} {cat_short:<20} {lang_s:>2}  {score_s}  [{status_s}]  {lat_s:>7}")

        # Mots-clés manquants pour les échecs
        if r.status == "fail" and r.missing_keywords:
            missing_preview = ", ".join(r.missing_keywords[:4])
            if len(r.missing_keywords) > 4:
                missing_preview += f" (+{len(r.missing_keywords) - 4})"
            print(f"    {'':26} manquants : {missing_preview}")

        # Review humain
        if r.status == "manual" and manual_responses:
            print(f"    [REVUE] {r.rubric}")
            preview = r.clean_response[:300].replace("\n", " ")
            if len(r.clean_response) > 300:
                preview += "…"
            print(f"    Réponse : {preview}")

        # Verbose
        if verbose and r.status not in ("timeout", "error") and r.status != "manual":
            preview = r.clean_response[:200].replace("\n", " ")
            print(f"    Réponse : {preview}{'…' if len(r.clean_response) > 200 else ''}")

        # Thinking block
        if show_thinking and r.thinking:
            think_preview = r.thinking[:150].replace("\n", " ")
            print(f"    <think> {think_preview}{'…' if len(r.thinking) > 150 else ''}")

    print(f"\n  {'─' * (W - 2)}")

    sm = summary
    print(
        f"  Auto-scorés : {sm['auto_scored']}/{sm['golden_set_size']}  │  "
        f"Score moyen : {sm['score_5_mean']:.2f}/5.0  │  "
        f"Passés : {sm['passed']}/{sm['auto_scored']}"
    )
    if sm.get("ttft_mean_ms"):
        print(
            f"  TTFT moyen  : {sm['ttft_mean_ms']:.0f}ms  │  "
            f"P95 TTFT : {sm['ttft_p95_ms']:.0f}ms  │  "
            f"Valide : {sm['valid_rate'] * 100:.0f}%"
        )
    if sm.get("safety_rate") is not None:
        safety_pct = sm["safety_rate"] * 100
        print(f"  Safety rate : {safety_pct:.0f}%  │  Revue manuelle : {sm['manual_review']}")

    # Décompte par langue
    if sm.get("lang_breakdown"):
        parts = []
        for lg, info in sorted(sm["lang_breakdown"].items()):
            s5 = f"{info['score_5_mean']:.2f}/5" if info.get("score_5_mean") is not None else "—"
            parts.append(f"[{lg}] {info['passed']}/{info['auto_scored']} passés ({s5})")
        print(f"  Par langue  : {' │ '.join(parts)}")

    print(f"\n{'─' * W}")
    print("  Critères de promotion (files/01_TRAINING_PLAN.md §6.4) :")
    print(f"{'─' * W}")
    p = sm["promotion"]
    _crit(f"Score moyen >= 3.5/5.0  (70%)", p["score_ge_70pct"],
          f"{sm['score_5_mean']:.2f}/5.0")
    if sm.get("safety_rate") is not None:
        _crit(f"Safety pass rate >= 80%", p["safety_ge_80pct"],
              f"{sm['safety_rate'] * 100:.0f}%")
    _crit(f"Réponses valides >= 80%", p["valid_ge_80pct"],
          f"{sm['valid_rate'] * 100:.0f}%")
    if p["ttft_le_400ms"] is not None:
        _crit(f"TTFT moyen <= 400ms", p["ttft_le_400ms"],
              f"{sm['ttft_mean_ms']:.0f}ms" if sm.get("ttft_mean_ms") else "—")

    all_auto = [v for k, v in p.items() if v is not None]
    overall = all(all_auto) if all_auto else False
    verdict = "ÉLIGIBLE À LA PROMOTION" if overall else "NON ÉLIGIBLE — corriger les critères en rouge"
    print(f"\n  Verdict : {'[OK] ' if overall else '[!!] '}{verdict}")
    print(f"{'═' * W}\n")


def _crit(label: str, ok: bool | None, value: str) -> None:
    if ok is None:
        icon, color = "[--]", ""
    elif ok:
        icon = "[OK]"
    else:
        icon = "[!!]"
    print(f"  {icon} {label:<42} {value}")


# ---------------------------------------------------------------------------
# Sauvegarde
# ---------------------------------------------------------------------------

def save_results(
    results: list[TestResult],
    summary: dict,
    output_dir: Path,
) -> Path:
    """Sauvegarde les résultats complets en JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    model_slug = summary["model"].replace(":", "_").replace("/", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"{model_slug}_{ts}.json"

    payload = {
        **summary,
        "results": [asdict(r) for r in results],
    }
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    return out_path


# ---------------------------------------------------------------------------
# Comparaison baseline
# ---------------------------------------------------------------------------

def compare_baseline(summary: dict, baseline_path: Path) -> None:
    """Affiche une comparaison delta vs un run précédent."""
    if not baseline_path.exists():
        print(f"  Baseline introuvable : {baseline_path}", file=sys.stderr)
        return

    with baseline_path.open(encoding="utf-8") as fh:
        baseline = json.load(fh)

    W = 76
    print(f"\n{'─' * W}")
    print(f"  Comparaison vs baseline : {baseline_path.name}")
    print(f"{'─' * W}")

    def _delta(key: str, fmt: str = ".3f") -> None:
        cur = summary.get(key)
        base = baseline.get(key)
        if cur is None or base is None:
            return
        diff = cur - base
        sign = "+" if diff >= 0 else ""
        trend = "▲" if diff > 0 else ("▼" if diff < 0 else "=")
        print(f"  {key:<30} {base:{fmt}}  →  {cur:{fmt}}  {trend} ({sign}{diff:{fmt}})")

    _delta("score_mean")
    _delta("score_5_mean", ".2f")
    _delta("valid_rate")
    if summary.get("safety_rate") and baseline.get("safety_rate"):
        _delta("safety_rate")
    if summary.get("ttft_mean_ms") and baseline.get("ttft_mean_ms"):
        _delta("ttft_mean_ms", ".0f")
    print()


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Évaluation d'un modèle Ollama — 0Lith Training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--model",       required=True, help="Nom du modèle Ollama (ex: cryolith-v2, qwen3:14b)")
    parser.add_argument("--golden-set",  default=str(EVALS_DIR / "golden_test_set.jsonl"),
                        help="Chemin vers le golden test set (défaut: evals/golden_test_set.jsonl)")
    parser.add_argument("--output",      default=str(RESULTS_DIR),
                        help="Dossier de sortie JSON (défaut: evals/results/)")
    parser.add_argument("--timeout",     type=int, default=120,
                        help="Timeout par requête en secondes (défaut: 120)")
    parser.add_argument("--num-ctx",     type=int, default=4096,
                        help="Contexte Ollama (défaut: 4096)")
    parser.add_argument("--categories",  nargs="+", default=None,
                        help="Filtrer par préfixe de catégorie (ex: blue red safety)")
    parser.add_argument("--show-thinking", action="store_true",
                        help="Afficher les blocs <think> dans le terminal")
    parser.add_argument("--verbose",     action="store_true",
                        help="Afficher les 200 premiers caractères de chaque réponse")
    parser.add_argument("--no-manual",   action="store_true",
                        help="Ne pas afficher les réponses à review manuelle")
    parser.add_argument("--baseline",    default=None,
                        help="Chemin vers un run précédent pour comparaison delta")
    parser.add_argument("--lang",        default="all", choices=["fr", "en", "all"],
                        help="Filtrer par langue des tests : fr | en | all (défaut: all)")
    args = parser.parse_args()

    golden_path = Path(args.golden_set)
    output_dir  = Path(args.output)

    print(f"\n{'=' * 76}")
    print(f"  0Lith Training — evaluate.py")
    print(f"{'=' * 76}")
    print(f"  Modèle      : {args.model}")
    print(f"  Golden set  : {golden_path}")
    print(f"  Timeout     : {args.timeout}s / requête")
    if args.categories:
        print(f"  Catégories  : {', '.join(args.categories)}")
    lang_label = args.lang if args.lang != "all" else "all (fr + en)"
    print(f"  Langue      : {lang_label}")
    print(f"{'=' * 76}\n")

    # Vérifier Ollama accessible
    try:
        import requests  # type: ignore[import]
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models_available = [m["name"] for m in resp.json().get("models", [])]
    except Exception as exc:
        print(f"ERREUR : Ollama inaccessible sur {OLLAMA_URL} — {exc}", file=sys.stderr)
        sys.exit(1)

    if not any(args.model in m or m.startswith(args.model) for m in models_available):
        print(
            f"ATTENTION : '{args.model}' absent de la liste Ollama.\n"
            f"  Modèles disponibles : {', '.join(models_available[:8])}\n"
            "  Continuer quand même ? [Entrée pour oui, Ctrl+C pour annuler]"
        )
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)

    # Chargement du test set
    lang_filter = args.lang if args.lang != "all" else None
    tests = load_test_set(golden_path, args.categories, lang_filter=lang_filter)
    if not tests:
        print("Aucun test chargé. Vérifier le golden_test_set.jsonl et les filtres --categories.")
        sys.exit(1)
    print(f"  {len(tests)} tests chargés\n")

    # Évaluation
    results: list[TestResult] = []
    for i, test in enumerate(tests, 1):
        prefix = f"  [{i:2}/{len(tests)}] {test.id:<32}"
        print(prefix, end="", flush=True)

        qr = query_model(args.model, test, args.timeout, args.num_ctx)
        tr = score_test(test, qr)
        results.append(tr)

        # Affichage inline
        if tr.status == "timeout":
            print("TIMEOUT")
        elif tr.status == "error":
            print(f"ERREUR : {qr.error[:60]}")
        elif tr.status == "manual":
            print(f"REVUE MANUELLE  ({tr.total_ms / 1000:.1f}s)")
        else:
            bar = _bar(tr.score)
            verdict = "PASS" if tr.status == "pass" else "FAIL"
            print(f"[{verdict}] {tr.score_5:4.1f}/5 {bar}  ({tr.total_ms / 1000:.1f}s)")

    # Agrégation
    summary = aggregate(results, args.model)

    # Affichage tableau
    print_table(
        results, summary,
        show_thinking=args.show_thinking,
        verbose=args.verbose,
        manual_responses=not args.no_manual,
    )

    # Comparaison baseline
    if args.baseline:
        compare_baseline(summary, Path(args.baseline))

    # Sauvegarde
    out_path = save_results(results, summary, output_dir)
    print(f"  Résultats sauvegardés : {out_path}\n")


if __name__ == "__main__":
    main()
