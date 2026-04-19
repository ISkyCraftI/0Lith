"""
train_sft.py — Entraînement SFT (Supervised Fine-Tuning) avec Unsloth + TRL.

Charge Qwen/Qwen3.5-4B en bf16, applique LoRA via Unsloth FastLanguageModel,
entraîne avec TRL SFTTrainer, sauvegarde les checkpoints LoRA.

Usage :
  # Blue Team (Cryolith v2)
  python scripts/train_sft.py --config configs/blue_team.yaml

  # Red Team (Pyrolith v2) avec nom de run
  python scripts/train_sft.py --config configs/red_team.yaml --run-name pyrolith_v2_run1

  # Dataset spécifique (fichier ou dossier)
  python scripts/train_sft.py --config configs/blue_team.yaml --data data/processed/blue_fenrir_v2.jsonl
  python scripts/train_sft.py --config configs/blue_team.yaml --data data/processed/

  # Filtre agent (ne charge que les fichiers blue_*.jsonl)
  python scripts/train_sft.py --config configs/blue_team.yaml --filter-agent blue

  # Dry-run : valide config + dataset sans entraîner
  python scripts/train_sft.py --config configs/blue_team.yaml --dry-run

  # Reprendre depuis checkpoint
  python scripts/train_sft.py --config configs/blue_team.yaml --resume models/checkpoints/cryolith_v2_run1/checkpoint-200

  # Tracking WandB
  python scripts/train_sft.py --config configs/blue_team.yaml --wandb --run-name cryolith_v2_run1

  # Limiter les steps (test rapide)
  python scripts/train_sft.py --config configs/blue_team.yaml --max-steps 50 --dry-run

Contraintes critiques (NE PAS modifier) :
  - load_in_4bit=False      : QLoRA déconseillé sur Qwen3.5 par Unsloth
  - use_gradient_checkpointing="unsloth" : string, jamais True
  - lora_alpha == r         : recommandation Unsloth pour Qwen3.5
  - bf16=True, fp16=False   : jamais les deux True
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Chemins de base
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DATA_PROCESSED = BASE_DIR / "data" / "processed"
MODELS_DIR = BASE_DIR / "models" / "checkpoints"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    base_model: str
    max_seq_length: int
    load_in_4bit: bool
    load_in_16bit: bool
    dtype: str
    full_finetuning: bool


@dataclass
class LoraConfig:
    r: int
    lora_alpha: int
    lora_dropout: float
    bias: str
    use_gradient_checkpointing: str
    random_state: int
    target_modules: list[str]


@dataclass
class TrainingConfig:
    per_device_train_batch_size: int
    gradient_accumulation_steps: int
    num_train_epochs: int
    learning_rate: float
    lr_scheduler_type: str
    warmup_ratio: float
    optim: str
    fp16: bool
    bf16: bool
    logging_steps: int
    save_strategy: str
    save_steps: int
    output_dir: str
    seed: int


@dataclass
class Config:
    model: ModelConfig
    lora: LoraConfig
    training: TrainingConfig
    raw: dict = field(default_factory=dict)


def load_config(path: Path) -> Config:
    """Charge et valide le fichier YAML de configuration."""
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        _die("pyyaml non installé. pip install pyyaml>=6.0.0")

    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    m = raw["model"]
    l = raw["lora"]
    t = raw["training"]

    return Config(
        model=ModelConfig(
            base_model=m["base_model"],
            max_seq_length=m["max_seq_length"],
            load_in_4bit=bool(m.get("load_in_4bit", False)),
            load_in_16bit=bool(m.get("load_in_16bit", True)),
            dtype=m.get("dtype", "bfloat16"),
            full_finetuning=bool(m.get("full_finetuning", False)),
        ),
        lora=LoraConfig(
            r=int(l["r"]),
            lora_alpha=int(l["lora_alpha"]),
            lora_dropout=float(l["lora_dropout"]),
            bias=str(l["bias"]),
            use_gradient_checkpointing=str(l["use_gradient_checkpointing"]),
            random_state=int(l["random_state"]),
            target_modules=list(l["target_modules"]),
        ),
        training=TrainingConfig(
            per_device_train_batch_size=int(t["per_device_train_batch_size"]),
            gradient_accumulation_steps=int(t["gradient_accumulation_steps"]),
            num_train_epochs=int(t["num_train_epochs"]),
            learning_rate=float(t["learning_rate"]),
            lr_scheduler_type=str(t["lr_scheduler_type"]),
            warmup_ratio=float(t["warmup_ratio"]),
            optim=str(t["optim"]),
            fp16=bool(t.get("fp16", False)),
            bf16=bool(t.get("bf16", True)),
            logging_steps=int(t["logging_steps"]),
            save_strategy=str(t["save_strategy"]),
            save_steps=int(t["save_steps"]),
            output_dir=str(t["output_dir"]),
            seed=int(t["seed"]),
        ),
        raw=raw,
    )


def validate_config(cfg: Config) -> list[str]:
    """Vérifie les contraintes critiques. Retourne la liste des avertissements/erreurs."""
    issues: list[str] = []

    # Contrainte absolue : QLoRA interdit sur Qwen3.5
    if cfg.model.load_in_4bit:
        issues.append(
            "ERREUR CRITIQUE : load_in_4bit=True détecté.\n"
            "  QLoRA est DÉCONSEILLÉ sur Qwen3.5 (différences de quantification anormales).\n"
            "  → Mettre load_in_4bit: false dans le YAML."
        )

    # use_gradient_checkpointing doit être "unsloth" (string)
    gc = cfg.lora.use_gradient_checkpointing
    if gc is True or (isinstance(gc, str) and gc.lower() == "true"):
        issues.append(
            "ERREUR : use_gradient_checkpointing=True (bool) détecté.\n"
            "  → Utiliser la valeur string : use_gradient_checkpointing: \"unsloth\""
        )
    elif gc != "unsloth":
        issues.append(
            f"AVERTISSEMENT : use_gradient_checkpointing=\"{gc}\".\n"
            "  Valeur recommandée par Unsloth pour Qwen3.5 : \"unsloth\"."
        )

    # lora_alpha doit être égal à r
    if cfg.lora.lora_alpha != cfg.lora.r:
        issues.append(
            f"AVERTISSEMENT : lora_alpha ({cfg.lora.lora_alpha}) ≠ r ({cfg.lora.r}).\n"
            "  Unsloth recommande lora_alpha == r pour Qwen3.5."
        )

    # bf16/fp16 exclusifs
    if cfg.training.bf16 and cfg.training.fp16:
        issues.append(
            "ERREUR : bf16=True ET fp16=True simultanément.\n"
            "  → Mettre fp16: false dans le YAML."
        )
    if not cfg.training.bf16:
        issues.append(
            "AVERTISSEMENT : bf16=False. bf16=True est requis pour l'entraînement Qwen3.5."
        )

    return issues


# ---------------------------------------------------------------------------
# VRAM
# ---------------------------------------------------------------------------

def check_vram(min_gb: float = 14.0) -> None:
    """Vérifie la VRAM disponible avant de charger le modèle."""
    try:
        import torch
        if not torch.cuda.is_available():
            _die(
                "CUDA non disponible. Vérifier le driver NVIDIA et l'installation PyTorch CUDA.\n"
                "  RTX 5070 Ti 16 GB requiert CUDA 12.8+ et torch >= 2.6.0"
            )
        props = torch.cuda.get_device_properties(0)
        total_gb = props.total_memory / (1024 ** 3)
        free_gb  = (props.total_memory - torch.cuda.memory_allocated()) / (1024 ** 3)

        print(f"  GPU         : {props.name}")
        print(f"  VRAM total  : {total_gb:.1f} GB")
        print(f"  VRAM libre  : {free_gb:.1f} GB")

        if total_gb < min_gb:
            _die(
                f"VRAM insuffisante : {total_gb:.1f} GB disponibles, {min_gb} GB requis.\n"
                "  Fallback possible :\n"
                "    → Réduire max_seq_length : 2048 → 1024 dans le YAML\n"
                "    → Réduire gradient_accumulation_steps : 8 → 16 + batch_size : 1 → 1\n"
                "    → Plan B : Qwen3-4B avec QLoRA (~7-9 GB, modèle base inférieur)"
            )
    except ImportError:
        _die("torch non installé. pip install torch>=2.6.0")


def get_vram_peak_gb() -> float | None:
    """Retourne le pic VRAM alloué depuis le début du processus."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / (1024 ** 3)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def load_jsonl_files(paths: list[Path]) -> "Any":
    """Charge et concatène plusieurs JSONL en un Dataset HuggingFace."""
    try:
        from datasets import Dataset, concatenate_datasets  # type: ignore[import]
    except ImportError:
        _die("datasets non installé. pip install datasets>=3.3.0")

    all_rows: list[dict] = []
    for p in paths:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if "messages" in row and isinstance(row["messages"], list):
                        all_rows.append(row)
                except json.JSONDecodeError:
                    continue

    if not all_rows:
        _die(
            "Aucun exemple valide trouvé dans les fichiers fournis.\n"
            "  Chaque ligne doit avoir une clé 'messages' au format ChatML.\n"
            "  Vérifier avec : python scripts/normalize_dataset.py --dry-run"
        )

    return Dataset.from_list(all_rows)


def resolve_data_paths(data_arg: str | None, filter_agent: str | None) -> list[Path]:
    """Résout --data en liste de fichiers JSONL."""
    if data_arg:
        p = Path(data_arg)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.is_file():
            return [p]
        if p.is_dir():
            search_dir = p
        else:
            _die(f"--data introuvable : {p}")
    else:
        search_dir = DATA_PROCESSED

    jsonl_files = sorted(search_dir.glob("*.jsonl"))
    if filter_agent:
        jsonl_files = [f for f in jsonl_files if f.stem.startswith(f"{filter_agent}_")]

    if not jsonl_files:
        hint = f" (filtre agent='{filter_agent}')" if filter_agent else ""
        _die(
            f"Aucun fichier JSONL trouvé dans {search_dir}{hint}.\n"
            "  Générer les données avec : python scripts/download_datasets.py\n"
            "  Ou : python scripts/normalize_dataset.py --dataset <hf_id> --agent blue"
        )

    return jsonl_files


def apply_chat_template_to_dataset(dataset: "Any", tokenizer: "Any") -> "Any":
    """Applique le template ChatML et crée une colonne 'text'."""

    def _format(example: dict) -> dict:
        text = tokenizer.apply_chat_template(
            example["messages"],
            tokenize=False,
            add_generation_prompt=False,
        )
        return {"text": text}

    return dataset.map(_format, desc="Application du template ChatML", num_proc=1)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def make_csv_logger(log_path: Path) -> "Any":
    """Retourne un TrainerCallback qui écrit les logs dans un CSV local."""
    try:
        from transformers import TrainerCallback  # type: ignore[import]
    except ImportError:
        return None

    class CSVLoggerCallback(TrainerCallback):
        def __init__(self) -> None:
            self._file = log_path.open("w", newline="", encoding="utf-8")
            self._writer: csv.DictWriter | None = None

        def on_log(self, args: Any, state: Any, control: Any, logs: Any = None, **kwargs: Any) -> None:
            if logs is None:
                return
            row = {
                "step":  state.global_step,
                "epoch": round(state.epoch, 4) if state.epoch else 0,
                **{k: round(v, 6) if isinstance(v, float) else v for k, v in logs.items()},
            }
            if self._writer is None:
                self._writer = csv.DictWriter(self._file, fieldnames=list(row.keys()), extrasaction="ignore")
                self._writer.writeheader()
            # Assure que toutes les colonnes sont présentes
            for key in self._writer.fieldnames:
                row.setdefault(key, "")
            self._writer.writerow(row)
            self._file.flush()

        def on_train_end(self, *args: Any, **kwargs: Any) -> None:
            self._file.close()

    return CSVLoggerCallback()


# ---------------------------------------------------------------------------
# Chargement du modèle + LoRA
# ---------------------------------------------------------------------------

def load_model_and_tokenizer(cfg: Config) -> tuple["Any", "Any"]:
    """Charge Qwen3.5-4B avec Unsloth FastLanguageModel en bf16."""
    try:
        from unsloth import FastLanguageModel  # type: ignore[import]
    except ImportError:
        _die(
            "Unsloth non installé.\n"
            "  pip install 'unsloth[cu128-torch260] @ git+https://github.com/unslothai/unsloth.git'\n"
            "  Vérifier avec : python scripts/validate_env.py"
        )

    import torch

    # Résoudre dtype
    dtype_map = {
        "bfloat16": torch.bfloat16,
        "float16":  torch.float16,
        "float32":  torch.float32,
    }
    dtype = dtype_map.get(cfg.model.dtype, torch.bfloat16)

    if dtype == torch.bfloat16:
        try:
            from unsloth import is_bfloat16_supported  # type: ignore[import]
            if not is_bfloat16_supported():
                print(
                    "  AVERTISSEMENT : bf16 non supporté nativement sur ce GPU.\n"
                    "  RTX 5070 Ti (Blackwell, CC 12.0) supporte bf16 — si ce message apparaît,\n"
                    "  vérifier la version de torch (>= 2.6.0 requis pour Blackwell)."
                )
        except ImportError:
            pass

    print(f"  Chargement   : {cfg.model.base_model}")
    print(f"  Precision    : bf16 LoRA (load_in_4bit=False)")
    print(f"  max_seq_len  : {cfg.model.max_seq_length}")

    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=cfg.model.base_model,
            max_seq_length=cfg.model.max_seq_length,
            load_in_4bit=False,       # JAMAIS True sur Qwen3.5
            dtype=dtype,
        )
    except OSError as exc:
        if "not found" in str(exc).lower() or "repository" in str(exc).lower():
            _die(
                f"Modèle introuvable : {cfg.model.base_model}\n"
                "  Options :\n"
                "    1. Télécharger via HuggingFace Hub :\n"
                f"       huggingface-cli download {cfg.model.base_model}\n"
                "    2. Utiliser la version Unsloth optimisée :\n"
                f"       Remplacer base_model par 'unsloth/{cfg.model.base_model.split('/')[-1]}' dans le YAML\n"
                "    3. Vérifier la connexion réseau et l'authentification HF :\n"
                "       huggingface-cli login"
            )
        raise

    return model, tokenizer


def apply_lora(model: "Any", cfg: Config) -> "Any":
    """Applique le PEFT LoRA via Unsloth get_peft_model."""
    try:
        from unsloth import FastLanguageModel  # type: ignore[import]
    except ImportError:
        _die("Unsloth non trouvé — ne devrait pas arriver ici.")

    lc = cfg.lora
    print(f"  LoRA rank    : r={lc.r}, alpha={lc.lora_alpha}")
    print(f"  Modules      : {', '.join(lc.target_modules)}")
    print(f"  grad_ckpt    : {lc.use_gradient_checkpointing!r}")

    model = FastLanguageModel.get_peft_model(
        model,
        r=lc.r,
        lora_alpha=lc.lora_alpha,
        lora_dropout=lc.lora_dropout,
        bias=lc.bias,
        use_gradient_checkpointing=lc.use_gradient_checkpointing,
        random_state=lc.random_state,
        target_modules=lc.target_modules,
        max_seq_length=cfg.model.max_seq_length,
    )
    return model


# ---------------------------------------------------------------------------
# SFTConfig + Trainer
# ---------------------------------------------------------------------------

def build_sft_config(
    cfg: Config,
    run_name: str,
    output_dir: Path,
    max_steps: int,
    use_wandb: bool,
) -> "Any":
    """Construit le SFTConfig TRL à partir du YAML."""
    try:
        from trl import SFTConfig  # type: ignore[import]
    except ImportError:
        _die("TRL non installé. pip install trl>=0.15.0")

    tc = cfg.training
    report_to = "wandb" if use_wandb else "none"

    sft_kwargs: dict[str, Any] = dict(
        output_dir=str(output_dir),
        run_name=run_name,
        # Données
        dataset_text_field="text",
        max_seq_length=cfg.model.max_seq_length,
        # Batch
        per_device_train_batch_size=tc.per_device_train_batch_size,
        gradient_accumulation_steps=tc.gradient_accumulation_steps,
        # Optimiseur
        learning_rate=tc.learning_rate,
        lr_scheduler_type=tc.lr_scheduler_type,
        warmup_ratio=tc.warmup_ratio,
        optim=tc.optim,
        # Précision
        fp16=tc.fp16,
        bf16=tc.bf16,
        # Durée
        num_train_epochs=tc.num_train_epochs,
        # Logs & sauvegarde
        logging_steps=tc.logging_steps,
        save_strategy=tc.save_strategy,
        save_steps=tc.save_steps,
        save_total_limit=3,   # Garde les 3 derniers checkpoints
        # Reproductibilité
        seed=tc.seed,
        data_seed=tc.seed,
        # Tracking
        report_to=report_to,
    )

    if max_steps > 0:
        sft_kwargs["max_steps"] = max_steps
        sft_kwargs.pop("num_train_epochs", None)

    return SFTConfig(**sft_kwargs)


# ---------------------------------------------------------------------------
# Résumé final
# ---------------------------------------------------------------------------

def print_training_summary(
    trainer: "Any",
    t_start: float,
    output_dir: Path,
    run_name: str,
) -> None:
    """Affiche le résumé post-entraînement."""
    duration = timedelta(seconds=int(time.monotonic() - t_start))
    peak_vram = get_vram_peak_gb()

    # Dernière loss depuis l'historique
    final_loss: float | None = None
    if hasattr(trainer, "state") and trainer.state.log_history:
        losses = [e["loss"] for e in trainer.state.log_history if "loss" in e]
        if losses:
            final_loss = losses[-1]

    W = 65
    print(f"\n{'═' * W}")
    print("  Entraînement terminé")
    print(f"{'═' * W}")
    print(f"  Run name        : {run_name}")
    print(f"  Durée totale    : {duration}")
    if final_loss is not None:
        print(f"  Loss finale     : {final_loss:.4f}")
    if peak_vram is not None:
        print(f"  VRAM peak       : {peak_vram:.2f} GB")
    print(f"  Checkpoint      : {output_dir}")
    print(f"\n  Prochaine étape :")
    config_hint = "blue_team" if "blue" in str(output_dir).lower() else "red_team"
    print(f"    python scripts/export_gguf.py \\")
    print(f"        --config configs/{config_hint}.yaml \\")
    print(f"        --checkpoint {output_dir}")
    print(f"{'═' * W}\n")


# ---------------------------------------------------------------------------
# Utilitaire
# ---------------------------------------------------------------------------

def _die(msg: str) -> None:
    print(f"\n  ERREUR : {msg}\n", file=sys.stderr)
    sys.exit(1)


def _resolve_output_dir(cfg: Config, run_name: str) -> Path:
    """Résout le dossier de sortie : config output_dir / run_name."""
    base = Path(cfg.training.output_dir)
    if not base.is_absolute():
        base = BASE_DIR / base
    out = base.parent / run_name if run_name else base
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Entraînement SFT Qwen3.5-4B avec Unsloth (0Lith Training)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", required=True,
        help="Chemin vers le YAML de config (ex: configs/blue_team.yaml)",
    )
    parser.add_argument(
        "--data", default=None,
        help="Fichier JSONL ou dossier de données (défaut: data/processed/)",
    )
    parser.add_argument(
        "--filter-agent", default=None, choices=["red", "blue"],
        help="Ne charger que les fichiers red_*.jsonl ou blue_*.jsonl",
    )
    parser.add_argument(
        "--run-name", default=None,
        help="Nom du run (WandB + dossier checkpoint). Auto-généré si absent.",
    )
    parser.add_argument(
        "--wandb", action="store_true",
        help="Activer le tracking Weights & Biases (nécessite wandb installé et configuré)",
    )
    parser.add_argument(
        "--resume", default=None, metavar="CHECKPOINT_DIR",
        help="Reprendre depuis un checkpoint (chemin vers le dossier checkpoint-N)",
    )
    parser.add_argument(
        "--max-steps", type=int, default=0,
        help="Limiter le nombre de steps (0 = désactivé, utilise num_train_epochs du YAML)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Valider config + dataset sans charger le modèle ni entraîner",
    )
    parser.add_argument(
        "--no-csv", action="store_true",
        help="Désactiver le logging CSV local",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = BASE_DIR / config_path
    if not config_path.exists():
        _die(f"Config introuvable : {config_path}")

    # ── En-tête
    W = 65
    print(f"\n{'=' * W}")
    print("  0Lith Training — train_sft.py")
    print(f"{'=' * W}")
    print(f"  Config    : {config_path.name}")
    if args.dry_run:
        print("  Mode      : DRY-RUN (validation seule, pas d'entraînement)")
    print()

    # ── Chargement et validation de la config
    print("  [1/6] Chargement de la config...")
    cfg = load_config(config_path)
    issues = validate_config(cfg)

    errors = [i for i in issues if i.startswith("ERREUR")]
    warnings = [i for i in issues if i.startswith("AVERT")]

    for w in warnings:
        print(f"  ⚠  {w}")
    for e in errors:
        print(f"  ✗  {e}", file=sys.stderr)
    if errors:
        sys.exit(1)

    tc = cfg.training
    lc = cfg.lora
    mc = cfg.model
    eff_batch = tc.per_device_train_batch_size * tc.gradient_accumulation_steps
    print(f"  Modèle          : {mc.base_model}")
    print(f"  max_seq_length  : {mc.max_seq_length}")
    print(f"  LoRA r={lc.r}, alpha={lc.lora_alpha}")
    print(f"  Epochs          : {tc.num_train_epochs}  |  Eff. batch : {eff_batch}")
    print(f"  LR              : {tc.learning_rate:.1e}  |  Scheduler : {tc.lr_scheduler_type}")

    # ── Nom du run
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.run_name:
        run_name = args.run_name
    else:
        agent = "blue" if "blue" in config_path.stem else "red"
        run_name = f"{agent}_{mc.base_model.split('/')[-1].lower()}_{ts}"
    print(f"  Run name        : {run_name}")

    # ── Dataset
    print(f"\n  [2/6] Chargement du dataset...")
    data_paths = resolve_data_paths(args.data, args.filter_agent)
    print(f"  Fichiers ({len(data_paths)}) :")
    for p in data_paths:
        print(f"    {p.relative_to(BASE_DIR) if p.is_relative_to(BASE_DIR) else p}")

    dataset_raw = load_jsonl_files(data_paths)
    n_examples = len(dataset_raw)
    print(f"  Exemples        : {n_examples:,}")

    if n_examples < 500:
        print(
            f"  AVERTISSEMENT : {n_examples} exemples est peu pour un SFT de qualité.\n"
            "    Recommandation : 8 000–12 000 exemples minimum (01_TRAINING_PLAN.md §5.1)."
        )

    if args.dry_run:
        # Vérifier le format des 3 premiers exemples
        print(f"\n  [DRY-RUN] Vérification du format ChatML (3 exemples)...")
        for i, ex in enumerate(dataset_raw.select(range(min(3, n_examples)))):
            msgs = ex.get("messages", [])
            roles = [m.get("role") for m in msgs]
            print(f"  Exemple {i+1} : {len(msgs)} messages, rôles : {roles}")
            if not any(r == "user" for r in roles):
                print(f"    AVERTISSEMENT : pas de message 'user' dans l'exemple {i+1}")
        print(f"\n  Dry-run OK — config et dataset valides.")
        print(f"  Pour lancer l'entraînement : relancer sans --dry-run\n")
        sys.exit(0)

    # ── VRAM
    print(f"\n  [3/6] Vérification VRAM...")
    check_vram(min_gb=12.0)  # 12 GB min (14 GB recommandé, mais tolérance pour les cas limites)

    # ── Chargement du modèle
    print(f"\n  [4/6] Chargement du modèle ({mc.base_model})...")
    t_model_start = time.monotonic()

    try:
        import torch
        torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass

    model, tokenizer = load_model_and_tokenizer(cfg)

    vram_after_model = get_vram_peak_gb()
    print(f"  Modèle chargé en {time.monotonic() - t_model_start:.1f}s", end="")
    if vram_after_model:
        print(f"  (VRAM : {vram_after_model:.1f} GB)")
    else:
        print()

    # ── Application LoRA
    print(f"\n  [5/6] Application LoRA (r={lc.r}, alpha={lc.lora_alpha})...")
    model = apply_lora(model, cfg)

    # Compter les paramètres entraînables
    try:
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total     = sum(p.numel() for p in model.parameters())
        print(f"  Params entraînables : {trainable:,} / {total:,} ({trainable/total*100:.2f}%)")
    except Exception:
        pass

    # ── Préparation du dataset
    print(f"\n  [6/6] Application du template ChatML...")
    dataset = apply_chat_template_to_dataset(dataset_raw, tokenizer)

    # ── Setup output + logging
    output_dir = _resolve_output_dir(cfg, run_name)
    log_path = output_dir / "training_log.csv"

    callbacks = []
    if not args.no_csv:
        csv_cb = make_csv_logger(log_path)
        if csv_cb:
            callbacks.append(csv_cb)
            print(f"  Log CSV         : {log_path}")

    if args.wandb:
        try:
            import wandb  # type: ignore[import]
            wandb.init(project="0lith-training", name=run_name)
            print(f"  WandB           : activé (projet=0lith-training, run={run_name})")
        except ImportError:
            print("  WandB non installé — logging CSV uniquement.")

    # ── SFTConfig
    sft_config = build_sft_config(
        cfg, run_name, output_dir,
        max_steps=args.max_steps,
        use_wandb=args.wandb,
    )

    # ── Trainer
    try:
        from trl import SFTTrainer  # type: ignore[import]
    except ImportError:
        _die("TRL non installé. pip install trl>=0.15.0")

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=sft_config,
        callbacks=callbacks if callbacks else None,
    )

    # ── Entraînement
    print(f"\n{'─' * W}")
    print(f"  Démarrage de l'entraînement — {run_name}")
    if args.max_steps > 0:
        print(f"  Limité à {args.max_steps} steps (--max-steps)")
    elif tc.num_train_epochs:
        steps_per_epoch = max(1, n_examples // (tc.per_device_train_batch_size * tc.gradient_accumulation_steps))
        total_steps = steps_per_epoch * tc.num_train_epochs
        print(f"  Steps estimés   : {total_steps:,} ({tc.num_train_epochs} epochs × ~{steps_per_epoch} steps)")
    print(f"{'─' * W}")

    t_start = time.monotonic()

    # Ctrl+C → sauvegarde propre
    interrupted = False

    def _handle_sigint(sig: int, frame: Any) -> None:
        nonlocal interrupted
        if interrupted:
            print("\n  Deuxième interruption — arrêt forcé.", file=sys.stderr)
            sys.exit(1)
        interrupted = True
        print(
            "\n\n  Interruption détectée — sauvegarde du checkpoint en cours...\n"
            "  (Ctrl+C une deuxième fois pour forcer l'arrêt)",
            file=sys.stderr,
        )

    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        resume = args.resume if args.resume else None
        trainer.train(resume_from_checkpoint=resume)

    except RuntimeError as exc:
        err = str(exc)
        if "out of memory" in err.lower() or "cuda" in err.lower():
            print(f"\n  ERREUR OOM (CUDA Out of Memory) :\n  {err[:400]}", file=sys.stderr)
            print(
                "\n  Solutions :\n"
                "    → Réduire max_seq_length : 2048 → 1024 dans le YAML\n"
                "    → Réduire per_device_train_batch_size déjà à 1 — essayer packing=True\n"
                "    → Augmenter gradient_accumulation_steps : 8 → 16\n"
                "    → Fermer les autres applications GPU (Gaming Mode doit être OFF)",
                file=sys.stderr,
            )
            # Sauvegarde si possible
            try:
                oom_dir = output_dir / "oom_checkpoint"
                trainer.save_model(str(oom_dir))
                print(f"  Checkpoint partiel sauvegardé : {oom_dir}", file=sys.stderr)
            except Exception:
                pass
            sys.exit(1)
        raise

    except KeyboardInterrupt:
        interrupted = True

    # Sauvegarde du checkpoint (normal ou interrompu)
    if interrupted:
        save_dir = output_dir / f"interrupted_{ts}"
        print(f"\n  Sauvegarde checkpoint interrompu → {save_dir}")
        trainer.save_model(str(save_dir))
        tokenizer.save_pretrained(str(save_dir))
        print("  Sauvegarde terminée.")
    else:
        # Sauvegarde finale explicite du LoRA adapter
        final_dir = output_dir / "final"
        trainer.save_model(str(final_dir))
        tokenizer.save_pretrained(str(final_dir))
        print(f"\n  Adapter final sauvegardé → {final_dir}")

    # ── Résumé
    print_training_summary(trainer, t_start, output_dir, run_name)


if __name__ == "__main__":
    main()
