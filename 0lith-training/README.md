# 0Lith Training — Pipeline de Fine-Tuning Cybersécurité

Pipeline de fine-tuning pour produire deux adaptateurs LoRA spécialisés sur base **Qwen3.5-4B**, déployables via Ollama sur RTX 5070 Ti 16 GB.

> Plan complet : [`../files/01_TRAINING_PLAN.md`](../files/01_TRAINING_PLAN.md)

---

## Objectif

Remplacer les agents cybersécurité actuels de 0Lith par des modèles plus légers, plus rapides et spécialisés :

| Agent | Actuel | Cible | VRAM actuelle | VRAM cible |
|-------|--------|-------|--------------|------------|
| Pyrolith (Red) | DeepHat V1 7B | **Pyrolith v2** (Qwen3.5-4B + LoRA r=32) | ~5 GB | ~3 GB |
| Cryolith (Blue) | Foundation-Sec 8B | **Cryolith v2** (Qwen3.5-4B + LoRA r=16) | ~5 GB | ~3 GB |

Base partagée Qwen3.5-4B : les deux adaptateurs hot-swappent sur le même jeu de poids en VRAM (~8 GB bf16). Switch quasi-instantané.

---

## Prérequis

- **GPU** : NVIDIA RTX 5070 Ti 16 GB (ou équivalent VRAM >= 14 GB)
- **CUDA** : 12.8+ (Blackwell)
- **Python** : 3.12
- **Ollama** : installé et démarré (service Windows ou `ollama serve`)
- **Unsloth** : depuis le repo Git (pas PyPI — support Qwen3.5 + CUDA 12.8)

```bash
pip install -r requirements.txt
```

---

## Workflow en 5 étapes

### Étape 1 — Valider l'environnement

```bash
python scripts/validate_env.py
```

Vérifie CUDA, VRAM, version CUDA, Unsloth, Ollama. Exit 0 si tout OK.

### Étape 2 — Préparer les données

Placer les datasets bruts dans `data/raw/`, puis utiliser `normalize_dataset.py` pour les convertir au format ChatML dans `data/processed/`.

```bash
# Aperçu (3 exemples, sans sauvegarder)
python scripts/normalize_dataset.py --dataset fenrir-cybersec/fenrir-v2 --agent blue --dry-run

# Conversion complète (auto-détection de format)
python scripts/normalize_dataset.py --dataset fenrir-cybersec/fenrir-v2 --agent blue
python scripts/normalize_dataset.py --dataset CyberSafetyAI/CyberLLMInstruct --agent red

# Fichier local
python scripts/normalize_dataset.py --dataset data/raw/local_dataset.jsonl --agent red --format alpaca
```

Formats supportés : `alpaca`, `sharegpt`, `qa`, `cybersec` (Fenrir, CyberLLMInstruct, AttackQA, Trendyol), `auto` (défaut).

Format ChatML produit :
```json
{
  "messages": [
    {"role": "system", "content": "Tu es Cryolith..."},
    {"role": "user", "content": "<question cybersec>"},
    {"role": "assistant", "content": "<think>\n[raisonnement]\n</think>\n\n<réponse>"}
  ]
}
```

Datasets recommandés : Fenrir v2.0, CyberLLMInstruct, Trendyol Defense v2, AttackQA, SigmaHQ.

### Étape 3 — Entraînement SFT

```bash
# Blue Team d'abord (plus immédiatement utile)
python scripts/train_sft.py --config configs/blue_team.yaml --data data/processed/blue_team.jsonl

# Red Team ensuite
python scripts/train_sft.py --config configs/red_team.yaml --data data/processed/red_team.jsonl
```

> Script non encore implémenté — voir [`files/01_TRAINING_PLAN.md`](../files/01_TRAINING_PLAN.md) §3.2

### Étape 4 — Export GGUF + déploiement Ollama

```bash
python scripts/export_gguf.py --config configs/blue_team.yaml --checkpoint models/checkpoints/cryolith_v2_lora
python scripts/export_gguf.py --config configs/red_team.yaml  --checkpoint models/checkpoints/pyrolith_v2_lora
```

> Script non encore implémenté — voir [`files/01_TRAINING_PLAN.md`](../files/01_TRAINING_PLAN.md) §5.2

### Étape 5 — Évaluation

```bash
python scripts/evaluate.py --model cryolith-v2 --golden-set evals/golden_test_set.jsonl
python scripts/evaluate.py --model pyrolith-v2 --golden-set evals/golden_test_set.jsonl
```

Critères de promotion vers production :
- CyberMetric-80 >= modèle actuel (Foundation-Sec / DeepHat baseline)
- Score golden set moyen >= 3.5 / 5.0
- Prompt injection resistance >= 0.80
- Latence premier token <= 50% du modèle actuel
- 3 sessions Arena sans crash

> Script non encore implémenté — voir [`files/01_TRAINING_PLAN.md`](../files/01_TRAINING_PLAN.md) §6

---

## Structure des dossiers

```
0lith-training/
├── CLAUDE.md              # Instructions Claude Code (règles critiques)
├── README.md              # Ce fichier
├── requirements.txt       # Dépendances Python
├── configs/
│   ├── red_team.yaml      # Hyperparamètres Pyrolith v2 (r=32)
│   └── blue_team.yaml     # Hyperparamètres Cryolith v2 (r=16)
├── scripts/
│   ├── validate_env.py       # Vérification environnement (CUDA, VRAM, Unsloth, Ollama)
│   ├── normalize_dataset.py  # Normalisation ChatML (Alpaca/ShareGPT/QA/cybersec → ChatML)
│   ├── train_sft.py          # SFT générique (stub — Mois 5-6)
│   ├── train_dpo.py          # DPO Purple Team (stub — Mois 8+)
│   ├── export_gguf.py        # Merge LoRA + GGUF + Ollama (stub — Mois 7)
│   └── evaluate.py           # Évaluation golden set (stub — Mois 5+)
├── data/
│   ├── raw/               # Datasets bruts téléchargés
│   ├── processed/         # Normalisé au format ChatML
│   ├── synthetic/         # Généré par les teachers (Qwen3.5-27B, API)
│   └── dpo_pairs/         # Paires de préférence depuis l'Arena
├── evals/
│   ├── golden_test_set.jsonl  # 50-100 prompts (JAMAIS en training)
│   └── results/               # Résultats par run
└── models/
    ├── checkpoints/       # Checkpoints LoRA pendant l'entraînement
    └── exported/          # GGUFs finaux prêts pour Ollama
```

---

## Contraintes importantes

- **bf16 LoRA uniquement** — QLoRA 4-bit déconseillé par Unsloth sur Qwen3.5 (différences de quantification anormalement élevées)
- **use_gradient_checkpointing = "unsloth"** — string, jamais `True`
- **Quantification GGUF = Q5_K_M** — Q4 peut effacer les subtilités LoRA sur modèles fine-tunés
- **Template ChatML** — ne pas modifier le template Qwen3.5 dans le Modelfile Ollama
- **Golden test set** — ne jamais inclure `evals/golden_test_set.jsonl` dans les données d'entraînement
- **DPO** — 1 seule époque par cycle, max 3 cycles avant reset au checkpoint SFT

---

## Sécurité et éthique

L'adaptateur Red Team (Pyrolith v2) est soumis à des contraintes strictes :

- Opère exclusivement dans le contexte Arena de 0Lith (simulation contrôlée, token de session)
- Données d'entraînement limitées aux techniques connues et documentées (MITRE ATT&CK)
- 10% du dataset Red Team validé manuellement avant inclusion
- 10-15% d'exemples safety-aligned dans le mix d'entraînement
- Distribué exclusivement avec 0Lith (AGPL-3.0), jamais comme modèle standalone

---

*Licence : AGPL-3.0 — Projet 0Lith*
