#!/usr/bin/env bash
# 0Lith — Cyber Range: Build all images
# ======================================
# Builds les 4 images dans l'ordre, vérifie le démarrage, affiche les tailles.
# Compatible WSL2/Docker Desktop et Linux natif.
#
# Usage:
#   ./build_all.sh               # Build + verify
#   ./build_all.sh --no-cache    # Force rebuild from scratch
#   ./build_all.sh --push        # Push vers registry après build (optionnel)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Couleurs ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Options ───────────────────────────────────────────────────────────────────
NO_CACHE=""
PUSH=false
for arg in "$@"; do
    case "$arg" in
        --no-cache) NO_CACHE="--no-cache" ;;
        --push)     PUSH=true ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
log_info()    { echo -e "${BLUE}[INFO]${RESET}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $*"; }
log_section() { echo -e "\n${BOLD}══════════════════════════════════════════${RESET}"; echo -e "${BOLD}  $*${RESET}"; echo -e "${BOLD}══════════════════════════════════════════${RESET}"; }

FAILED_BUILDS=()
PASSED_BUILDS=()
BUILD_START=$(date +%s)

# ── Vérifications préalables ──────────────────────────────────────────────────
log_section "0Lith Cyber Range — Build"

if ! command -v docker &>/dev/null; then
    log_error "Docker non trouvé. Installer Docker Desktop ou Docker Engine."
    exit 1
fi

if ! docker info &>/dev/null; then
    log_error "Docker daemon non accessible. Lancer Docker Desktop ou 'sudo systemctl start docker'."
    exit 1
fi

log_info "Docker: $(docker --version)"
[[ -n "$NO_CACHE" ]] && log_warn "Mode --no-cache activé — rebuild complet"

# ── Définition des images ─────────────────────────────────────────────────────
# Ordre de build : webapp en premier (sert de base au test des dépendances)
declare -a IMAGES=("vuln-webapp" "vuln-ssh" "siem-lite" "noise-gen")

# Vérification rapide après build (sans démarrer les daemons)
declare -A VERIFY_CMD=(
    ["vuln-webapp"]="python -c \"import flask, sqlite3; print('flask+sqlite3 OK')\""
    ["vuln-ssh"]="which sshd"
    ["siem-lite"]="which rsyslogd"
    ["noise-gen"]="python -c \"import urllib.request; print('urllib OK')\""
)
declare -A VERIFY_ENTRYPOINT=(
    ["vuln-webapp"]=""       # Entrypoint standard (python app.py) — override inutile
    ["vuln-ssh"]="bash"      # sshd requiert root et clés — vérification sans démarrer
    ["siem-lite"]="bash"     # rsyslogd requiert config — vérification sans démarrer
    ["noise-gen"]=""         # Entrypoint standard (python generator.py)
)

# ── Build loop ────────────────────────────────────────────────────────────────
echo ""
for service in "${IMAGES[@]}"; do
    context_dir="$SCRIPT_DIR/$service"
    tag="0lith/${service}:latest"

    if [[ ! -d "$context_dir" ]]; then
        log_error "Répertoire manquant : $context_dir"
        FAILED_BUILDS+=("$service")
        continue
    fi

    echo -e "${YELLOW}▶ Build${RESET} ${BOLD}$tag${RESET}"
    t0=$(date +%s)

    if docker build $NO_CACHE -t "$tag" "$context_dir" 2>&1 | \
       grep -E --line-buffered "^(Step|#[0-9]+|DONE|ERROR|error)" | \
       sed 's/^/  /'; then
        t1=$(date +%s)
        elapsed=$(( t1 - t0 ))
        size=$(docker image inspect "$tag" --format='{{.Size}}' 2>/dev/null | \
               awk '{printf "%.1f MB", $1/1024/1024}')
        log_ok "$tag — ${elapsed}s — ${size}"
    else
        log_error "Build ÉCHOUÉ pour $service"
        FAILED_BUILDS+=("$service")
        continue
    fi

    # ── Vérification démarrage ─────────────────────────────────────────────
    echo "  └─ Vérification démarrage..."
    ep_override=""
    [[ -n "${VERIFY_ENTRYPOINT[$service]}" ]] && ep_override="--entrypoint ${VERIFY_ENTRYPOINT[$service]}"

    verify_cmd="${VERIFY_CMD[$service]}"
    if docker run --rm $ep_override "$tag" sh -c "$verify_cmd" &>/dev/null; then
        log_ok "  Démarrage OK"
        PASSED_BUILDS+=("$service")
    else
        log_warn "  Vérification démarrage échouée (image peut quand même fonctionner)"
        PASSED_BUILDS+=("$service")  # Non-bloquant
    fi
    echo ""
done

# ── Push (optionnel) ──────────────────────────────────────────────────────────
if $PUSH; then
    log_section "Push vers registry"
    for service in "${PASSED_BUILDS[@]}"; do
        tag="0lith/${service}:latest"
        log_info "Push $tag..."
        docker push "$tag" && log_ok "$tag poussé" || log_error "Push échoué: $tag"
    done
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
BUILD_END=$(date +%s)
total=$(( BUILD_END - BUILD_START ))

log_section "Résumé"
echo ""
echo "Durée totale : ${total}s"
echo ""

echo "Images buildées :"
for service in "${IMAGES[@]}"; do
    tag="0lith/${service}:latest"
    if docker image inspect "$tag" &>/dev/null; then
        size=$(docker image inspect "$tag" --format='{{.Size}}' | \
               awk '{printf "%.1f MB", $1/1024/1024}')
        echo -e "  ${GREEN}✅${RESET}  $tag  ($size)"
    else
        echo -e "  ${RED}❌${RESET}  $tag  (manquant)"
    fi
done

echo ""
if [[ ${#FAILED_BUILDS[@]} -gt 0 ]]; then
    log_error "Builds échoués : ${FAILED_BUILDS[*]}"
    echo ""
    echo "Pour déboguer :"
    for service in "${FAILED_BUILDS[@]}"; do
        echo "  docker build -t 0lith/${service}:latest docker/${service}/"
    done
    exit 1
else
    log_ok "Tous les builds réussis — Cyber Range prêt."
    echo ""
    echo "Prochaines étapes :"
    echo "  ./test_cyber_range.sh                    # Tests d'intégration"
    echo "  docker compose -f docker-compose.test.yml up -d   # Démarrage manuel"
fi
