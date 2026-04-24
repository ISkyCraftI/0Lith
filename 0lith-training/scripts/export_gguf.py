"""
export_gguf.py — Merge LoRA + export GGUF + création Modelfile Ollama.

Référence : files/01_TRAINING_PLAN.md §5.2

Usage :
  python scripts/export_gguf.py --checkpoint models/checkpoints/pyrolith_v2_lora/final
  python scripts/export_gguf.py --checkpoint models/checkpoints/cryolith_v2_lora/final \\
      --quant q8_0 --install --test
  python scripts/export_gguf.py --checkpoint models/checkpoints/pyrolith_v2_lora/final \\
      --quant q4_k_m --model-name pyrolith-v2-experimental --output models/exported/exp/

Quantification (défaut : q5_k_m) :
  - q5_k_m  RECOMMANDÉ pour les modèles fine-tunés — préserve les subtilités LoRA
  - q4_k_m  Plus léger (~2.5 GB) mais risque de perte de comportement fine-tuné
             Utiliser imatrix depuis texte cybersec si ce format est nécessaire
  - q8_0    Quasi-lossless (~4.5 GB), utile pour valider avant quantification
  - f16     Non quantifié (~8 GB), contrôle maximal avant quantification manuelle

GOTCHA CRITIQUE — Template ChatML :
  Le Modelfile doit utiliser EXACTEMENT le template <|im_start|>/<|im_end|> de Qwen3.5.
  Un mismatch de template est la cause #1 de dégradation post-export GGUF.
  Vérifier avec : ollama run {model} "<|im_start|>user\\ntest<|im_end|>\\n<|im_start|>assistant"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

VALID_QUANTS = ["q4_k_m", "q5_k_m", "q8_0", "f16"]
DEFAULT_QUANT = "q5_k_m"
DEFAULT_NUM_CTX = 8192
BASE_MODEL = "Qwen/Qwen3.5-4B"
MAX_SEQ_LENGTH = 2048

SYSTEM_PROMPTS: dict[str, str] = {
    "red": (
        "Tu es Pyrolith, agent Red Team de 0Lith. Expert en sécurité offensive, "
        "pentesting et analyse de vulnérabilités. Tu aides les professionnels de la "
        "cybersécurité à comprendre les techniques d'attaque pour mieux se défendre. "
        "Tu travailles exclusivement dans des contextes légaux et éthiques."
    ),
    "blue": (
        "Tu es Cryolith, agent Blue Team de 0Lith. Expert en défense cybersécurité, "
        "analyse de logs, détection d'intrusions et réponse aux incidents. Tu aides "
        "les équipes SOC et les défenseurs à identifier et neutraliser les menaces."
    ),
    "unknown": (
        "Tu es un assistant cybersécurité expert. Tu aides les professionnels de la "
        "sécurité informatique dans leurs missions défensives et offensives, "
        "exclusivement dans des contextes légaux et éthiques."
    ),
}

QUANT_INFO: dict[str, dict] = {
    "q5_k_m": {"size_gb": 3.0, "label": "Q5_K_M", "note": "Recommandé — préserve les subtilités LoRA"},
    "q4_k_m": {"size_gb": 2.5, "label": "Q4_K_M", "note": "Léger — risque de perte de signal fine-tuné"},
    "q8_0":   {"size_gb": 4.5, "label": "Q8_0",   "note": "Quasi-lossless — pour validation pre-quant"},
    "f16":    {"size_gb": 8.0, "label": "F16",    "note": "Non quantifié — contrôle maximal"},
}

# Template ChatML exact de Qwen3.5 pour Ollama
# CRITIQUE : ne pas modifier sans tester — cause #1 de dégradation post-export
CHATML_TEMPLATE = """\
{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
{{ .Response }}<|im_end|>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Détection automatique
# ─────────────────────────────────────────────────────────────────────────────

def detect_agent(checkpoint_path: Path) -> str:
    """Détecte l'agent (red/blue) depuis le nom du checkpoint."""
    path_str = str(checkpoint_path).lower()

    red_indicators = ["pyrolith", "red_team", "redteam", "_red", "-red"]
    blue_indicators = ["cryolith", "blue_team", "blueteam", "_blue", "-blue"]

    red_score = sum(1 for ind in red_indicators if ind in path_str)
    blue_score = sum(1 for ind in blue_indicators if ind in path_str)

    if red_score > blue_score:
        return "red"
    if blue_score > red_score:
        return "blue"
    return "unknown"


def derive_model_name(checkpoint_path: Path) -> str:
    """Déduit le nom du modèle Ollama depuis le chemin du checkpoint.

    Exemples :
      models/checkpoints/pyrolith_v2_lora/final → pyrolith-v2
      models/checkpoints/cryolith_v2_lora/final → cryolith-v2
      models/checkpoints/pyrolith_v2_lora       → pyrolith-v2
    """
    parts = checkpoint_path.parts

    # Chercher le premier segment significatif (ignorer final/, interrupted_*)
    name = None
    for part in reversed(parts):
        if part == "final":
            continue
        if part.startswith("interrupted_"):
            continue
        name = part
        break

    if name is None:
        name = checkpoint_path.name

    # Supprimer les suffixes courants de training
    for suffix in ("_lora", "_adapter", "_checkpoint", "_merged"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    return name.replace("_", "-")


def find_gguf_file(output_dir: Path) -> Path | None:
    """Trouve le fichier GGUF généré dans le dossier de sortie.

    Unsloth peut créer les fichiers GGUF dans un sous-dossier suffixé _gguf
    (ex: output_dir_gguf/) au lieu de output_dir/ directement.
    On cherche dans les deux emplacements.
    """
    # Chercher dans le dossier spécifié
    gguf_files = sorted(output_dir.glob("*.gguf"))

    # Fallback : chercher dans output_dir_gguf/ (comportement Unsloth récent)
    if not gguf_files:
        gguf_dir = output_dir.parent / (output_dir.name + "_gguf")
        if gguf_dir.is_dir():
            gguf_files = sorted(gguf_dir.glob("*.gguf"))

    # Fallback : chercher récursivement dans les sous-dossiers
    if not gguf_files:
        gguf_files = sorted(output_dir.rglob("*.gguf"))

    if not gguf_files:
        return None
    # Préférer le fichier quantifié (pas BF16-mmproj), puis le plus récent
    non_mmproj = [f for f in gguf_files if "mmproj" not in f.name.lower()]
    candidates = non_mmproj if non_mmproj else gguf_files
    return max(candidates, key=lambda p: p.stat().st_mtime)


# ─────────────────────────────────────────────────────────────────────────────
# Génération du Modelfile
# ─────────────────────────────────────────────────────────────────────────────

def generate_modelfile(
    gguf_file: Path,
    model_name: str,
    agent: str,
    num_ctx: int = DEFAULT_NUM_CTX,
) -> str:
    """Génère le contenu du Modelfile Ollama.

    Le path GGUF est relatif au Modelfile (même dossier).
    CRITIQUE : ne pas modifier le template ChatML — cause #1 de dégradation.
    """
    system_prompt = SYSTEM_PROMPTS[agent]
    gguf_relative = f"./{gguf_file.name}"

    lines = [
        f"FROM {gguf_relative}",
        "",
        'TEMPLATE """',
        CHATML_TEMPLATE.rstrip(),
        '"""',
        "",
        f'SYSTEM """{system_prompt}"""',
        "",
        'PARAMETER stop "<|im_end|>"',
        f"PARAMETER num_ctx {num_ctx}",
        "",
        f"# Généré par export_gguf.py — modèle : {model_name}",
        f"# Agent : {agent} | Quantification : {gguf_file.name}",
    ]
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Chargement et export
# ─────────────────────────────────────────────────────────────────────────────

def load_and_export(
    checkpoint_path: Path,
    output_dir: Path,
    quant: str,
) -> Path:
    """Charge le checkpoint LoRA via Unsloth et exporte en GGUF.

    Retourne le chemin du fichier GGUF produit.
    """
    try:
        import torch
        from unsloth import FastLanguageModel
    except ImportError as exc:
        print(f"\n[ERREUR] Import échoué : {exc}")
        print("Vérifier l'installation : python scripts/validate_env.py")
        sys.exit(1)

    # Vérification CUDA
    if not torch.cuda.is_available():
        print("\n[ERREUR] CUDA non disponible — impossible de charger le modèle.")
        sys.exit(1)

    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"  GPU   : {torch.cuda.get_device_name(0)}")
    print(f"  VRAM  : {vram_gb:.1f} GB")
    print(f"  CUDA  : {torch.version.cuda}")

    print(f"\n[1/3] Chargement du checkpoint LoRA : {checkpoint_path}")
    print(
        "      Unsloth détecte adapter_config.json et charge automatiquement "
        f"le modèle de base ({BASE_MODEL}) + l'adaptateur LoRA."
    )

    # Unsloth charge le modèle de base + applique l'adaptateur si adapter_config.json
    # est présent dans checkpoint_path (format PEFT standard produit par train_sft.py).
    # load_in_4bit=False OBLIGATOIRE sur Qwen3.5 (cf. CLAUDE.md)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(checkpoint_path),
        max_seq_length=MAX_SEQ_LENGTH,
        load_in_4bit=False,
        dtype=torch.bfloat16,
    )

    peak_load_gb = torch.cuda.max_memory_allocated() / 1024**3
    print(f"  Modèle chargé — VRAM utilisée : {peak_load_gb:.1f} GB")

    output_dir.mkdir(parents=True, exist_ok=True)

    quant_label = QUANT_INFO[quant]["label"]
    quant_size = QUANT_INFO[quant]["size_gb"]
    print(f"\n[2/3] Export GGUF ({quant_label}, ~{quant_size:.1f} GB) → {output_dir}")
    print("      Merge LoRA + quantification en cours… (peut prendre 5-15 min)")

    t_start = time.monotonic()
    model.save_pretrained_gguf(str(output_dir), tokenizer, quantization_method=quant)
    duration = time.monotonic() - t_start

    print(f"  Export terminé en {duration:.0f}s")

    # Localiser le GGUF produit
    gguf_file = find_gguf_file(output_dir)
    if gguf_file is None:
        print(f"\n[ERREUR] Aucun fichier .gguf trouvé dans {output_dir}")
        print("  Vérifier les logs Unsloth ci-dessus pour identifier l'erreur.")
        sys.exit(1)

    print(f"  Fichier GGUF : {gguf_file} ({gguf_file.stat().st_size / 1024**3:.2f} GB)")
    return gguf_file


# ─────────────────────────────────────────────────────────────────────────────
# Intégration Ollama
# ─────────────────────────────────────────────────────────────────────────────

def create_ollama_model(model_name: str, modelfile_path: Path) -> bool:
    """Importe le modèle dans Ollama via `ollama create`.

    Retourne True si succès.
    """
    print(f"\n[4/4] Import Ollama : ollama create {model_name}")
    cmd = ["ollama", "create", model_name, "-f", str(modelfile_path)]
    print(f"  Commande : {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=900,
        )
    except FileNotFoundError:
        print("  [ERREUR] ollama non trouvé dans PATH.")
        print("  Installer Ollama : https://ollama.com/download")
        return False
    except subprocess.TimeoutExpired:
        print("  [ERREUR] Timeout (900s) — ollama create n'a pas répondu.")
        print("  Vérifier qu'Ollama est en cours d'exécution et que le GGUF est valide.")
        return False

    if result.returncode != 0:
        print(f"  [ERREUR] ollama create a échoué (code {result.returncode})")
        if result.stderr:
            print(f"  stderr : {result.stderr.strip()}")
        return False

    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")

    print(f"  ✓ Modèle importé : {model_name}")
    return True


def test_ollama_model(model_name: str) -> bool:
    """Vérifie le modèle importé avec un test rapide.

    Retourne True si la réponse est non-vide.
    """
    test_prompt = "Décris ton rôle en une phrase."
    print(f"\n[TEST] ollama run {model_name} \"{test_prompt}\"")

    cmd = ["ollama", "run", model_name, test_prompt]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except FileNotFoundError:
        print("  [ERREUR] ollama non trouvé dans PATH.")
        return False
    except subprocess.TimeoutExpired:
        print("  [ERREUR] Timeout (120s) — modèle trop lent ou non chargé.")
        return False

    if result.returncode != 0:
        print(f"  [ERREUR] ollama run a échoué (code {result.returncode})")
        if result.stderr:
            print(f"  stderr : {result.stderr.strip()}")
        return False

    response = result.stdout.strip()
    if not response:
        print("  [ATTENTION] Réponse vide — vérifier le template ChatML dans le Modelfile.")
        return False

    print(f"\n  Réponse du modèle :")
    print(f"  {'─' * 60}")
    for line in response.splitlines():
        print(f"  {line}")
    print(f"  {'─' * 60}")
    print("  ✓ Test rapide réussi")
    return True


def check_ollama_available() -> bool:
    """Vérifie qu'Ollama est accessible."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
            model_count = len(data.get("models", []))
            print(f"  Ollama accessible ({model_count} modèle(s) chargé(s))")
            return True
    except Exception as exc:
        print(f"  [ATTENTION] Ollama non accessible : {exc}")
        print("  Démarrer Ollama avant de continuer.")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Résumé final
# ─────────────────────────────────────────────────────────────────────────────

def print_export_summary(
    checkpoint_path: Path,
    gguf_file: Path,
    modelfile_path: Path,
    model_name: str,
    agent: str,
    quant: str,
    installed: bool,
    tested: bool,
) -> None:
    quant_info = QUANT_INFO[quant]
    print("\n" + "═" * 60)
    print("EXPORT TERMINÉ")
    print("═" * 60)
    print(f"  Checkpoint    : {checkpoint_path}")
    print(f"  GGUF          : {gguf_file}")
    print(f"  Taille        : {gguf_file.stat().st_size / 1024**3:.2f} GB")
    print(f"  Quantisation  : {quant_info['label']} — {quant_info['note']}")
    print(f"  Modelfile     : {modelfile_path}")
    print(f"  Agent         : {agent}")
    print(f"  Modèle Ollama : {model_name}")
    print(f"  Installé      : {'✓ oui' if installed else '✗ non'}")
    print(f"  Testé         : {'✓ oui' if tested else '✗ non'}")
    print()

    if not installed:
        print("─ Étapes suivantes ─")
        print(f"  # Importer dans Ollama :")
        print(f"  ollama create {model_name} -f {modelfile_path}")
        print()

    if installed and not tested:
        print(f"  # Tester le modèle :")
        print(f"  ollama run {model_name} \"Décris ton rôle en une phrase.\"")
        print()

    print("  # Évaluer sur le golden test set :")
    print(f"  python scripts/evaluate.py --model {model_name}")
    print()
    print("  # Évaluation complète avec baseline :")
    print(f"  python scripts/evaluate.py --model {model_name} --categories red blue safety")
    print("═" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge LoRA + export GGUF + création Modelfile Ollama — 0Lith Training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--checkpoint",
        required=True,
        help="Chemin vers le dossier LoRA (ex: models/checkpoints/pyrolith_v2_lora/final)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Dossier de sortie (défaut: models/exported/{model-name}-{quant}/)",
    )
    parser.add_argument(
        "--quant",
        default=DEFAULT_QUANT,
        choices=VALID_QUANTS,
        help=f"Méthode de quantification GGUF (défaut: {DEFAULT_QUANT})",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help="Nom du modèle Ollama (défaut: déduit du checkpoint)",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=DEFAULT_NUM_CTX,
        help=f"Taille du contexte Ollama (défaut: {DEFAULT_NUM_CTX})",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Importer automatiquement dans Ollama après export",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Faire un test rapide après import Ollama (implique --install)",
    )
    args = parser.parse_args()

    # --test implique --install
    if args.test:
        args.install = True

    # ── Résolution des chemins ────────────────────────────────────────────────
    checkpoint_path = Path(args.checkpoint).resolve()
    if not checkpoint_path.exists():
        print(f"[ERREUR] Checkpoint introuvable : {checkpoint_path}")
        sys.exit(1)

    # Vérifier que c'est bien un adaptateur PEFT (adapter_config.json présent)
    adapter_config = checkpoint_path / "adapter_config.json"
    if not adapter_config.exists():
        print(f"[ERREUR] adapter_config.json non trouvé dans {checkpoint_path}")
        print("  Ce dossier ne semble pas être un checkpoint PEFT LoRA valide.")
        print("  Chemin attendu : models/checkpoints/*/final/")
        print("  Généré par    : train_sft.py → dossier final/ ou interrupted_*/")
        sys.exit(1)

    # ── Détection automatique ─────────────────────────────────────────────────
    agent = detect_agent(checkpoint_path)
    model_name = args.model_name or derive_model_name(checkpoint_path)
    quant = args.quant

    # Dossier de sortie
    if args.output:
        output_dir = Path(args.output).resolve()
    else:
        output_dir = (
            Path(__file__).parent.parent
            / "models"
            / "exported"
            / f"{model_name}-{quant}"
        )

    modelfile_path = output_dir / "Modelfile"

    # ── Affichage du plan ─────────────────────────────────────────────────────
    quant_info = QUANT_INFO[quant]
    print("=" * 60)
    print("0LITH — EXPORT GGUF + MODELFILE OLLAMA")
    print("=" * 60)
    print(f"  Checkpoint    : {checkpoint_path}")
    print(f"  Agent détecté : {agent}")
    print(f"  Nom modèle    : {model_name}")
    print(f"  Quantisation  : {quant_info['label']} (~{quant_info['size_gb']:.1f} GB) — {quant_info['note']}")
    print(f"  Sortie GGUF   : {output_dir}/")
    print(f"  Modelfile     : {modelfile_path}")
    print(f"  Import Ollama : {'oui' if args.install else 'non (ajouter --install)'}")
    print(f"  Test rapide   : {'oui' if args.test else 'non (ajouter --test)'}")

    if agent == "unknown":
        print()
        print("[ATTENTION] Agent non détecté depuis le nom du checkpoint.")
        print("  Ni 'pyrolith'/'red' ni 'cryolith'/'blue' dans le chemin.")
        print("  System prompt générique utilisé. Renommer le checkpoint ou")
        print("  vérifier que le chemin contient l'identifiant agent.")

    if quant == "q4_k_m":
        print()
        print("[ATTENTION] Q4_K_M sélectionné — risque de perte du signal LoRA.")
        print("  Recommandation : générer une imatrix depuis du texte cybersec")
        print("  avant quantification. Voir files/01_TRAINING_PLAN.md §5.2.")

    # Vérification Ollama si --install
    if args.install:
        print()
        print("[0/4] Vérification Ollama…")
        if not check_ollama_available():
            print("  Continuer sans --install ou démarrer Ollama d'abord.")
            sys.exit(1)

    print()

    # ── Validation adapter_config ─────────────────────────────────────────────
    try:
        with open(adapter_config, encoding="utf-8") as f:
            ac = json.load(f)
        base_from_config = ac.get("base_model_name_or_path", "")
        if "Qwen3.5" not in base_from_config and "qwen3.5" not in base_from_config.lower():
            print(f"[ATTENTION] base_model dans adapter_config.json : {base_from_config}")
            print(f"  Attendu : {BASE_MODEL}")
            print("  Continuer avec précaution.")
        else:
            print(f"  ✓ Base model confirmé : {base_from_config}")
        lora_r = ac.get("r", "?")
        print(f"  LoRA rank     : r={lora_r}")
    except Exception as exc:
        print(f"[ATTENTION] Impossible de lire adapter_config.json : {exc}")

    print()

    # ── Export GGUF ───────────────────────────────────────────────────────────
    gguf_file = load_and_export(checkpoint_path, output_dir, quant)

    # ── Génération du Modelfile ───────────────────────────────────────────────
    print(f"\n[3/3] Génération du Modelfile Ollama → {modelfile_path}")
    modelfile_content = generate_modelfile(gguf_file, model_name, agent, args.num_ctx)
    modelfile_path.write_text(modelfile_content, encoding="utf-8")
    print("  Contenu du Modelfile :")
    print("  " + "─" * 56)
    for line in modelfile_content.splitlines():
        print(f"  {line}")
    print("  " + "─" * 56)

    # ── Import Ollama ─────────────────────────────────────────────────────────
    installed = False
    tested = False

    if args.install:
        installed = create_ollama_model(model_name, modelfile_path)
        if not installed:
            print("\n[ATTENTION] Import Ollama échoué — GGUF et Modelfile conservés.")
            print(f"  Réessayer manuellement :")
            print(f"  ollama create {model_name} -f {modelfile_path}")

    # ── Test rapide ───────────────────────────────────────────────────────────
    if args.test and installed:
        tested = test_ollama_model(model_name)
        if not tested:
            print("\n[ATTENTION] Test rapide échoué.")
            print("  Vérifier le template ChatML dans le Modelfile.")
            print("  Cause probable : mismatch <|im_start|>/<|im_end|>.")

    # ── Résumé ────────────────────────────────────────────────────────────────
    print_export_summary(
        checkpoint_path=checkpoint_path,
        gguf_file=gguf_file,
        modelfile_path=modelfile_path,
        model_name=model_name,
        agent=agent,
        quant=quant,
        installed=installed,
        tested=tested,
    )


if __name__ == "__main__":
    main()
