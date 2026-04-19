"""
download_datasets.py — Télécharge, inspecte et normalise les datasets cybersec.

Télécharge 4 datasets HuggingFace vers data/raw/, affiche les statistiques,
splitte CyberLLMInstruct par agent (red/blue), puis appelle normalize_dataset.py
pour chaque. Termine par un gap analysis vs la taxonomie cible.

Usage :
  python scripts/download_datasets.py                         # Tout télécharger
  python scripts/download_datasets.py --datasets fenrir nist  # Datasets spécifiques
  python scripts/download_datasets.py --skip-download         # Réutilise data/raw/ existants
  python scripts/download_datasets.py --skip-normalize        # Inspecte sans normaliser
  python scripts/download_datasets.py --max-examples 10000    # Limite (utile pour NIST 530K)
  python scripts/download_datasets.py --gap-only              # Gap analysis seul

Notes :
  - CyberLLMInstruct HF ID : à vérifier sur https://huggingface.co/datasets?search=CyberLLMInstruct
    Référence : arXiv:2503.09334 "CyberLLMInstruct: A New Dataset for Analysing Safety
    of Fine-Tuned LLMs Using Cyber Security Data"
  - NIST : 530K exemples — utiliser --max-examples pour limiter en dev
  - Authentification HF : `huggingface-cli login` si dataset privé/gated
"""

from __future__ import annotations

import argparse
import functools
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Chemins de base (relatifs à ce script → 0lith-training/)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROCESSED = BASE_DIR / "data" / "processed"
NORMALIZE_SCRIPT = BASE_DIR / "scripts" / "normalize_dataset.py"


# ---------------------------------------------------------------------------
# Configs des datasets
# ---------------------------------------------------------------------------

@dataclass
class DatasetConfig:
    hf_id: str                     # Identifiant HuggingFace
    slug: str                      # Nom de fichier local (sans extension)
    agents: list[str]              # ["red"], ["blue"] ou ["red", "blue"]
    format_hint: str               # Format pour normalize_dataset.py
    split: str = "train"
    expected_size: int = 0         # Taille attendue (pour vérification)
    note: str = ""                 # Note de documentation


DATASET_CONFIGS: dict[str, DatasetConfig] = {
    "fenrir": DatasetConfig(
        hf_id="AlicanKiraz0/Cybersecurity-Dataset-Fenrir-v2.0",
        slug="fenrir_v2",
        agents=["blue"],
        format_hint="cybersec",
        expected_size=83_920,
        note="Apache 2.0 — OWASP/MITRE/NIST mapping, MinHash dédupliqué",
    ),
    "cyberlllminstruct": DatasetConfig(
        # arXiv:2503.09334 — vérifier l'ID exact sur HuggingFace si téléchargement échoue
        hf_id="CyberSafetyAI/CyberLLMInstruct",
        slug="cyberlllminstruct",
        agents=["red", "blue"],    # Split par catégorie — voir _split_by_agent()
        format_hint="cybersec",
        expected_size=54_928,
        note="arXiv:2503.09334 — Malware, phishing, zero-day — split red/blue par mots-clés",
    ),
    "trendyol": DatasetConfig(
        hf_id="Trendyol/Trendyol-Cybersecurity-Instruction-Tuning-Dataset",
        slug="trendyol_cybersec",
        agents=["blue"],
        format_hint="cybersec",
        expected_size=53_202,
        note="Apache 2.0 — 200+ topics, ATT&CK/NIST mappés",
    ),
    "nist": DatasetConfig(
        hf_id="ethanolivertroy/nist-cybersecurity-training",
        slug="nist_cybersec",
        agents=["blue"],
        format_hint="cybersec",
        expected_size=530_912,
        note="CC0 — 596 publications NIST chunkées — recommandé : --max-examples 50000",
    ),
}


# ---------------------------------------------------------------------------
# Taxonomie par agent — pour classification et gap analysis
# (Source : files/01_TRAINING_PLAN.md §4.2)
# ---------------------------------------------------------------------------

RED_TAXONOMY: dict[str, list[str]] = {
    "recon": [
        "reconnaissance", "enumeration", "nmap", "osint", "dns", "scan",
        "fingerprint", "footprint", "port scan", "service discovery", "banner grab",
    ],
    "exploitation": [
        "exploit", "cve-", "vulnerability", "remote code execution", "rce",
        "buffer overflow", "zero-day", "0day", "use-after-free", "heap spray",
        "integer overflow", "memory corruption",
    ],
    "post_exploitation": [
        "lateral movement", "privilege escalation", "persistence", "pivoting",
        "pass-the-hash", "mimikatz", "kerberoast", "golden ticket", "silver ticket",
        "token impersonation", "dcsync",
    ],
    "payload": [
        "payload", "shellcode", "reverse shell", "bind shell", "obfuscat",
        "encoder", "meterpreter", "stager", "stageless", "cobalt strike",
        "c2 framework", "command and control",
    ],
    "web_attacks": [
        "sql inject", "sqli", "xss", "cross-site script", "ssrf", "idor",
        "csrf", "lfi", "rfi", "path traversal", "file inclusion", "owasp",
        "web shell", "deserialization",
    ],
    "social_engineering": [
        "phishing", "spear phishing", "pretexting", "vishing", "smishing",
        "social engineer", "credential harvest", "typosquat",
    ],
    "code_review": [
        "vulnerable code", "code review", "source code audit", "sast",
        "secure coding", "code vulnerab", "insecure function", "static analysis",
    ],
    "ctf": [
        "ctf", "capture the flag", "pwn", "binary exploit",
        "reverse engineer", "flag{", "challenge", "writeup",
    ],
}

BLUE_TAXONOMY: dict[str, list[str]] = {
    "log_analysis": [
        "log analysis", "syslog", "event log", "windows event", "apache log",
        "nginx log", "splunk", "siem", "elk stack", "suricata", "zeek",
        "audit log", "log correlation",
    ],
    "anomaly_detection": [
        "anomaly detection", "anomaly", "baseline", "behavioral analysis",
        "deviation", "outlier", "ueba", "user behavior", "statistical model",
    ],
    "sigma_rules": [
        "sigma", "detection rule", "logsource", "sigma yaml",
        "detection:", "condition:", "sigma rule", "rule author",
    ],
    "incident_response": [
        "incident response", "triage", "containment", "eradication",
        "recovery", "playbook", "runbook", "ir plan", "post-incident",
    ],
    "threat_hunting": [
        "threat hunting", "threat hunt", "hypothesis", "ioc", "ioa",
        "indicator of compromise", "hunting query", "threat intelligence",
        "proactive detection",
    ],
    "malware_analysis": [
        "malware analysis", "malware", "sandbox", "dynamic analysis",
        "decompile", "disassemble", "yara", "ioc extraction",
        "strings analysis", "behavior analysis",
    ],
    "hardening": [
        "hardening", "remediation", "configuration review", "cis benchmark",
        "patch management", "vulnerability management", "secure baseline",
        "compliance", "security policy",
    ],
    "forensics": [
        "forensic", "timeline analysis", "memory forensic", "disk image",
        "volatility", "autopsy", "artifact", "chain of custody",
        "memory dump",
    ],
}

RED_CATEGORY_LABELS: dict[str, str] = {
    "recon":            "Reconnaissance & énumération",
    "exploitation":     "Exploitation CVE",
    "post_exploitation":"Post-exploitation",
    "payload":          "Génération de payloads",
    "web_attacks":      "Web application attacks",
    "social_engineering":"Social engineering",
    "code_review":      "Code review offensif",
    "ctf":              "CTF problem solving",
}
BLUE_CATEGORY_LABELS: dict[str, str] = {
    "log_analysis":     "Analyse de logs",
    "anomaly_detection":"Détection d'anomalies",
    "sigma_rules":      "Génération de règles Sigma",
    "incident_response":"Incident response",
    "threat_hunting":   "Threat hunting",
    "malware_analysis": "Analyse de malware",
    "hardening":        "Hardening & remédiation",
    "forensics":        "Forensics",
}

# Cible minimum par catégorie pour un SFT de qualité (sur 8K-12K total)
MIN_EXAMPLES_PER_CATEGORY = 1_000


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(max_attempts: int = 3, backoff_base: float = 2.0):
    """Réessaie une fonction sur exception avec backoff exponentiel."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        wait = backoff_base ** (attempt - 1)
                        print(
                            f"  [retry {attempt}/{max_attempts}] Erreur : {exc}\n"
                            f"  Nouvelle tentative dans {wait:.0f}s...",
                            file=sys.stderr,
                        )
                        time.sleep(wait)
            raise RuntimeError(
                f"Échec après {max_attempts} tentatives : {last_exc}"
            ) from last_exc
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Classification par mots-clés
# ---------------------------------------------------------------------------

def _score_text(text: str, taxonomy: dict[str, list[str]]) -> dict[str, int]:
    """Compte les correspondances de mots-clés par catégorie."""
    lower = text.lower()
    return {cat: sum(1 for kw in kws if kw in lower) for cat, kws in taxonomy.items()}


def classify_category(text: str) -> tuple[str, str]:
    """Retourne (agent, category) en choisissant la catégorie avec le plus de matches.

    agent   : "red" ou "blue"
    category: clé de RED_TAXONOMY ou BLUE_TAXONOMY
    """
    red_scores = _score_text(text, RED_TAXONOMY)
    blue_scores = _score_text(text, BLUE_TAXONOMY)

    best_red_cat = max(red_scores, key=red_scores.__getitem__)
    best_blue_cat = max(blue_scores, key=blue_scores.__getitem__)
    best_red_score = red_scores[best_red_cat]
    best_blue_score = blue_scores[best_blue_cat]

    if best_red_score == 0 and best_blue_score == 0:
        return "blue", "hardening"  # Défaut : hardening (catégorie la plus générique)

    if best_red_score > best_blue_score:
        return "red", best_red_cat
    return "blue", best_blue_cat


def classify_agent(text: str) -> str:
    """Retourne "red", "blue" ou "both" pour le routing d'un exemple CyberLLMInstruct."""
    red_scores = _score_text(text, RED_TAXONOMY)
    blue_scores = _score_text(text, BLUE_TAXONOMY)
    total_red = sum(red_scores.values())
    total_blue = sum(blue_scores.values())

    if total_red == 0 and total_blue == 0:
        return "blue"
    if total_red == 0:
        return "blue"
    if total_blue == 0:
        return "red"

    ratio = total_red / (total_red + total_blue)
    if ratio >= 0.6:
        return "red"
    if ratio <= 0.4:
        return "blue"
    return "both"  # Ambigu → les deux agents bénéficient de cet exemple


def _extract_text_from_row(row: dict) -> str:
    """Extrait le texte principal d'une ligne brute pour classification."""
    for field in ("instruction", "question", "prompt", "input", "text", "output", "answer"):
        val = str(row.get(field) or "")
        if val.strip():
            return val
    return " ".join(str(v) for v in row.values() if v)


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------

@retry(max_attempts=3, backoff_base=2.0)
def _hf_download(
    hf_id: str,
    split: str,
    max_examples: int | None,
) -> tuple[list[dict], list[str]]:
    """Télécharge un dataset HuggingFace, retourne (rows, column_names)."""
    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "La librairie 'datasets' n'est pas installée.\n"
            "  pip install datasets>=3.3.0"
        )

    ds = load_dataset(hf_id, split=split, trust_remote_code=False)
    columns = list(ds.column_names) if hasattr(ds, "column_names") else []

    if max_examples is not None:
        ds = ds.select(range(min(max_examples, len(ds))))

    rows = [dict(row) for row in ds]
    return rows, columns


def download_dataset(
    cfg: DatasetConfig,
    max_examples: int | None = None,
) -> tuple[Path, list[str]]:
    """Télécharge le dataset et le sauvegarde en JSONL. Retourne (path, columns)."""
    raw_path = DATA_RAW / f"{cfg.slug}.jsonl"
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    print(f"  Téléchargement : {cfg.hf_id}")
    if cfg.note:
        print(f"  Note           : {cfg.note}")
    if max_examples:
        print(f"  Limite         : {max_examples} exemples")

    rows, columns = _hf_download(cfg.hf_id, cfg.split, max_examples)

    with raw_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    size_mb = raw_path.stat().st_size / 1_048_576
    print(f"  Sauvegardé     : {raw_path} ({len(rows):,} exemples, {size_mb:.1f} MB)")

    if cfg.expected_size and len(rows) < cfg.expected_size * 0.9:
        print(
            f"  ATTENTION : {len(rows):,} exemples reçus vs {cfg.expected_size:,} attendus "
            f"— dataset potentiellement incomplet ou limité par --max-examples",
            file=sys.stderr,
        )

    return raw_path, columns


def load_raw(raw_path: Path) -> tuple[list[dict], list[str]]:
    """Charge un JSONL existant depuis data/raw/."""
    rows = []
    columns: set[str] = set()
    with raw_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                rows.append(row)
                columns.update(row.keys())
            except json.JSONDecodeError:
                continue
    return rows, sorted(columns)


# ---------------------------------------------------------------------------
# Affichage des statistiques
# ---------------------------------------------------------------------------

def _ascii_bar(count: int, total: int, width: int = 20) -> str:
    filled = round(width * count / total) if total else 0
    return "█" * filled + "░" * (width - filled)


def show_stats(cfg: DatasetConfig, rows: list[dict], columns: list[str]) -> None:
    """Affiche count, colonnes, 3 exemples aléatoires, distribution des catégories."""
    print(f"\n  Colonnes ({len(columns)}) : {', '.join(columns)}")
    print(f"  Exemples        : {len(rows):,}")

    # 3 exemples aléatoires
    samples = random.sample(rows, min(3, len(rows)))
    print(f"\n  3 exemples aléatoires :")
    for i, row in enumerate(samples, 1):
        text = _extract_text_from_row(row)
        preview = text[:200].replace("\n", " ").strip()
        if len(text) > 200:
            preview += "…"
        print(f"\n    [{i}] {preview}")

    # Distribution des catégories
    print(f"\n  Distribution des catégories (heuristique mots-clés) :")
    cat_counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        text = _extract_text_from_row(row)
        _, cat = classify_category(text)
        cat_counts[cat] += 1

    total = len(rows)
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1])[:10]:
        label = RED_CATEGORY_LABELS.get(cat) or BLUE_CATEGORY_LABELS.get(cat) or cat
        pct = count / total * 100
        bar = _ascii_bar(count, total)
        print(f"    {label:<32} {bar} {count:>6,} ({pct:4.1f}%)")

    uncategorized = total - sum(cat_counts.values())
    if uncategorized > 0:
        print(f"    {'(non classifié)':<32} {uncategorized:>6,}")


# ---------------------------------------------------------------------------
# Split CyberLLMInstruct par agent
# ---------------------------------------------------------------------------

def split_by_agent(rows: list[dict], slug: str) -> dict[str, Path]:
    """Splitte les lignes en fichiers par agent (red / blue).

    "both" → l'exemple est inclus dans red ET blue (dual-use).
    Retourne {agent: path}.
    """
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {
        "red": DATA_RAW / f"{slug}_red.jsonl",
        "blue": DATA_RAW / f"{slug}_blue.jsonl",
    }
    counts = {"red": 0, "blue": 0, "both": 0}

    files = {agent: p.open("w", encoding="utf-8") for agent, p in paths.items()}
    try:
        for row in rows:
            text = _extract_text_from_row(row)
            agent = classify_agent(text)
            if agent == "both":
                counts["both"] += 1
                files["red"].write(json.dumps(row, ensure_ascii=False) + "\n")
                files["blue"].write(json.dumps(row, ensure_ascii=False) + "\n")
            elif agent in files:
                counts[agent] += 1
                files[agent].write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        for fh in files.values():
            fh.close()

    total = len(rows)
    print(
        f"\n  Split CyberLLMInstruct :\n"
        f"    Red (offensif)  : {counts['red'] + counts['both']:,} exemples\n"
        f"    Blue (défensif) : {counts['blue'] + counts['both']:,} exemples\n"
        f"    Dual-use (both) : {counts['both']:,} exemples (inclus dans les deux)"
    )
    return paths


# ---------------------------------------------------------------------------
# Appel normalize_dataset.py
# ---------------------------------------------------------------------------

def run_normalize(
    raw_path: Path,
    agent: str,
    cfg: DatasetConfig,
    output_path: Path | None = None,
) -> tuple[Path, int]:
    """Appelle normalize_dataset.py en subprocess. Retourne (output_path, exemples_conservés)."""
    if output_path is None:
        slug = raw_path.stem
        output_path = DATA_PROCESSED / f"{agent}_{slug}.jsonl"

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(NORMALIZE_SCRIPT),
        "--dataset", str(raw_path),
        "--agent", agent,
        "--format", cfg.format_hint,
        "--output", str(output_path),
    ]

    print(f"\n  Normalisation ({agent}) : {raw_path.name} → {output_path.name}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(BASE_DIR),
    )

    if result.returncode != 0:
        print(f"  ERREUR normalize_dataset.py :\n{result.stderr[:800]}", file=sys.stderr)
        return output_path, 0

    # Extraire le nombre d'exemples conservés depuis stdout
    kept = 0
    for line in result.stdout.splitlines():
        if "Conservés" in line or "écrits" in line:
            parts = [p.strip().replace(",", "") for p in line.split(":")]
            for p in parts:
                if p.isdigit():
                    kept = int(p)
                    break

    # Compter directement si le parsing stdout a échoué
    if kept == 0 and output_path.exists():
        with output_path.open(encoding="utf-8") as fh:
            kept = sum(1 for line in fh if line.strip())

    print(f"  → {kept:,} exemples conservés dans {output_path}")
    return output_path, kept


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def compute_gap_analysis(
    processed_files: list[tuple[str, Path]],
) -> dict[str, dict[str, int]]:
    """Charge les fichiers normalisés et classifie chaque exemple.

    Retourne {"red": {category: count}, "blue": {category: count}}.
    """
    counts: dict[str, dict[str, int]] = {
        "red": defaultdict(int),
        "blue": defaultdict(int),
    }

    for agent, path in processed_files:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    example = json.loads(line)
                    # Extraire le message user pour classification
                    user_text = next(
                        (m["content"] for m in example.get("messages", []) if m.get("role") == "user"),
                        "",
                    )
                    _, cat = classify_category(user_text)

                    # Ranger dans le bon agent
                    if agent == "red" and cat in RED_TAXONOMY:
                        counts["red"][cat] += 1
                    elif agent == "blue" and cat in BLUE_TAXONOMY:
                        counts["blue"][cat] += 1
                    else:
                        # Exemple mal classé → ranger dans l'agent cible sous la catégorie dominante
                        agent_scores_r = sum(_score_text(user_text, RED_TAXONOMY).values())
                        agent_scores_b = sum(_score_text(user_text, BLUE_TAXONOMY).values())
                        if agent == "red":
                            # Trouver la catégorie red la plus proche
                            rs = _score_text(user_text, RED_TAXONOMY)
                            best = max(rs, key=rs.__getitem__)
                            counts["red"][best] += 1
                        else:
                            bs = _score_text(user_text, BLUE_TAXONOMY)
                            best = max(bs, key=bs.__getitem__)
                            counts["blue"][best] += 1
                except (json.JSONDecodeError, KeyError):
                    continue

    return counts


def print_gap_analysis(counts: dict[str, dict[str, int]]) -> None:
    """Affiche les tableaux de gap analysis et les recommandations."""
    print(f"\n{'=' * 65}")
    print("  Gap Analysis — Couverture vs taxonomie cible")
    print(f"  (Cible : {MIN_EXAMPLES_PER_CATEGORY:,} exemples min par catégorie)")
    print(f"{'=' * 65}")

    recommendations: list[str] = []

    for agent, taxonomy_labels in [("red", RED_CATEGORY_LABELS), ("blue", BLUE_CATEGORY_LABELS)]:
        agent_counts = counts.get(agent, {})
        total = sum(agent_counts.values())
        agent_label = "Red Team (Pyrolith v2)" if agent == "red" else "Blue Team (Cryolith v2)"

        print(f"\n  {agent_label} — {total:,} exemples total")
        print(f"  {'Catégorie':<36} {'Count':>7}  {'Statut':<8}  {'Gap':>7}")
        print(f"  {'─' * 65}")

        for cat, label in taxonomy_labels.items():
            count = agent_counts.get(cat, 0)
            gap = MIN_EXAMPLES_PER_CATEGORY - count
            if gap > 0:
                status = "GAP"
                gap_str = f"+{gap:,}"
                recommendations.append(
                    f"  • {agent_label.split('(')[0].strip()}: générer ~{gap:,} exemples "
                    f"'{label}' (actuel : {count:,})"
                )
            else:
                status = "OK"
                gap_str = "—"
            print(f"  {label:<36} {count:>7,}  {status:<8}  {gap_str:>7}")

    # Résumé des recommandations
    print(f"\n{'─' * 65}")
    print("  Recommandations pour la génération synthétique :")
    print(f"{'─' * 65}")
    if recommendations:
        for rec in recommendations:
            print(rec)
    else:
        print("  Toutes les catégories atteignent le seuil minimum.")

    # Catégories sans aucun exemple (priorité absolue)
    zero_cats = [
        (agent, label)
        for agent, labels in [("Red", RED_CATEGORY_LABELS), ("Blue", BLUE_CATEGORY_LABELS)]
        for cat, label in labels.items()
        if counts.get(agent.lower(), {}).get(cat, 0) == 0
    ]
    if zero_cats:
        print(f"\n  PRIORITÉ ABSOLUE (0 exemples) :")
        for agent, label in zero_cats:
            print(f"  !! {agent} Team — {label} : aucune donnée source")


# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Télécharge et normalise les datasets cybersec pour 0Lith Training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=list(DATASET_CONFIGS.keys()),
        default=list(DATASET_CONFIGS.keys()),
        help="Datasets à traiter (défaut : tous)",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Réutiliser les fichiers data/raw/ existants sans re-télécharger",
    )
    parser.add_argument(
        "--skip-normalize",
        action="store_true",
        help="Ne pas appeler normalize_dataset.py (inspecter seulement)",
    )
    parser.add_argument(
        "--gap-only",
        action="store_true",
        help="Afficher uniquement le gap analysis depuis data/processed/ existants",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=None,
        help="Limite d'exemples par dataset (utile pour NIST 530K en dev)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed pour l'échantillonnage des exemples aléatoires",
    )
    args = parser.parse_args()

    random.seed(args.seed)

    # Mode gap-only
    if args.gap_only:
        processed: list[tuple[str, Path]] = []
        for slug in DATA_PROCESSED.glob("*.jsonl"):
            agent = "red" if slug.stem.startswith("red_") else "blue"
            processed.append((agent, slug))
        if not processed:
            print("Aucun fichier dans data/processed/ — lancer sans --gap-only d'abord.")
            sys.exit(1)
        counts = compute_gap_analysis(processed)
        # Totaux
        for agent in ("red", "blue"):
            total = sum(counts.get(agent, {}).values())
            print(f"  Agent {agent.upper():4} : {total:,} exemples")
        print_gap_analysis(counts)
        return

    print(f"\n{'=' * 65}")
    print("  0Lith Training — download_datasets.py")
    print(f"{'=' * 65}")
    print(f"  Datasets sélectionnés : {', '.join(args.datasets)}")
    if args.max_examples:
        print(f"  Limite               : {args.max_examples:,} exemples par dataset")
    print(f"{'=' * 65}")

    all_processed: list[tuple[str, Path]] = []

    for key in args.datasets:
        cfg = DATASET_CONFIGS[key]
        raw_path = DATA_RAW / f"{cfg.slug}.jsonl"

        print(f"\n{'─' * 65}")
        print(f"  [{list(DATASET_CONFIGS.keys()).index(key) + 1}/{len(args.datasets)}] {cfg.hf_id}")
        print(f"{'─' * 65}")

        # Téléchargement ou chargement local
        if args.skip_download and raw_path.exists():
            print(f"  --skip-download : chargement depuis {raw_path}")
            rows, columns = load_raw(raw_path)
        else:
            try:
                raw_path, columns = download_dataset(cfg, args.max_examples)
                rows, _ = load_raw(raw_path)
            except Exception as exc:
                print(f"  ERREUR téléchargement {cfg.hf_id} : {exc}", file=sys.stderr)
                print("  Passage au dataset suivant.", file=sys.stderr)
                continue

        # Affichage des statistiques
        show_stats(cfg, rows, columns)

        if args.skip_normalize:
            continue

        # Normalisation
        if cfg.agents == ["red", "blue"]:
            # CyberLLMInstruct : split par agent
            agent_paths = split_by_agent(rows, cfg.slug)
            for agent, split_path in agent_paths.items():
                out_path, kept = run_normalize(split_path, agent, cfg)
                all_processed.append((agent, out_path))
        else:
            for agent in cfg.agents:
                out_path, kept = run_normalize(raw_path, agent, cfg)
                all_processed.append((agent, out_path))

    # Résumé final
    print(f"\n{'=' * 65}")
    print("  Résumé final")
    print(f"{'=' * 65}")

    totals: dict[str, int] = defaultdict(int)
    for agent, path in all_processed:
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                n = sum(1 for line in fh if line.strip())
            totals[agent] += n
            print(f"  {agent.upper():4} {path.name:<45} {n:>8,} exemples")

    print(f"\n  Total Agent RED  : {totals.get('red', 0):>8,} exemples")
    print(f"  Total Agent BLUE : {totals.get('blue', 0):>8,} exemples")

    # Gap analysis
    if all_processed:
        counts = compute_gap_analysis(all_processed)
        print_gap_analysis(counts)

    print(f"\n{'=' * 65}")
    print("  Pipeline terminé.")
    print(f"  data/processed/ contient {len(list(DATA_PROCESSED.glob('*.jsonl')))} fichier(s).")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
