"""
0Lith Cyber Range — Noise Generator
=====================================
Génère du trafic HTTP légitime vers les services du Cyber Range pour
simuler l'activité d'utilisateurs normaux. Rend la détection d'attaques
plus réaliste pour Blue Team en ajoutant du bruit de fond.

Variables d'environnement :
    TARGETS   : IPs cibles séparées par virgule (ex: "10.42.1.10,10.42.1.11")
    INTENSITY : low / medium / high (défaut: medium)

Niveaux :
    low    → 1 requête toutes les 3-8 secondes
    medium → 1 requête toutes les 0.5-2 secondes
    high   → 1 requête toutes les 0.1-0.5 secondes
"""

from __future__ import annotations

import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Paramètres de bruit
# ---------------------------------------------------------------------------

# Intensity → (délai min, délai max) en secondes
INTENSITY_DELAYS: dict[str, tuple[float, float]] = {
    "low":    (3.0, 8.0),
    "medium": (0.5, 2.0),
    "high":   (0.1, 0.5),
}

# Requêtes de recherche simulant des utilisateurs normaux
SEARCH_QUERIES = [
    "laptop", "keyboard", "monitor", "mouse", "headset",
    "webcam", "usb hub", "cable", "charger", "laptop stand",
    "external drive", "tablet", "speaker", "printer", "router",
]

# Commentaires bénins simulant des avis utilisateurs
COMMENT_TEXTS = [
    "Great product, highly recommend!",
    "Good quality for the price.",
    "Arrived on time and works perfectly.",
    "Five stars, amazing value.",
    "Will definitely buy again.",
    "Solid build quality.",
    "Easy to set up, works out of the box.",
]

# User-Agents réalistes
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Android 13; Mobile; rv:109.0) Gecko/113.0 Firefox/113.0",
]

# Actions avec leur poids de probabilité (simulation de navigation réaliste)
ACTIONS = ["home", "products", "search", "search", "comment"]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _request(url: str, method: str = "GET", data: bytes | None = None) -> None:
    """Envoie une requête HTTP et ignore silencieusement toute erreur."""
    try:
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", random.choice(USER_AGENTS))
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        req.add_header("Accept-Language", "en-US,en;q=0.5")
        if data:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read(4096)  # consomme la réponse
    except Exception:
        pass  # Silencieux — c'est du bruit de fond


# ---------------------------------------------------------------------------
# Générateur de trafic
# ---------------------------------------------------------------------------


def _do_action(base_url: str) -> None:
    """Exécute une action de navigation aléatoire vers un service webapp."""
    action = random.choice(ACTIONS)

    if action == "home":
        _request(f"{base_url}/")

    elif action == "products":
        _request(f"{base_url}/products")

    elif action == "search":
        q = urllib.parse.quote_plus(random.choice(SEARCH_QUERIES))
        _request(f"{base_url}/search?q={q}")

    elif action == "comment":
        text = urllib.parse.quote_plus(random.choice(COMMENT_TEXTS))
        _request(f"{base_url}/comment", method="POST", data=f"text={text}".encode())


def main() -> None:
    targets_raw = os.environ.get("TARGETS", "")
    intensity   = os.environ.get("INTENSITY", "medium").lower()

    if intensity not in INTENSITY_DELAYS:
        intensity = "medium"

    min_delay, max_delay = INTENSITY_DELAYS[intensity]
    targets = [t.strip() for t in targets_raw.split(",") if t.strip()]

    # Écriture du marker de santé (HEALTHCHECK le vérifie)
    try:
        with open("/tmp/healthy", "w") as f:
            f.write("ok")
    except OSError:
        pass

    if not targets:
        # Pas de cibles — le conteneur reste actif sans rien faire
        while True:
            time.sleep(30)

    # Boucle principale
    while True:
        target = random.choice(targets)
        # Port webapp par défaut : 8080
        base_url = f"http://{target}:8080"
        _do_action(base_url)
        time.sleep(random.uniform(min_delay, max_delay))


if __name__ == "__main__":
    main()
