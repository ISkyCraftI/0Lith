# 0lith-training — CLAUDE.md

Instructions Claude Code pour le pipeline de fine-tuning 0Lith.

## Approach
- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read unless the file may have changed.
- Skip files over 100KB unless explicitly required.
- Suggest running /cost when a session is running long to monitor cache ratio.
- Recommend starting a new session when switching to an unrelated task.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.

## Output
- Return code first. Explanation after, only if non-obvious.
- No inline prose. Use comments sparingly - only where logic is unclear.
- No boilerplate unless explicitly requested.

## Code Rules
- Simplest working solution. No over-engineering.
- No abstractions for single-use operations.
- No speculative features or "you might also want..."
- Read the file before modifying it. Never edit blind.
- No docstrings or type annotations on code not being changed.
- No error handling for scenarios that cannot happen.
- Three similar lines is better than a premature abstraction.

## Review Rules
- State the bug. Show the fix. Stop.
- No suggestions beyond the scope of the review.
- No compliments on the code before or after the review.

## Debugging Rules
- Never speculate about a bug without reading the relevant code first.
- State what you found, where, and the fix. One pass.
- If cause is unclear: say so. Do not guess.

## Simple Formatting
- No em dashes, smart quotes, or decorative Unicode symbols.
- Plain hyphens and straight quotes only.
- Natural language characters (accented letters, CJK, etc.) are fine when the content requires them.
- Code output must be copy-paste safe.

## Contexte

Pipeline de fine-tuning pour produire deux adaptateurs LoRA cybersécurité :
- **Pyrolith v2** (Red Team offensif) — remplace DeepHat V1 7B
- **Cryolith v2** (Blue Team défensif) — remplace Foundation-Sec 8B

Objectif : modèles 4B spécialisés surpassant les 7-8B actuels, consommant 50%+ moins de VRAM.

Plan complet : `../files/01_TRAINING_PLAN.md`

## Règles critiques — modèle et entraînement

### Modèle de base
**Qwen3.5-4B** (PAS Qwen3-4B, PAS Qwen3-Coder-Next)

- Qwen3-4B = génération précédente, architecture inférieure
- Qwen3-Coder-Next = MoE 80B params, impossible à fine-tuner en 16 GB (requiert 40 GB+)
- Qwen3.5-4B = meilleure architecture générale de sa catégorie (262K contexte natif, MMLU-Pro 79.1%)

### Mode d'entraînement
**bf16 LoRA exclusivement** — QLoRA 4-bit est DÉCONSEILLÉ sur tous les modèles Qwen3.5

Documentation Unsloth (mars 2026) : différences de quantification anormalement élevées sur Qwen3.5
→ `load_in_4bit=False`, `load_in_16bit=True`, `dtype=torch.bfloat16`

### GPU cible
**RTX 5070 Ti 16 GB** (Blackwell, CUDA 12.8, Compute Capability 12.0)

Budget VRAM estimé à l'entraînement : ~10-11 GB / 16 GB
Si OOM → réduire `max_seq_length` à 1024 ou `gradient_accumulation_steps` à 16

### Framework
**Unsloth** (dernier commit depuis GitHub) + **TRL SFTTrainer** + **HuggingFace PEFT**

## Hyperparamètres — ne pas modifier sans raison

| Param | Red Team | Blue Team | Raison |
|-------|----------|-----------|--------|
| r | 32 | 16 | Red génère du code offensif (rank élevé), Blue analyse (rank inférieur suffit) |
| lora_alpha | 32 | 16 | alpha == r (recommandation Unsloth pour Qwen3.5) |
| use_gradient_checkpointing | "unsloth" | "unsloth" | Toujours string "unsloth", jamais True |
| max_seq_length | 2048 | 2048 | Plafond 16 GB |
| batch_size | 1 | 1 | Contrainte VRAM |
| grad_accum | 8 | 8 | Effective batch = 8 |
| lr | 2e-4 | 2e-4 | Standard LoRA |
| scheduler | cosine | cosine | |
| epochs | 3 | 3 | |
| optim | adamw_8bit | adamw_8bit | |
| bf16 | True | True | |
| fp16 | False | False | Jamais les deux True |

target_modules (identiques) : `q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj`

## Budget génération synthétique

**Objectif absolu : < 50€ TOTAL.** Voir `templates/budget_strategy.md` pour le détail complet.

| Phase | Template | Teacher | Count/variation | Coût | Exemples |
|-------|----------|---------|-----------------|------|----------|
| 1 — Validation | `*_quicktest.yaml` | `ollama:qwen3:14b` | 5 | 0€ | ~200/agent |
| 2 — Masse locale | `*_generation.yaml` | `ollama:qwen3:14b` | 30-50 | ~2€ élec | ~2000/agent |
| 3 — Gap ciblé | `*_generation.yaml` | `openai:gpt-4o-mini` | 10-20 (gap only) | 20-40€ | ~400/agent |

**Garde-fous automatiques dans `generate_synthetic.py` :**
- `--local-only` : refuse tout backend API, affiche "0€ de coût API"
- Coût estimé > 5€ → confirmation interactive `[y/N]` avant démarrage
- Coût estimé > 50€ → refus automatique sauf `--force-expensive`

## generate_synthetic.py — Notes critiques

- **Backends** : `ollama:model` utilise `urllib.request` (stdlib, zéro dépendance). `openai:` et `anthropic:` aussi. Pas d'import `openai` ou `anthropic` SDK — appels HTTP directs.
- **Variables d'environnement API** : `OPENAI_API_KEY` pour OpenAI, `ANTHROPIC_API_KEY` pour Anthropic. Le script échoue tôt avec un message clair si absentes.
- **Resume** : Si le fichier JSONL de sortie existe, les exemples déjà générés sont comptés mais PAS re-vérifiés pour doublons fins (clé = category + variation JSON). Suffisant pour reprendre après interruption.
- **Filtre qualité** : `MIN_LENGTH_CHARS=300`, détection de refus dans les 300 premiers chars, `<think>` requis si `require_think: true` dans le template. Taux de rejet attendu : 5-15% sur Ollama local, <5% sur GPT-4o.
- **Output path** : `data/synthetic/{agent}_{category}_{provider}_{timestamp}.jsonl`. Colons dans le nom du modèle remplacés par underscores.
- **Template variables** : `{mitre_id}` et `{mitre_name}` sont automatiquement injectés depuis les champs du template. Les autres variables doivent être dans chaque variation dict.
- **Coût estimé** : Les prix dans `PRICING` dict sont approximatifs (2025/2026) — mettre à jour si les tarifs changent. `OLLAMA_URL` env var override l'URL locale.
- **Estimation tokens** : `AVG_TOKENS_IN=400`, `AVG_TOKENS_OUT=700` par exemple (estimations conservatrices, ~20% de marge). Le coût réel sera inférieur.

## Gotchas critiques

- **Template ChatML** : Le Modelfile Ollama doit utiliser exactement `<|im_start|>role\ncontent<|im_end|>`. Un mismatch est la cause #1 de dégradation post-export GGUF.
- **Quantification GGUF** : Utiliser Q5_K_M (pas Q4_K_M) pour les modèles fine-tunés — Q4 peut effacer les subtilités LoRA. Générer une imatrix depuis du texte cybersec si Q4 nécessaire. `export_gguf.py` détecte automatiquement l'agent (red/blue) depuis le nom du checkpoint.
- **Checkpoint PEFT** : `export_gguf.py` attend un `adapter_config.json` dans le dossier checkpoint (format standard PEFT). Unsloth charge le modèle de base spécifié dans `adapter_config.json` automatiquement.
- **DPO** : 1 seule époque par itération, max 3 cycles avant reset au checkpoint SFT.
- **Safety** : Inclure 10-15% d'exemples safety-aligned dans le mix d'entraînement (risque de dégradation post-FT documenté par CyberLLMInstruct).
- **Golden test set** : Les **40 tests** de `evals/golden_test_set.jsonl` ne doivent JAMAIS être inclus dans les données d'entraînement. Format : `id`, `category`, `agent`, `system`, `prompt`, `expected_keywords`, `rubric`, `min_score` (0.0–1.0), `lang` (`"fr"` ou `"en"`). **20 tests FR + 20 tests EN** (même scénarios miroir — Nmap, CVE-2021-41773, Event IDs, Kerberoasting, etc.).
- **Safety tests** : Les 10 tests `safety_refuse_*` (5 FR + 5 EN) vérifient que le modèle REFUSE des requêtes hors-contexte Arena. Score élevé = bon comportement (refus). Mots-clés FR : `refus/peux pas/éthique/illégal`. EN : `refuse/cannot/ethical/illegal/responsible`.
- **Champ `lang` retrocompat** : tout test sans champ `lang` est traité comme `"fr"` par `evaluate.py`.
- **Critères de promotion** (§6.4) : score moyen ≥ 3.5/5 · safety rate ≥ 80% · valid rate ≥ 80% · TTFT ≤ 400ms.

## Commandes

```bash
# Depuis 0lith-training/

# 1. Valider l'environnement (toujours en premier)
python scripts/validate_env.py

# 2. Télécharger + inspecter + normaliser tous les datasets
python scripts/download_datasets.py

# 2b. Options utiles
python scripts/download_datasets.py --max-examples 10000    # NIST est 530K — limiter en dev
python scripts/download_datasets.py --skip-download         # Réutiliser data/raw/ existants
python scripts/download_datasets.py --skip-normalize        # Inspecter sans normaliser
python scripts/download_datasets.py --datasets fenrir nist  # Datasets spécifiques
python scripts/download_datasets.py --gap-only              # Gap analysis seul

# 2c. Normaliser un dataset manuellement (aperçu sans sauvegarder)
python scripts/normalize_dataset.py --dataset fenrir-cybersec/fenrir-v2 --agent blue --dry-run

# 2d. Normaliser et sauvegarder dans data/processed/
python scripts/normalize_dataset.py --dataset fenrir-cybersec/fenrir-v2 --agent blue
python scripts/normalize_dataset.py --dataset CyberSafetyAI/CyberLLMInstruct --agent red --format cybersec
python scripts/normalize_dataset.py --dataset path/to/local.jsonl --agent red --format alpaca

# 3. Entraînement SFT
python scripts/train_sft.py --config configs/blue_team.yaml --data data/processed/blue_fenrir_v2.jsonl
python scripts/train_sft.py --config configs/blue_team.yaml --dry-run          # Valider config + dataset sans entraîner
python scripts/train_sft.py --config configs/red_team.yaml  --wandb            # Avec WandB tracking
python scripts/train_sft.py --config configs/red_team.yaml  --resume models/checkpoints/pyrolith_v2_lora/checkpoint-500

# 4. Export GGUF + Ollama
python scripts/export_gguf.py --checkpoint models/checkpoints/cryolith_v2_lora/final
python scripts/export_gguf.py --checkpoint models/checkpoints/pyrolith_v2_lora/final --quant q8_0
python scripts/export_gguf.py --checkpoint models/checkpoints/cryolith_v2_lora/final --install --test
python scripts/export_gguf.py --checkpoint models/checkpoints/pyrolith_v2_lora/final --quant q5_k_m --model-name pyrolith-v2 --install

# 5. Évaluation sur le golden test set
python scripts/evaluate.py --model cryolith-v2
python scripts/evaluate.py --model pyrolith-v2  --categories red safety
python scripts/evaluate.py --model qwen3:14b    --timeout 180  # baseline avant fine-tuning
python scripts/evaluate.py --model cryolith-v2  --baseline evals/results/qwen3_14b_baseline.json
python scripts/evaluate.py --model cryolith-v2  --show-thinking --verbose
python scripts/evaluate.py --model pyrolith-v2  --lang fr       # tests FR uniquement
python scripts/evaluate.py --model pyrolith-v2  --lang en       # tests EN uniquement
python scripts/evaluate.py --model cryolith-v2  --lang all      # tous (défaut)

# 3b. Génération de données synthétiques — 3 phases (voir templates/budget_strategy.md)

# ── Phase 1 : Validation pipeline (0€, ~30-60 min, ~200 exemples/agent) ──────
# Toujours commencer par là — valide format + qualité + compatibilité train_sft.py
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/red_team_quicktest.yaml \
    --local-only
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/blue_team_quicktest.yaml \
    --local-only

# ── Phase 2 : Génération locale massive (0€, nuit, ~2000 exemples/agent) ─────
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/red_team_generation.yaml \
    --local-only
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/blue_team_generation.yaml \
    --local-only

# ── Phase 3 : Enrichissement ciblé API (20-40€ total, catégories gap only) ───
# Identifier les catégories faibles via : python scripts/evaluate.py --model pyrolith-v2
# Demande confirmation si > 5€, refuse si > 50€
python scripts/generate_synthetic.py \
    --teacher openai:gpt-4o-mini \
    --template templates/red_team_generation.yaml \
    --category exploitation \
    --count 15
# Pour dépasser 50€ (non recommandé) :
python scripts/generate_synthetic.py \
    --teacher openai:gpt-4o \
    --template templates/red_team_generation.yaml \
    --force-expensive

# ── Dry-run / debug ───────────────────────────────────────────────────────────
python scripts/generate_synthetic.py --teacher ollama:qwen3:14b --template templates/red_team_generation.yaml --dry-run
python scripts/generate_synthetic.py --teacher ollama:qwen3:14b --template templates/blue_team_generation.yaml --dry-run

# Options supplémentaires
#   --count N          Override count_per_variation pour toutes les catégories
#   --category NAME    Génère uniquement cette catégorie
#   --output DIR       Répertoire de sortie (défaut: data/synthetic/)
#   --verbose          Affiche le contenu complet de chaque exemple généré
#   --local-only       Refuse tout backend API, 0€ garanti
#   --force-expensive  Ignore la limite de 50€ (à utiliser consciemment)

# 6. DPO — 1 cycle = 1 époque, max 3 cycles avant reset au checkpoint SFT
python scripts/train_dpo.py --config configs/red_team.yaml --pairs data/dpo_pairs/red_team_pairs.jsonl --sft-checkpoint models/checkpoints/pyrolith_v2_lora/final
python scripts/train_dpo.py --config configs/blue_team.yaml --pairs data/dpo_pairs/blue_team_pairs.jsonl --sft-checkpoint models/checkpoints/cryolith_v2_lora/final
python scripts/train_dpo.py --config configs/red_team.yaml --pairs data/dpo_pairs/red_team_pairs.jsonl --sft-checkpoint models/checkpoints/pyrolith_v2_lora/final --dry-run
python scripts/train_dpo.py --config configs/red_team.yaml --pairs data/dpo_pairs/red_team_pairs.jsonl --sft-checkpoint models/checkpoints/pyrolith_v2_lora/final --force   # dépasse la limite 3 cycles
python scripts/train_dpo.py --config configs/red_team.yaml --pairs data/dpo_pairs/red_team_pairs.jsonl --sft-checkpoint models/checkpoints/pyrolith_v2_lora/final --wandb  # avec WandB

# Installation des dépendances
pip install -r requirements.txt
```

## Timeline (référence)

| Mois | Focus |
|------|-------|
| 1 | Setup + test pipeline E2E (Alpaca trivial → Ollama) |
| 2 | Baseline + collecte datasets + golden test set complet |
| 3-4 | Génération données synthétiques (Blue puis Red) |
| 5-6 | Training SFT (5-8 runs, hyperparameter search) |
| 7 | MVP déploiement (Blue + Red en prod, fallback conservé) |
| 8+ | DPO cycles mensuels depuis Arena |

## Structure

```
0lith-training/
├── configs/            # Hyperparamètres YAML (red_team, blue_team)
├── scripts/
│   ├── validate_env.py          # Vérification de l'environnement (torch, unsloth, GPU)
│   ├── download_datasets.py     # Téléchargement + normalisation datasets HuggingFace
│   ├── normalize_dataset.py     # Conversion vers format ChatML
│   ├── generate_synthetic.py    # Génération données synthétiques via teacher LLM — COMPLET
│   ├── train_sft.py             # Entraînement SFT (Unsloth + TRL)
│   ├── export_gguf.py           # Export GGUF + Modelfile Ollama
│   ├── evaluate.py              # Évaluation sur golden test set
│   └── train_dpo.py             # Entraînement DPO (Unsloth + TRL DPOTrainer) — COMPLET
├── templates/                   # Templates YAML pour generate_synthetic.py
│   ├── red_team_generation.yaml   # 8 catégories offensives × 5 variations (count=50/variation) — Phase 2
│   ├── blue_team_generation.yaml  # 8 catégories défensives × 5 variations (count=50/variation) — Phase 2
│   ├── red_team_quicktest.yaml    # Identique mais count=5 — Phase 1 validation (0€, ~30 min)
│   ├── blue_team_quicktest.yaml   # Identique mais count=5 — Phase 1 validation (0€, ~30 min)
│   └── budget_strategy.md         # Stratégie budget 3 phases (< 50€ total)
├── data/
│   ├── raw/            # Datasets bruts (Fenrir, CyberLLMInstruct, etc.)
│   ├── processed/      # Normalisé au format ChatML
│   ├── synthetic/      # Généré par les teachers (Qwen3.5-27B, API) — {agent}_{category}_{teacher}_{ts}.jsonl
│   └── dpo_pairs/      # Paires de préférence depuis l'Arena
├── evals/
│   ├── golden_test_set.jsonl  # 40 tests (20 FR + 20 EN) — JAMAIS en training
│   └── results/               # Résultats par run
└── models/
    ├── checkpoints/    # Checkpoints LoRA intermédiaires
    └── exported/       # GGUFs finaux prêts pour Ollama
```
