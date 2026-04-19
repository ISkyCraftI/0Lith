"""
train_dpo.py — Entraînement DPO (Direct Preference Optimization) avec Unsloth + TRL.

Charge un checkpoint SFT en bf16, applique LoRA via Unsloth FastLanguageModel,
entraîne avec TRL DPOTrainer sur des paires de préférence, sauvegarde les checkpoints.

Un seul cycle DPO = 1 époque (toujours). Max 3 cycles avant reset recommandé.

Usage :
  # Red Team (Pyrolith v2) — cycle DPO depuis Arena
  python scripts/train_dpo.py \\
      --config configs/red_team.yaml \\
      --pairs data/dpo_pairs/red_team_pairs.jsonl \\
      --sft-checkpoint models/checkpoints/pyrolith_v2_lora/final

  # Blue Team avec nom de run explicite
  python scripts/train_dpo.py \\
      --config configs/blue_team.yaml \\
      --pairs data/dpo_pairs/blue_team_pairs.jsonl \\
      --sft-checkpoint models/checkpoints/cryolith_v2_lora/final \\
      --run-name cryolith_dpo_cycle1

  # Dry-run : valider config + dataset sans entraîner
  python scripts/train_dpo.py \\
      --config configs/blue_team.yaml \\
      --pairs data/dpo_pairs/blue_team_pairs.jsonl \\
      --sft-checkpoint models/checkpoints/cryolith_v2_lora/final \\
      --dry-run

  # Forcer un 4e cycle (non recommandé)
  python scripts/train_dpo.py \\
      --config configs/red_team.yaml \\
      --pairs data/dpo_pairs/red_team_pairs.jsonl \\
      --sft-checkpoint models/checkpoints/pyrolith_v2_lora/final \\
      --force

Contraintes critiques (NE PAS modifier) :
  - num_train_epochs : TOUJOURS 1 — multi-epoch = overfitting en self-play
  - load_in_4bit=False      : QLoRA déconseillé sur Qwen3.5 par Unsloth
  - use_gradient_checkpointing="unsloth" : string, jamais True
  - bf16=True, fp16=False   : jamais les deux True
  - max 3 cycles DPO avant reset au checkpoint SFT
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
MODELS_DIR = BASE_DIR / "models" / "checkpoints"

# Hyperparamètres DPO fixes — ne pas exposer dans le YAML
DPO_BETA              = 0.1
DPO_LEARNING_RATE     = 5e-5
DPO_LR_SCHEDULER      = "cosine"
DPO_WARMUP_RATIO      = 0.1
DPO_NUM_EPOCHS        = 1       # TOUJOURS 1 — règle immuable
DPO_BATCH_SIZE        = 1
DPO_GRAD_ACCUM        = 4
DPO_BF16              = True
DPO_MAX_LENGTH        = 2048
DPO_MAX_PROMPT_LENGTH = 1024
DPO_MAX_CYCLES        = 3


# ---------------------------------------------------------------------------
# Config (réutilise le même format YAML que SFT)
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
    """Charge et valide le fichier YAML de configuration (même format que SFT)."""
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

    if cfg.model.load_in_4bit:
        issues.append(
            "ERREUR CRITIQUE : load_in_4bit=True détecté.\n"
            "  QLoRA est DÉCONSEILLÉ sur Qwen3.5 (différences de quantification anormales).\n"
            "  → Mettre load_in_4bit: false dans le YAML."
        )

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

    if cfg.lora.lora_alpha != cfg.lora.r:
        issues.append(
            f"AVERTISSEMENT : lora_alpha ({cfg.lora.lora_alpha}) ≠ r ({cfg.lora.r}).\n"
            "  Unsloth recommande lora_alpha == r pour Qwen3.5."
        )

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
# Compteur de cycles DPO
# ---------------------------------------------------------------------------

def _cycle_counter_path(agent: str) -> Path:
    return MODELS_DIR / f"{agent}_dpo_cycles.txt"


def read_dpo_cycles(agent: str) -> int:
    """Lit le compteur de cycles DPO. Retourne 0 si le fichier n'existe pas."""
    path = _cycle_counter_path(agent)
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0


def increment_dpo_cycles(agent: str) -> int:
    """Incrémente le compteur et retourne la nouvelle valeur."""
    current = read_dpo_cycles(agent)
    new_val = current + 1
    path = _cycle_counter_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(new_val), encoding="utf-8")
    return new_val


def check_dpo_cycle_limit(agent: str, force: bool) -> int:
    """
    Vérifie la limite de cycles DPO.
    Retourne le numéro du prochain cycle (1-indexed).
    Lève SystemExit si >= 3 cycles et force=False.
    """
    current = read_dpo_cycles(agent)
    if current >= DPO_MAX_CYCLES and not force:
        print(
            f"\n  ✗  {DPO_MAX_CYCLES} cycles DPO atteints pour l'agent '{agent}'.",
            file=sys.stderr,
        )
        print(
            f"     Reset au checkpoint SFT recommandé avant de continuer.\n"
            f"     Utilisez --force pour ignorer (non recommandé).\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if current >= DPO_MAX_CYCLES and force:
        print(
            f"  ⚠  AVERTISSEMENT : {current} cycles DPO déjà effectués (limite={DPO_MAX_CYCLES}).\n"
            f"     --force activé — continuation forcée (risque d'overfitting élevé)."
        )

    return current + 1  # numéro du prochain cycle


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
                "    → Réduire DPO_MAX_LENGTH : 2048 → 1024 (modifier le script)\n"
                "    → Réduire DPO_GRAD_ACCUM : 4 → 8\n"
                "    → Fermer les autres applications GPU (Gaming Mode doit être OFF)"
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
# Dataset DPO
# ---------------------------------------------------------------------------

def load_dpo_pairs(path: Path) -> "Any":
    """
    Charge les paires DPO depuis un JSONL.
    Format attendu : {"prompt": "...", "chosen": "...", "rejected": "..."}
    Retourne un Dataset HuggingFace avec colonnes prompt/chosen/rejected.
    """
    try:
        from datasets import Dataset  # type: ignore[import]
    except ImportError:
        _die("datasets non installé. pip install datasets>=3.3.0")

    if not path.exists():
        _die(f"Fichier de paires DPO introuvable : {path}")

    rows: list[dict] = []
    skipped = 0
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print(f"  AVERTISSEMENT : ligne {lineno} JSON invalide — ignorée")
                skipped += 1
                continue

            if not all(k in row for k in ("prompt", "chosen", "rejected")):
                missing = [k for k in ("prompt", "chosen", "rejected") if k not in row]
                print(f"  AVERTISSEMENT : ligne {lineno} manque {missing} — ignorée")
                skipped += 1
                continue

            rows.append({
                "prompt":   str(row["prompt"]),
                "chosen":   str(row["chosen"]),
                "rejected": str(row["rejected"]),
            })

    if not rows:
        _die(
            "Aucune paire DPO valide trouvée.\n"
            "  Chaque ligne doit avoir les clés 'prompt', 'chosen', 'rejected'.\n"
            "  Format : {\"prompt\": \"...\", \"chosen\": \"...\", \"rejected\": \"...\"}"
        )

    if skipped:
        print(f"  {skipped} ligne(s) ignorée(s) (format invalide)")

    return Dataset.from_list(rows)


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
            for key in self._writer.fieldnames:
                row.setdefault(key, "")
            self._writer.writerow(row)
            self._file.flush()

        def on_train_end(self, *args: Any, **kwargs: Any) -> None:
            self._file.close()

    return CSVLoggerCallback()


# ---------------------------------------------------------------------------
# Chargement du modèle (depuis checkpoint SFT)
# ---------------------------------------------------------------------------

def load_model_from_sft_checkpoint(
    sft_checkpoint: Path,
    cfg: Config,
) -> tuple["Any", "Any"]:
    """Charge le checkpoint SFT avec Unsloth FastLanguageModel en bf16."""
    try:
        from unsloth import FastLanguageModel  # type: ignore[import]
    except ImportError:
        _die(
            "Unsloth non installé.\n"
            "  pip install 'unsloth[cu128-torch260] @ git+https://github.com/unslothai/unsloth.git'\n"
            "  Vérifier avec : python scripts/validate_env.py"
        )

    import torch

    dtype_map = {
        "bfloat16": torch.bfloat16,
        "float16":  torch.float16,
        "float32":  torch.float32,
    }
    dtype = dtype_map.get(cfg.model.dtype, torch.bfloat16)

    print(f"  Checkpoint SFT : {sft_checkpoint}")
    print(f"  Precision      : bf16 LoRA (load_in_4bit=False)")
    print(f"  max_seq_len    : {cfg.model.max_seq_length}")

    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(sft_checkpoint),
            max_seq_length=cfg.model.max_seq_length,
            load_in_4bit=False,     # JAMAIS True sur Qwen3.5
            dtype=dtype,
        )
    except OSError as exc:
        err = str(exc)
        if "not found" in err.lower() or "repository" in err.lower() or "adapter_config" in err.lower():
            _die(
                f"Checkpoint SFT introuvable ou invalide : {sft_checkpoint}\n"
                "  Le dossier doit contenir adapter_config.json (format PEFT standard).\n"
                "  Vérifier que le chemin pointe vers le sous-dossier 'final' ou 'checkpoint-N'."
            )
        raise

    return model, tokenizer


def apply_lora(model: "Any", cfg: Config) -> "Any":
    """Applique le PEFT LoRA via Unsloth get_peft_model (identique au SFT)."""
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
# DPOConfig + Trainer
# ---------------------------------------------------------------------------

def build_dpo_config(
    cfg: Config,
    run_name: str,
    output_dir: Path,
    use_wandb: bool,
) -> "Any":
    """Construit le DPOConfig TRL avec les hyperparamètres DPO fixes."""
    try:
        from trl import DPOConfig  # type: ignore[import]
    except ImportError:
        _die(
            "TRL non installé ou version trop ancienne.\n"
            "  pip install trl>=0.15.0\n"
            "  DPOConfig est disponible depuis trl>=0.8.0"
        )

    report_to = "wandb" if use_wandb else "none"

    return DPOConfig(
        output_dir=str(output_dir),
        run_name=run_name,
        # Hyperparamètres DPO fixes
        beta=DPO_BETA,
        learning_rate=DPO_LEARNING_RATE,
        lr_scheduler_type=DPO_LR_SCHEDULER,
        warmup_ratio=DPO_WARMUP_RATIO,
        num_train_epochs=DPO_NUM_EPOCHS,        # TOUJOURS 1
        per_device_train_batch_size=DPO_BATCH_SIZE,
        gradient_accumulation_steps=DPO_GRAD_ACCUM,
        bf16=DPO_BF16,
        fp16=False,
        max_length=DPO_MAX_LENGTH,
        max_prompt_length=DPO_MAX_PROMPT_LENGTH,
        # Optimiseur — hérite du YAML SFT (adamw_8bit fonctionne bien en DPO)
        optim=cfg.training.optim,
        # Logs & sauvegarde
        logging_steps=cfg.training.logging_steps,
        save_strategy=cfg.training.save_strategy,
        save_steps=cfg.training.save_steps,
        save_total_limit=3,
        # Reproductibilité
        seed=cfg.training.seed,
        data_seed=cfg.training.seed,
        # Tracking
        report_to=report_to,
        remove_unused_columns=False,
    )


# ---------------------------------------------------------------------------
# Résumé final DPO
# ---------------------------------------------------------------------------

def print_dpo_summary(
    trainer: "Any",
    t_start: float,
    output_dir: Path,
    run_name: str,
    n_pairs: int,
    cycle: int,
    agent: str,
) -> None:
    """Affiche le résumé post-entraînement DPO."""
    duration = timedelta(seconds=int(time.monotonic() - t_start))
    peak_vram = get_vram_peak_gb()

    final_loss: float | None = None
    avg_reward_chosen:   float | None = None
    avg_reward_rejected: float | None = None

    if hasattr(trainer, "state") and trainer.state.log_history:
        history = trainer.state.log_history

        losses = [e["loss"] for e in history if "loss" in e]
        if losses:
            final_loss = losses[-1]

        chosen_rewards   = [e["rewards/chosen"]   for e in history if "rewards/chosen"   in e]
        rejected_rewards = [e["rewards/rejected"]  for e in history if "rewards/rejected" in e]

        if chosen_rewards:
            avg_reward_chosen = sum(chosen_rewards) / len(chosen_rewards)
        if rejected_rewards:
            avg_reward_rejected = sum(rejected_rewards) / len(rejected_rewards)

    W = 65
    print(f"\n{'═' * W}")
    print("  DPO — Entraînement terminé")
    print(f"{'═' * W}")
    print(f"  Run name           : {run_name}")
    print(f"  Agent              : {agent}")
    print(f"  Cycle DPO          : {cycle} / {DPO_MAX_CYCLES}")
    print(f"  Paires utilisées   : {n_pairs:,}")
    print(f"  Durée totale       : {duration}")

    if final_loss is not None:
        print(f"  Loss DPO finale    : {final_loss:.4f}")
    if avg_reward_chosen is not None:
        print(f"  Reward chosen (moy): {avg_reward_chosen:.4f}")
    if avg_reward_rejected is not None:
        print(f"  Reward rejected (m): {avg_reward_rejected:.4f}")
    if avg_reward_chosen is not None and avg_reward_rejected is not None:
        margin = avg_reward_chosen - avg_reward_rejected
        print(f"  Margin (ch - rej)  : {margin:+.4f}", end="")
        if margin > 0:
            print("  ✓  Le modèle préfère correctement les réponses choisies")
        else:
            print("  ⚠  Margin négative — vérifier la qualité des paires")

    if peak_vram is not None:
        print(f"  VRAM peak          : {peak_vram:.2f} GB")
    print(f"  Checkpoint         : {output_dir}")

    remaining = DPO_MAX_CYCLES - cycle
    if remaining > 0:
        print(f"\n  Cycles restants    : {remaining}")
        print(f"  Prochain cycle     :")
        print(f"    python scripts/train_dpo.py \\")
        print(f"        --config configs/{agent}_team.yaml \\")
        print(f"        --pairs data/dpo_pairs/{agent}_team_pairs.jsonl \\")
        print(f"        --sft-checkpoint {output_dir}")
    else:
        print(f"\n  Limite de {DPO_MAX_CYCLES} cycles atteinte.")
        print(f"  → Reset recommandé : reprendre depuis le checkpoint SFT de base.")
        print(f"  → Supprimer {MODELS_DIR / f'{agent}_dpo_cycles.txt'} pour réinitialiser.")

    print(f"\n  Évaluation :")
    print(f"    python scripts/evaluate.py --model {agent}lith-v2-dpo-c{cycle}")
    print(f"{'═' * W}\n")


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def _die(msg: str) -> None:
    print(f"\n  ERREUR : {msg}\n", file=sys.stderr)
    sys.exit(1)


def _detect_agent(config_path: Path) -> str:
    """Déduit 'red' ou 'blue' depuis le nom du fichier de config."""
    stem = config_path.stem.lower()
    if "blue" in stem:
        return "blue"
    if "red" in stem:
        return "red"
    return "unknown"


def _resolve_sft_checkpoint(sft_arg: str) -> Path:
    """Résout --sft-checkpoint en chemin absolu."""
    p = Path(sft_arg)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.exists():
        _die(
            f"Checkpoint SFT introuvable : {p}\n"
            "  Vérifier que l'entraînement SFT a bien produit un checkpoint 'final'.\n"
            "  Commande : python scripts/train_sft.py --config configs/<agent>_team.yaml"
        )
    return p


def _resolve_pairs_path(pairs_arg: str) -> Path:
    """Résout --pairs en chemin absolu."""
    p = Path(pairs_arg)
    if not p.is_absolute():
        p = BASE_DIR / p
    return p


def _build_output_dir(agent: str, cycle: int, run_name: str | None) -> Path:
    """Construit le dossier de sortie : models/checkpoints/{agent}_dpo_cycle{N}/"""
    if run_name:
        out = MODELS_DIR / run_name
    else:
        out = MODELS_DIR / f"{agent}_dpo_cycle{cycle}"
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Entraînement DPO Qwen3.5-4B avec Unsloth (0Lith Training)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", required=True,
        help="Chemin vers le YAML de config (ex: configs/blue_team.yaml)",
    )
    parser.add_argument(
        "--pairs", required=True,
        help="Fichier JSONL de paires DPO (format: {prompt, chosen, rejected})",
    )
    parser.add_argument(
        "--sft-checkpoint", required=True, dest="sft_checkpoint",
        help="Checkpoint SFT de base (ex: models/checkpoints/pyrolith_v2_lora/final)",
    )
    parser.add_argument(
        "--run-name", default=None,
        help="Nom du run (WandB + dossier checkpoint). Auto-généré si absent.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help=f"Ignorer la limite de {DPO_MAX_CYCLES} cycles DPO (non recommandé)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Valider config + dataset sans charger le modèle ni entraîner",
    )
    parser.add_argument(
        "--wandb", action="store_true",
        help="Activer le tracking Weights & Biases (nécessite wandb installé et configuré)",
    )
    parser.add_argument(
        "--no-csv", action="store_true",
        help="Désactiver le logging CSV local",
    )
    args = parser.parse_args()

    # ── Résolution des chemins
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = BASE_DIR / config_path
    if not config_path.exists():
        _die(f"Config introuvable : {config_path}")

    sft_checkpoint = _resolve_sft_checkpoint(args.sft_checkpoint)
    pairs_path     = _resolve_pairs_path(args.pairs)

    # ── En-tête
    W = 65
    print(f"\n{'=' * W}")
    print("  0Lith Training — train_dpo.py")
    print(f"{'=' * W}")
    print(f"  Config        : {config_path.name}")
    print(f"  Paires DPO    : {pairs_path}")
    print(f"  Checkpoint SFT: {sft_checkpoint}")
    if args.dry_run:
        print("  Mode          : DRY-RUN (validation seule, pas d'entraînement)")
    if args.force:
        print(f"  --force       : limite de {DPO_MAX_CYCLES} cycles ignorée")
    print()

    # ── [1/7] Config
    print("  [1/7] Chargement de la config...")
    cfg = load_config(config_path)
    issues = validate_config(cfg)

    errors   = [i for i in issues if i.startswith("ERREUR")]
    warnings = [i for i in issues if i.startswith("AVERT")]

    for w in warnings:
        print(f"  ⚠  {w}")
    for e in errors:
        print(f"  ✗  {e}", file=sys.stderr)
    if errors:
        sys.exit(1)

    mc = cfg.model
    lc = cfg.lora
    print(f"  Modèle base     : {mc.base_model}")
    print(f"  max_seq_length  : {mc.max_seq_length}")
    print(f"  LoRA r={lc.r}, alpha={lc.lora_alpha}")
    print(f"  DPO beta        : {DPO_BETA}  |  LR : {DPO_LEARNING_RATE:.1e}  |  Epochs : {DPO_NUM_EPOCHS} (fixe)")
    print(f"  max_length      : {DPO_MAX_LENGTH}  |  max_prompt : {DPO_MAX_PROMPT_LENGTH}")

    # ── Détection de l'agent
    agent = _detect_agent(config_path)
    if agent == "unknown":
        chk_str = str(sft_checkpoint).lower()
        if "pyrolith" in chk_str or "red" in chk_str:
            agent = "red"
        elif "cryolith" in chk_str or "blue" in chk_str:
            agent = "blue"
        else:
            print(
                "  AVERTISSEMENT : impossible de détecter l'agent (red/blue) depuis le nom du config.\n"
                "  Utilisation de 'unknown' pour le compteur de cycles."
            )
    print(f"  Agent           : {agent}")

    # ── [2/7] Compteur de cycles
    print(f"\n  [2/7] Vérification des cycles DPO...")
    cycle = check_dpo_cycle_limit(agent, args.force)
    current_cycles = read_dpo_cycles(agent)
    print(f"  Cycles effectués : {current_cycles} / {DPO_MAX_CYCLES}")
    print(f"  Cycle en cours   : {cycle}")

    # ── Nom du run
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.run_name:
        run_name = args.run_name
    else:
        run_name = f"{agent}_dpo_cycle{cycle}_{ts}"
    print(f"  Run name         : {run_name}")

    # ── [3/7] Dataset
    print(f"\n  [3/7] Chargement des paires DPO...")
    dataset = load_dpo_pairs(pairs_path)
    n_pairs = len(dataset)
    print(f"  Paires chargées : {n_pairs:,}")

    if n_pairs < 50:
        print(
            f"  AVERTISSEMENT : {n_pairs} paires est très peu pour du DPO de qualité.\n"
            "    Recommandation : 500–2000 paires minimum pour un signal fiable."
        )

    if args.dry_run:
        print(f"\n  [DRY-RUN] Vérification du format (3 premières paires)...")
        for i, ex in enumerate(dataset.select(range(min(3, n_pairs)))):
            p_len = len(ex.get("prompt", ""))
            c_len = len(ex.get("chosen", ""))
            r_len = len(ex.get("rejected", ""))
            print(f"  Paire {i+1} : prompt={p_len} chars, chosen={c_len} chars, rejected={r_len} chars")
            if c_len == r_len and ex.get("chosen") == ex.get("rejected"):
                print(f"    AVERTISSEMENT : chosen == rejected pour la paire {i+1} — paire inutile")

        cycles_left = DPO_MAX_CYCLES - current_cycles
        print(f"\n  Dry-run OK — config et dataset valides.")
        print(f"  Cycle prévu    : {cycle} / {DPO_MAX_CYCLES}  ({max(0, cycles_left - 1)} restant(s) après ce cycle)")
        print(f"  Pour lancer l'entraînement : relancer sans --dry-run\n")
        sys.exit(0)

    # ── [4/7] VRAM
    print(f"\n  [4/7] Vérification VRAM...")
    check_vram(min_gb=12.0)

    # ── [5/7] Chargement du modèle
    print(f"\n  [5/7] Chargement du checkpoint SFT ({sft_checkpoint.name})...")
    t_model_start = time.monotonic()

    try:
        import torch
        torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass

    model, tokenizer = load_model_from_sft_checkpoint(sft_checkpoint, cfg)

    vram_after_model = get_vram_peak_gb()
    print(f"  Modèle chargé en {time.monotonic() - t_model_start:.1f}s", end="")
    if vram_after_model:
        print(f"  (VRAM : {vram_after_model:.1f} GB)")
    else:
        print()

    # ── [6/7] Application LoRA
    print(f"\n  [6/7] Application LoRA (r={lc.r}, alpha={lc.lora_alpha})...")
    model = apply_lora(model, cfg)

    try:
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        total     = sum(p.numel() for p in model.parameters())
        print(f"  Params entraînables : {trainable:,} / {total:,} ({trainable/total*100:.2f}%)")
    except Exception:
        pass

    # ── Setup output + logging
    output_dir = _build_output_dir(agent, cycle, args.run_name)
    log_path   = output_dir / "dpo_training_log.csv"

    callbacks: list[Any] = []
    if not args.no_csv:
        csv_cb = make_csv_logger(log_path)
        if csv_cb:
            callbacks.append(csv_cb)
            print(f"  Log CSV         : {log_path}")

    if args.wandb:
        try:
            import wandb  # type: ignore[import]
            wandb.init(project="0lith-training", name=run_name, tags=[f"dpo_cycle{cycle}", agent])
            print(f"  WandB           : activé (projet=0lith-training, run={run_name})")
        except ImportError:
            print("  WandB non installé — logging CSV uniquement.")

    # ── DPOConfig
    dpo_config = build_dpo_config(cfg, run_name, output_dir, use_wandb=args.wandb)

    # ── [7/7] DPOTrainer
    try:
        from trl import DPOTrainer  # type: ignore[import]
    except ImportError:
        _die(
            "TRL non installé ou version incompatible.\n"
            "  pip install trl>=0.15.0\n"
            "  DPOTrainer disponible depuis trl>=0.7.0"
        )

    print(f"\n  [7/7] Initialisation du DPOTrainer...")
    trainer = DPOTrainer(
        model=model,
        ref_model=None,     # None = copie interne (économie VRAM avec gradient checkpointing)
        args=dpo_config,
        train_dataset=dataset,
        tokenizer=tokenizer,
        callbacks=callbacks if callbacks else None,
    )

    # ── Entraînement
    eff_batch = DPO_BATCH_SIZE * DPO_GRAD_ACCUM
    steps_est = max(1, n_pairs // eff_batch)
    print(f"\n{'─' * W}")
    print(f"  Démarrage DPO — {run_name}")
    print(f"  {n_pairs} paires · 1 époque · eff. batch {eff_batch} · ~{steps_est} steps")
    print(f"{'─' * W}")

    t_start     = time.monotonic()
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
        trainer.train()

    except RuntimeError as exc:
        err = str(exc)
        if "out of memory" in err.lower() or "cuda" in err.lower():
            print(f"\n  ERREUR OOM (CUDA Out of Memory) :\n  {err[:400]}", file=sys.stderr)
            print(
                "\n  Solutions :\n"
                "    → Réduire DPO_MAX_LENGTH : 2048 → 1024 (modifier le script)\n"
                "    → Réduire DPO_GRAD_ACCUM : 4 → 8\n"
                "    → Fermer les autres applications GPU (Gaming Mode doit être OFF)",
                file=sys.stderr,
            )
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

    # ── Sauvegarde
    if interrupted:
        save_dir = output_dir / f"interrupted_{ts}"
        print(f"\n  Sauvegarde checkpoint interrompu → {save_dir}")
        trainer.save_model(str(save_dir))
        tokenizer.save_pretrained(str(save_dir))
        print("  Sauvegarde terminée — compteur de cycles NON incrémenté (run incomplet).")
        sys.exit(0)
    else:
        final_dir = output_dir / "final"
        trainer.save_model(str(final_dir))
        tokenizer.save_pretrained(str(final_dir))
        print(f"\n  Adapter DPO sauvegardé → {final_dir}")

    # ── Incrémenter le compteur APRÈS succès
    new_cycle_count = increment_dpo_cycles(agent)
    print(f"  Compteur de cycles mis à jour : {new_cycle_count} / {DPO_MAX_CYCLES}")

    # ── Résumé
    print_dpo_summary(
        trainer=trainer,
        t_start=t_start,
        output_dir=final_dir,
        run_name=run_name,
        n_pairs=n_pairs,
        cycle=cycle,
        agent=agent,
    )


if __name__ == "__main__":
    main()
