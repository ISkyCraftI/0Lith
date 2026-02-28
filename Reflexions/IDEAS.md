# 0Lith — Backlog d'idées

> Compilé depuis toutes les conversations du projet (9 fév – 28 fév 2026).
> Légende : ✅ Fait · 🔄 En cours · ⬜ À faire · 💡 Idée brute

---

## 1. INTERFACE & UX

### Sidebar & Navigation
- ⬜ **Onglet Agents** : séparer la liste des agents dans un onglet dédié (centre de contrôle pour changer de modèles, voir les statuts, gérer les docks)
- ⬜ **Onglet Code** : onglet type Claude/Cursor pour voir le code généré par Aerolith directement dans l'app
- ⬜ **Suppression de conversations** : bouton supprimer sur chaque session + sélection multiple (pas comme ChatGPT)
- ✅ **Historique des sessions** : sidebar avec preview + date relative
- ⬜ **Cycle de vie des sessions** : auto-refresh après envoi, nouvelle session via "+", restauration au clic

### Logo & Identité visuelle
- ⬜ **OLithEye animé** : composant SVG avec pupille qui change de couleur selon l'agent actif
  - 5 états : idle (clignements), thinking (scan gauche-droite), responding (pupille dilatée), sleeping (œil fermé), gaming (grisé)
  - Transition couleur 300ms entre agents
  - Tailles : 24px (bulles), 32px (sidebar), 120px (écran d'accueil)
  - `requestAnimationFrame` pour la dérive, CSS transitions, pause quand onglet caché
- ⬜ **Œil en bas à droite** : indicateur system tray que 0Lith est actif

### Chat
- ✅ Routage visible ("Routé vers Monolith")
- ✅ Couleur + emoji par agent
- ✅ Support Markdown + code blocks
- ✅ Bouton Stop generation
- ✅ Streaming des réponses
- ⬜ **Indicateur de chargement Aerolith** : "⏳ Aerolith réfléchit... (30B, peut prendre plusieurs minutes)"
- ⬜ **Timeout gracieux** : "L'agent met plus de temps que prévu..."

### Status Bar
- ✅ Indicateurs Backend / Ollama / Qdrant
- ⬜ **VRAM en temps réel** dans la barre
- ⬜ **Bouton Gaming Mode** 🎮 dans la status bar

---

## 2. GAMING MODE & VRAM

- ✅ **Gaming Mode** : toggle qui décharge tous les modèles de la VRAM (keep_alive=0)
- ✅ **Bouton toggle** dans la sidebar + menu system tray
- ⬜ **3 modes VRAM granulaires** :
  - Normal : agents chargés à la demande (~6-11 Go)
  - Léger : seulement Hodolith 1.7B (~2 Go)
  - Gaming : 0 Go VRAM (actuellement implémenté)
- 💡 **Auto-détection** : détecter `LeagueClient.exe` / processus GPU lourds → basculer automatiquement en mode gaming
- 💡 **Profil joueur** : LoL stats, habitudes de jeu, intégré dans la mémoire (Mois 4-5)

---

## 3. SYSTÈME PROACTIF (Background Loop)

### olith_watcher.py
- ✅ Fichier créé, base fonctionnelle, lancé en parallèle par Tauri
- ✅ **File Watcher** : surveillance des dossiers de projets via watchdog
- ✅ **Panneau Suggestions** dans l'UI : SuggestionsBar affiche les suggestions Niveau 1
- ⬜ **Shadow Thinking** : Hodolith observe un fichier modifié → extrapole les prochaines étapes → stocke des suggestions dans Mem0 tagées `shadow_thinking`
- ⬜ **Boucle d'apprentissage** :
  - User accepte → Mem0 : "prédiction correcte"
  - User modifie → Mem0 : "préfère Y plutôt que X"
  - User rejette → Mem0 : "mauvaise direction"
  - Si 3 suggestions ignorées d'affilée → ralentir la fréquence

### Niveaux d'autonomie
- ⬜ **Niveau 0 — Observer** : lire fichiers, analyser, mémoriser (automatique)
- ⬜ **Niveau 1 — Suggérer** : proposer des actions, notifications, briefs (automatique avec notification)
- ⬜ **Niveau 2 — Agir** : écrire du code, envoyer un message, modifier un fichier (JAMAIS sans permission humaine)

### Anticipation
- 💡 **Prédiction d'idées** : après des mois de mémoire, 0Lith connaît tes cycles ("il commence toujours un projet le lundi", "il code mieux le soir", "quand il mentionne un jeu, il finit par vouloir reproduire la mécanique")
- 💡 **Emploi du temps intelligent** : "Vous n'avez rien de 20 à 21h, ça vous dit d'avancer sur l'app Tauri ?"
- 💡 **Exercices adaptés** : "DS de C++ dans 2 jours → exercices progressifs sans submerger"

---

## 4. DOCK — AGENTS ENFICHABLES

### Architecture
- ⬜ **Config YAML par agent** : ajouter un agent = un fichier YAML, pas une refonte du code
  ```yaml
  id: storylith
  name: Storylith
  role: Narrateur
  model: qwen3:14b
  emoji: "📖"
  color: "#A855F7"
  dock: gamedev
  ```
- ⬜ **Système de docks** : groupes logiques d'agents (Cybersécurité, Game Dev, Personnel)

### Dock Cybersécurité (V1 — actuel)
- ✅ Hodolith (dispatcher 1.7B)
- ✅ Monolith (orchestrateur 14B)
- ✅ Aerolith (codeur 30B)
- ✅ Cryolith (défensif 8B)
- ✅ Pyrolith (offensif 7B, Docker)

### Dock Game Dev (Mois 3+)
- ⬜ **Storylith** : narration, worldbuilding, dialogues (Qwen3-14B)
- ⬜ **Artlith** : direction artistique, briefs d'assets, descriptions visuelles
- ⬜ **Gamelith** : code gameplay GDScript/C#, mécanniques de jeu
- 💡 **Auto-déploiement** : Hodolith détecte un `gdd.md` dans un nouveau dossier → propose de déployer Storylith + Artlith + Gamelith

### Dock Personnel (Mois 4+)
- ⬜ **Schedulith** : planning, emploi du temps, routines détectées depuis iCal/TimeTree
- ⬜ **Econolith** : prévisionnel financier, analyse de dépenses (CSV bancaire, pas d'API)
  - Corrélation avec calendrier (événements coûteux, vacances)
  - Projections et conseils de gestion

### Sparring
- ⬜ **Sparring nocturne** : "entre 2h et 6h, Pyrolith vs Cryolith s'entraînent sur des CVE récentes, résumé le matin"

---

## 5. MÉMOIRE & DONNÉES

### Mem0 / Qdrant
- ✅ Mémoire partagée entre agents
- ✅ Filtrage des messages triviaux (< 50 chars, salut/merci/ok)
- ✅ Metadata timestamp sur chaque mémoire
- ⬜ **Garbage collection 30 jours** : TTL pour les mémoires de type "conversation"
- ⬜ **Intégrité mémoire Cryolith** : SHA-256 par vecteur, provenance tagging (user_input, agent_generated, external_data), vérification horaire quand idle, write-ahead log

### Google Takeout — Pipeline d'ingestion
- ⬜ **Couche 1** (haute valeur) : Calendar → patterns/routines, Contacts → graphe social, Drive → cours/projets/notes, YouTube → catégories d'intérêt
- ⬜ **Couche 2** (valeur moyenne) : Gmail → emails envoyés + starred seulement, Search history → thèmes récurrents, Chrome bookmarks
- ⬜ **Couche 3** (contextuel) : Location history → patterns, Photos metadata (dates/lieux, pas les images)
- 💡 Principe : "ne stocke jamais le texte brut, stocke des résumés, des patterns, des profils"
- 💡 Pipeline en job de nuit (GPU libre, pas de gaming)

### Données personnelles
- 💡 **Apple Health** : données Santé connectées pour optimisation quotidienne
- 💡 **TimeTree / iCal** : calendrier pour suggestions proactives
- 💡 **Chiffrement E2E** obligatoire pour les données santé (RGPD)

### Mémoire à 5 niveaux
- ⬜ Mémoire de travail (fenêtre de contexte LLM)
- ✅ Mémoire court terme (Mem0 → Qdrant)
- ⬜ Mémoire long terme (consolidation → Kuzu graphe)
- ⬜ Mémoire sémantique (knowledge graph permanent)
- ⬜ Mémoire épisodique (historique horodaté pour raisonnement par cas)

---

## 6. RÉSEAU & MULTI-MACHINE

- ⬜ **Tailscale** : VPN mesh WireGuard pour lier desktop + Lenovo Yoga 7 + iPhone 13
- 💡 **Headscale** : remplacement self-hosted du serveur Tailscale (souveraineté maximale)
- 💡 **Monitoring mobile** : Prometheus + Grafana accessible via Tailscale depuis iPhone/laptop
- 💡 **Swarm** : cluster de GPUs si ajout d'une seconde RTX 5070 Ti → tensor parallelism via vLLM

---

## 7. INTÉGRATIONS EXTERNES

- ⬜ **MCP Server pour Zed** : exposer les agents comme outils MCP, Zed appelle Aerolith/Monolith/Cryolith directement (2-3 jours d'effort)
- ✅ **System Tray** : icône dans la barre système, menu Show/Hide/Gaming Mode/Quit, app en arrière-plan
- 💡 **Accès internet pour les agents** : recherche web, consultation d'API externes, communication avec Claude ou d'autres IA si trop perdus
- 💡 **TryHackMe via API/VPN** : intégration pour les exercices cybersec

---

## 8. SÉCURITÉ & ISOLATION

- ✅ Sandbox filesystem (validate_path, whitelist, symlink check)
- ✅ Lane queue (threading.Lock pour cmd_chat)
- ✅ Cancel IPC gracieux (event + fallback kill)
- ✅ Retry + circuit breaker (Ollama, Mem0)
- ⬜ **Pyrolith en Firecracker microVM** : noyau dédié, réseau isolé, snapshot/restore natif (au lieu de Docker simple)
- ⬜ **gVisor** pour Aerolith et Cryolith (Docker renforcé)
- ⬜ **HITL 3 niveaux** : safe (auto), modéré (log+notif), dangereux (approbation humaine via interrupt())

---

## 9. FINE-TUNING & MODÈLES

- 💡 **QLoRA via Unsloth** : fine-tuner les modèles sur tes données spécifiques (2-5× plus rapide, 80% VRAM en moins)
- 💡 **Multi-LoRA** : un modèle de base Qwen3-8B + adaptateurs swappables par agent (coding, offensif, défensif), 10-100 Mo chacun, versionnables dans Git
- 💡 **Données d'entraînement** : writeups CTF (offensif), playbooks incident response (défensif), patterns de ta codebase (codeur)
- 💡 **RouteLLM** : classificateur léger pour router entre modèles faibles et forts

---

## 10. QUALITÉ & MAINTENANCE

- ✅ Cross-platform system_info (psutil)
- ✅ Chat persistence (JSON, ~/.0lith/chats/)
- ✅ **README.md complet** : installation, prérequis, architecture, screenshots
- ⬜ **Supprimer olith_memory_init.py racine** du tracking git
- ⬜ **HEARTBEAT.md** : pattern de monitoring proactif
- 💡 **Logging centralisé** : Prometheus + Grafana + Loki pour tokens/s, VRAM, erreurs par agent
- 💡 **Dashboard des sessions** : stats d'utilisation, agents les plus sollicités

---

## 11. VISION LONG TERME

- 💡 **BCI (Brain Computer Interface)** : architecture scalable pour intégration future. EEG non invasif (Neurable, Muse) → détection de fatigue mentale. Protocole Apple BCI HID → contrôle par intention. Horizon réaliste : détection binaire approuver/rejeter via focus attentionnel pour le HITL (2027-2030)
- 💡 **Anticipation profonde** : après des mois de données, 0Lith prédit tes décisions et prépare les réponses avant que tu les demandes
- 💡 **Écosystème de vie** : pas un chat, un cockpit personnel. 0Lith ≠ OpenClawd — la différence c'est la mémoire persistante + l'anticipation + la souveraineté totale

---

## PRIORITÉS SUGGÉRÉES (court terme)

| # | Tâche | Effort | Impact | Statut |
|---|-------|--------|--------|--------|
| 1 | Shadow Thinking (anticipation proactive) | 2-3 jours | Élevé | ⬜ |
| 2 | Suppression de conversations (+ multi-select) | 0.5 jour | Élevé | ⬜ |
| 3 | Onglets sidebar (Agents / Historique) | 1 jour | Moyen | ⬜ |
| 4 | OLithEye animé | 1-2 jours | Moyen (polish) | ⬜ |
| 5 | MCP Server Zed | 2-3 jours | Élevé (workflow) | ⬜ |
| 6 | Boucle d'apprentissage suggestions | 1-2 jours | Élevé | ⬜ |
| 7 | Agents enfichables YAML | 2-3 jours | Élevé (architecture) | ⬜ |
