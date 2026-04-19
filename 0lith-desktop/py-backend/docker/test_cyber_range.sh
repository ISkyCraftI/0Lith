#!/usr/bin/env bash
# 0Lith — Cyber Range: Tests d'intégration
# ==========================================
# Lance les 4 services, attend 10s, exécute 5 tests, nettoie tout.
# Compatible WSL2/Docker Desktop et Linux natif.
#
# Note WSL2/Windows : les IPs conteneurs (10.42.1.x) ne sont PAS routables
# depuis l'hôte Windows. Les tests utilisent `docker exec` (intra-réseau) ou
# les ports exposés (localhost:PORT) pour contourner cette limitation.
#
# Usage:
#   ./test_cyber_range.sh
#   ./test_cyber_range.sh --keep   # Ne pas nettoyer après (debug)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.test.yml"

# ── Options ───────────────────────────────────────────────────────────────────
KEEP=false
for arg in "$@"; do
    [[ "$arg" == "--keep" ]] && KEEP=true
done

# ── Couleurs ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${RESET}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $*"; }
log_section() { echo -e "\n${BOLD}══════════════════════════════════════════${RESET}"; echo -e "${BOLD}  $*${RESET}"; echo -e "${BOLD}══════════════════════════════════════════${RESET}"; }

PASS=0
FAIL=0
declare -a RESULTS=()

record_pass() {
    local name="$1"
    PASS=$(( PASS + 1 ))
    RESULTS+=("${GREEN}✅${RESET}  $name")
    echo -e "    ${GREEN}✅ PASS${RESET}  $name"
}

record_fail() {
    local name="$1"
    local reason="${2:-}"
    FAIL=$(( FAIL + 1 ))
    RESULTS+=("${RED}❌${RESET}  $name${reason:+ — $reason}")
    echo -e "    ${RED}❌ FAIL${RESET}  $name${reason:+ — $reason}"
}

# ── Cleanup (trap) ────────────────────────────────────────────────────────────
cleanup() {
    if $KEEP; then
        log_warn "Mode --keep : conteneurs laissés actifs."
        echo "  Pour nettoyer : docker compose -f $COMPOSE_FILE down --volumes --remove-orphans"
    else
        echo ""
        log_info "Nettoyage..."
        docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans --timeout 10 2>/dev/null || true
        log_ok "Conteneurs supprimés."
    fi
}
trap cleanup EXIT

# ── Vérifications préalables ──────────────────────────────────────────────────
log_section "0Lith Cyber Range — Tests d'intégration"

if ! command -v docker &>/dev/null; then
    log_error "Docker non trouvé."
    exit 1
fi
if ! docker info &>/dev/null; then
    log_error "Docker daemon non accessible."
    exit 1
fi
if [[ ! -f "$COMPOSE_FILE" ]]; then
    log_error "Fichier introuvable : $COMPOSE_FILE"
    exit 1
fi

# Vérifier que les images existent
MISSING_IMAGES=()
for img in vuln-webapp vuln-ssh siem-lite noise-gen; do
    docker image inspect "0lith/${img}:latest" &>/dev/null || MISSING_IMAGES+=("0lith/${img}:latest")
done
if [[ ${#MISSING_IMAGES[@]} -gt 0 ]]; then
    log_error "Images manquantes : ${MISSING_IMAGES[*]}"
    log_error "Lancer './build_all.sh' d'abord."
    exit 1
fi

# ── Démarrage du réseau de test ───────────────────────────────────────────────
log_section "Démarrage des services"

# Nettoyer une éventuelle exécution précédente
docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans --timeout 5 2>/dev/null || true

log_info "Lancement des 4 conteneurs..."
docker compose -f "$COMPOSE_FILE" up -d 2>&1 | grep -E "(Container|Network|Volume|Starting|Started|Created)" | sed 's/^/  /' || true

log_info "Attente 10s (démarrage services)..."
sleep 10

# Attente supplémentaire si les health checks ne sont pas encore verts
log_info "Vérification health checks..."
WAIT_MAX=30
WAITED=0
while [[ $WAITED -lt $WAIT_MAX ]]; do
    webapp_health=$(docker inspect range-webapp-test --format='{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
    siem_health=$(docker inspect range-siem-test   --format='{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
    if [[ "$webapp_health" == "healthy" && "$siem_health" == "healthy" ]]; then
        break
    fi
    log_info "  webapp=$webapp_health siem=$siem_health — attente 5s..."
    sleep 5
    WAITED=$(( WAITED + 5 ))
done

echo ""
log_info "État des conteneurs :"
docker compose -f "$COMPOSE_FILE" ps 2>/dev/null | sed 's/^/  /'

# ── Tests ─────────────────────────────────────────────────────────────────────
log_section "Tests"
echo ""

# ─────────────────────────────────────────────────────────────
# TEST 1 : Webapp répond HTTP 200 sur /health
# ─────────────────────────────────────────────────────────────
echo -e "  ${BOLD}[1/5] Webapp — HTTP 200 sur /health${RESET}"
if docker exec range-webapp-test curl -sf -o /dev/null -w "%{http_code}" http://localhost:8080/health 2>/dev/null | grep -q "200"; then
    record_pass "Webapp HTTP 200 /health"
else
    # Fallback : port exposé (WSL2 sans exec curl dans l'image)
    if command -v curl &>/dev/null && curl -sf -o /dev/null http://localhost:18080/health 2>/dev/null; then
        record_pass "Webapp HTTP 200 /health (via port exposé 18080)"
    else
        record_fail "Webapp HTTP 200 /health" "endpoint inaccessible"
    fi
fi

# ─────────────────────────────────────────────────────────────
# TEST 2 : Webapp SQLi — extraction de FLAG{
# ─────────────────────────────────────────────────────────────
echo -e "  ${BOLD}[2/5] Webapp SQLi — extraction FLAG{${RESET}"
SQLI_PAYLOAD="' UNION SELECT 1,flag_value,1,1 FROM flags --"
SQLI_ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$SQLI_PAYLOAD'))" 2>/dev/null \
               || python -c "import urllib.parse; print(urllib.parse.quote('$SQLI_PAYLOAD'))" 2>/dev/null \
               || echo "%27%20UNION%20SELECT%201%2Cflag_value%2C1%2C1%20FROM%20flags%20--")

sqli_output=$(docker exec range-webapp-test \
    curl -sf "http://localhost:8080/search?q=${SQLI_ENCODED}" 2>/dev/null || echo "")

if echo "$sqli_output" | grep -q "FLAG{"; then
    flag_found=$(echo "$sqli_output" | grep -o 'FLAG{[^}]*}' | head -1)
    record_pass "Webapp SQLi FLAG{ extrait : $flag_found"
else
    # Fallback : port exposé
    sqli_output2=$(curl -sf "http://localhost:18080/search?q=${SQLI_ENCODED}" 2>/dev/null || echo "")
    if echo "$sqli_output2" | grep -q "FLAG{"; then
        flag_found=$(echo "$sqli_output2" | grep -o 'FLAG{[^}]*}' | head -1)
        record_pass "Webapp SQLi FLAG{ extrait (port 18080) : $flag_found"
    else
        record_fail "Webapp SQLi FLAG{ non trouvé" "réponse: $(echo "$sqli_output" | head -c 120)"
    fi
fi

# ─────────────────────────────────────────────────────────────
# TEST 3 : SSH port ouvert (22 en écoute)
# ─────────────────────────────────────────────────────────────
echo -e "  ${BOLD}[3/5] SSH — port 22 en écoute${RESET}"
if docker exec range-ssh-test bash -c "echo > /dev/tcp/localhost/22" 2>/dev/null; then
    record_pass "SSH port 22 ouvert"
else
    # Fallback : ss/netstat dans le conteneur
    if docker exec range-ssh-test sh -c "ss -tlnp 2>/dev/null | grep ':22' || netstat -tlnp 2>/dev/null | grep ':22'" &>/dev/null; then
        record_pass "SSH port 22 ouvert (via ss)"
    else
        # Fallback : nc depuis l'hôte via port exposé
        if command -v nc &>/dev/null && nc -z -w2 localhost 12222 2>/dev/null; then
            record_pass "SSH port 22 ouvert (via port exposé 12222)"
        else
            record_fail "SSH port 22" "port non accessible"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────
# TEST 4 : SIEM — logs existent dans /var/log/siem/consolidated.log
# ─────────────────────────────────────────────────────────────
echo -e "  ${BOLD}[4/5] SIEM — logs consolidated.log existent${RESET}"
if docker exec range-siem-test test -s /var/log/siem/consolidated.log 2>/dev/null; then
    line_count=$(docker exec range-siem-test wc -l < /var/log/siem/consolidated.log 2>/dev/null || echo "?")
    record_pass "SIEM logs OK ($line_count ligne(s))"
elif docker exec range-siem-test test -f /var/log/siem/consolidated.log 2>/dev/null; then
    # Fichier existe mais vide — acceptable au démarrage
    record_pass "SIEM consolidated.log existe (vide — normal au démarrage)"
else
    record_fail "SIEM consolidated.log" "fichier absent dans /var/log/siem/"
fi

# ─────────────────────────────────────────────────────────────
# TEST 5 : Noise-gen — trafic généré (/tmp/healthy marker)
# ─────────────────────────────────────────────────────────────
echo -e "  ${BOLD}[5/5] Noise-gen — marqueur /tmp/healthy présent${RESET}"
if docker exec range-noise-test test -f /tmp/healthy 2>/dev/null; then
    record_pass "Noise-gen /tmp/healthy présent"
else
    # Noise-gen dépend de vuln-webapp — attendre un peu plus si webapp était lent
    log_info "  /tmp/healthy absent, attente 5s supplémentaires..."
    sleep 5
    if docker exec range-noise-test test -f /tmp/healthy 2>/dev/null; then
        record_pass "Noise-gen /tmp/healthy présent (après attente)"
    else
        container_status=$(docker inspect range-noise-test --format='{{.State.Status}}' 2>/dev/null || echo "unknown")
        record_fail "Noise-gen /tmp/healthy" "conteneur status=$container_status"
    fi
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
log_section "Résultats"
echo ""
for r in "${RESULTS[@]}"; do
    echo -e "  $r"
done
echo ""
echo -e "  Total : ${GREEN}$PASS PASS${RESET} / ${RED}$FAIL FAIL${RESET} / 5 tests"
echo ""

if [[ $FAIL -eq 0 ]]; then
    log_ok "Cyber Range opérationnel — tous les tests passent."
    exit 0
else
    log_error "$FAIL test(s) échoué(s). Vérifier les logs :"
    echo "  docker compose -f $COMPOSE_FILE logs"
    exit 1
fi
