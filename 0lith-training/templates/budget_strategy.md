# Stratégie Budget — Génération de données synthétiques

**Objectif absolu : rester sous 50€ TOTAL pour toute la génération.**

---

## Phase 1 — Validation pipeline (0€)

**Quand :** Avant toute génération massive. Toujours faire ça en premier.

**Template :** `templates/red_team_quicktest.yaml` et `templates/blue_team_quicktest.yaml`

| Paramètre           | Valeur                  |
|---------------------|-------------------------|
| count_per_variation | 5                       |
| teacher             | `ollama:qwen3:14b`      |
| coût                | 0€ (local)              |
| durée estimée       | ~30-60 min              |
| résultat            | ~80 exemples par agent  |

**Calcul :** 8 catégories × 5 variations × 5 exemples = 200 exemples/agent

**But :**
- Vérifier que le format ChatML est correct (messages + metadata)
- Vérifier que le filtrage qualité fonctionne (require_think, MIN_LENGTH_CHARS)
- Vérifier que `train_sft.py` accepte les données sans erreur
- Identifier les catégories qui produisent le plus de rejets (signal pour Phase 3)

```bash
# Phase 1 — Red Team
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/red_team_quicktest.yaml \
    --local-only

# Phase 1 — Blue Team
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/blue_team_quicktest.yaml \
    --local-only

# Valider que train_sft.py accepte le résultat
python scripts/train_sft.py \
    --config configs/red_team.yaml \
    --data data/synthetic/ \
    --dry-run
```

---

## Phase 2 — Génération locale massive (0€)

**Quand :** Après validation Phase 1. Lancer la nuit.

**Template :** `templates/red_team_generation.yaml` et `templates/blue_team_generation.yaml`

| Paramètre           | Valeur                    |
|---------------------|---------------------------|
| count_per_variation | 30-50 (défaut dans YAML)  |
| teacher             | `ollama:qwen3:14b`        |
| coût                | 0€ + ~2€ électricité      |
| durée estimée       | 8-12h (nuit)              |
| résultat            | ~2000 exemples par agent  |

**Calcul :** 8 catégories × 5 variations × 50 exemples = 2000 exemples/agent

**Tips pour la nuit :**
- Lancer dans un terminal tmux/screen (ne pas fermer le terminal)
- Le script reprend automatiquement si interrompu (resume par clé category+variation)
- Surveiller le taux de rejet dans le résumé final — si > 20%, investiguer

```bash
# Phase 2 — Red Team (nuit)
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/red_team_generation.yaml \
    --local-only

# Phase 2 — Blue Team (nuit suivante ou en parallèle)
python scripts/generate_synthetic.py \
    --teacher ollama:qwen3:14b \
    --template templates/blue_team_generation.yaml \
    --local-only
```

---

## Phase 3 — Enrichissement ciblé API (~20-40€)

**Quand :** Après avoir évalué les modèles SFT sur le golden test set.
Utiliser UNIQUEMENT pour les catégories identifiées comme faibles par l'évaluation.

**Teacher recommandé :** `openai:gpt-4o-mini` — meilleur rapport qualité/prix

| Paramètre           | Valeur                          |
|---------------------|----------------------------------|
| count_per_variation | 10-20 (par catégorie gap)        |
| teacher             | `openai:gpt-4o-mini`            |
| coût/1M tokens      | $0.15 in / $0.60 out            |
| coût estimé total   | 20-40€                          |
| résultat            | ~300-500 exemples haute qualité  |

**Processus décisionnel Phase 3 :**

```
1. Entraîner SFT avec données Phase 1+2
2. Évaluer : python scripts/evaluate.py --model pyrolith-v2
3. Identifier les catégories avec score < 3.0/5.0
4. Générer uniquement ces catégories avec --category + API
5. Ré-entraîner avec le mix Phase 1+2+3
```

```bash
# Exemple : catégorie "exploitation" identifiée comme faible
python scripts/generate_synthetic.py \
    --teacher openai:gpt-4o-mini \
    --template templates/red_team_generation.yaml \
    --category exploitation \
    --count 15

# Si la confirmation s'affiche, vérifier le montant avant d'accepter
```

---

## Budget estimé total

| Phase  | Coût      | Exemples       | Notes                              |
|--------|-----------|----------------|------------------------------------|
| 1      | 0€        | ~200/agent     | Validation pipeline uniquement     |
| 2      | ~2€       | ~2000/agent    | Électricité RTX 5070 Ti ~200W×10h  |
| 3      | 20-40€    | ~400/agent     | Uniquement les catégories en gap   |
| Buffer | 10-15€    | —              | Tests, re-runs, erreurs            |
| **Total** | **< 50€** | ~2600/agent | Largement suffisant pour fine-tuning de qualité |

---

## Garde-fous automatiques (dans generate_synthetic.py)

Le script implémente trois niveaux de protection :

1. **`--local-only`** : refuse tout backend non-ollama, affiche "0€ de coût API"
2. **Estimation > 5€** : demande confirmation interactive `[y/N]` avant de démarrer
3. **Estimation > 50€** : refuse complètement sauf `--force-expensive` (flag de sécurité)

**Estimation de coût** (avant de lancer) :
- Tokens input estimés : 400 tokens/exemple (system + user prompt)
- Tokens output estimés : 700 tokens/exemple (réponse teacher)
- Ces estimations sont conservatrices (+20% de marge)

---

## Règles de bon sens

- **Ne jamais lancer avec `--teacher openai:gpt-4o` sans avoir calculé le coût** (10x plus cher que gpt-4o-mini)
- **Ne jamais lancer Anthropic sans vérifier le budget restant** (claude-sonnet-4-5 = 3$/1M in)
- **Toujours tester avec `--dry-run` d'abord** quand on change de template ou de count
- **Le golden test set (evals/golden_test_set.jsonl) ne doit jamais être dans les données d'entraînement**
- **Si le taux de rejet local > 25%**, augmenter la température à 0.9 ou changer de modèle local
