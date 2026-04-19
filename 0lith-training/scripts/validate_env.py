"""
validate_env.py — Vérifie l'environnement avant de lancer l'entraînement.

Vérifications :
  1. CUDA disponible (torch)
  2. VRAM >= 14 GB (marge de sécurité pour bf16 LoRA Qwen3.5-4B)
  3. Version CUDA >= 12.8 (Blackwell RTX 5070 Ti)
  4. Unsloth importable
  5. Ollama accessible sur localhost:11434

Usage :
  python scripts/validate_env.py
  python scripts/validate_env.py --vram-min 12  # Baisser le seuil (non recommandé)

Exit 0 si tout OK, exit 1 avec message clair sinon.
"""

import sys
import argparse


VRAM_MIN_GB_DEFAULT = 14.0
CUDA_MIN_VERSION = (12, 8)
OLLAMA_URL = "http://localhost:11434/api/tags"


def check_torch_cuda() -> tuple[bool, str]:
    try:
        import torch
    except ImportError:
        return False, "torch non installé — pip install torch>=2.6.0"

    if not torch.cuda.is_available():
        return False, "CUDA non disponible — vérifier driver NVIDIA + installation torch CUDA"

    device = torch.cuda.get_device_name(0)
    return True, f"GPU détecté : {device}"


def check_vram(vram_min_gb: float) -> tuple[bool, str]:
    try:
        import torch
        props = torch.cuda.get_device_properties(0)
        total_gb = props.total_memory / (1024 ** 3)
        if total_gb < vram_min_gb:
            return False, (
                f"VRAM insuffisante : {total_gb:.1f} GB détectés, {vram_min_gb} GB requis.\n"
                f"  Fallback : réduire max_seq_length à 1024 dans les configs YAML."
            )
        return True, f"VRAM : {total_gb:.1f} GB (seuil : {vram_min_gb} GB)"
    except Exception as e:
        return False, f"Erreur lecture VRAM : {e}"


def check_cuda_version() -> tuple[bool, str]:
    try:
        import torch
        cuda_ver = torch.version.cuda
        if cuda_ver is None:
            return False, "Version CUDA non détectée dans torch"
        parts = cuda_ver.split(".")
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        if (major, minor) < CUDA_MIN_VERSION:
            return False, (
                f"CUDA {cuda_ver} détecté — version {CUDA_MIN_VERSION[0]}.{CUDA_MIN_VERSION[1]}+ requise "
                f"(Blackwell/RTX 5070 Ti nécessite CUDA 12.8+)"
            )
        return True, f"CUDA {cuda_ver}"
    except Exception as e:
        return False, f"Erreur lecture version CUDA : {e}"


def check_unsloth() -> tuple[bool, str]:
    try:
        import unsloth  # noqa: F401
        version = getattr(unsloth, "__version__", "inconnu")
        return True, f"Unsloth {version}"
    except ImportError:
        return False, (
            "Unsloth non installé.\n"
            "  Installation : pip install 'unsloth[cu128-torch260] @ git+https://github.com/unslothai/unsloth.git'"
        )
    except Exception as e:
        return False, f"Erreur import unsloth : {e}"


def check_ollama() -> tuple[bool, str]:
    try:
        import requests
        resp = requests.get(OLLAMA_URL, timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            return True, f"Ollama accessible — {len(models)} modèle(s) disponible(s)"
        return False, f"Ollama répond HTTP {resp.status_code} (attendu 200)"
    except ImportError:
        return False, "requests non installé — pip install requests"
    except Exception:
        return False, (
            f"Ollama inaccessible sur {OLLAMA_URL}\n"
            "  Vérifier qu'Ollama est démarré (service Windows ou `ollama serve`)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validation de l'environnement 0Lith Training")
    parser.add_argument(
        "--vram-min",
        type=float,
        default=VRAM_MIN_GB_DEFAULT,
        help=f"VRAM minimale en GB (défaut : {VRAM_MIN_GB_DEFAULT})",
    )
    args = parser.parse_args()

    import sys as _sys
    python_ver = f"Python {_sys.version.split()[0]}"

    checks = [
        ("CUDA disponible",        check_torch_cuda()),
        ("VRAM suffisante",        check_vram(args.vram_min)),
        ("Version CUDA",           check_cuda_version()),
        ("Unsloth",                check_unsloth()),
        ("Ollama",                 check_ollama()),
    ]

    print(f"\n{'=' * 55}")
    print("  0Lith Training — Validation environnement")
    print(f"  {python_ver}")
    print(f"{'=' * 55}")

    all_ok = True
    for label, (ok, msg) in checks:
        status = "OK" if ok else "FAIL"
        icon = "[OK]" if ok else "[!!]"
        print(f"\n  {icon} {label}")
        print(f"      {msg}")
        if not ok:
            all_ok = False

    print(f"\n{'=' * 55}")
    if all_ok:
        print("  Environnement valide — prêt pour l'entraînement.")
        print(f"{'=' * 55}\n")
        sys.exit(0)
    else:
        print("  ECHEC — corriger les erreurs ci-dessus avant de continuer.")
        print(f"{'=' * 55}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
