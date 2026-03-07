#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
0Lith — Test Qdrant Embedded Mode
===================================
Vérifie l'insertion et la récupération de vecteurs dans le Qdrant embarqué.

Usage:
    python test_qdrant_embedded.py            # Test complet
    python test_qdrant_embedded.py --cleanup  # Supprime la collection de test après
"""

import sys
import uuid
import shutil
import argparse
from pathlib import Path

# Force UTF-8 output on Windows (box-drawing chars in banner)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

QDRANT_DATA_PATH = Path(__file__).parent / "qdrant_data"
TEST_COLLECTION  = "test_olith_embedded"
VECTOR_DIM       = 1024
NUM_TEST_VECTORS = 5

# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(msg):  print(f"  ✅ {msg}")
def fail(msg): print(f"  ❌ {msg}"); sys.exit(1)
def info(msg): print(f"  ℹ  {msg}")
def header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

# ── Tests ─────────────────────────────────────────────────────────────────────

def test_import():
    header("1. Import qdrant-client")
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance, PointStruct
        ok("qdrant-client importé")
        return QdrantClient, VectorParams, Distance, PointStruct
    except ImportError as e:
        fail(f"qdrant-client manquant : {e}\n     pip install qdrant-client")


def _open_client(QdrantClient):
    """Ouvre un QdrantClient embarqué (helper interne)."""
    QDRANT_DATA_PATH.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(QDRANT_DATA_PATH))
    client.get_collections()  # vérifie que ça répond
    return client


def test_connect(QdrantClient):
    header("2. Connexion Qdrant embarqué")
    info(f"Path : {QDRANT_DATA_PATH}")
    try:
        # Embedded mode bug: delete_collection leaves storage.sqlite on disk.
        # Wipe the test collection folder BEFORE opening the client so we
        # always start from a clean slate (no stale SQLite from previous runs).
        col_dir = QDRANT_DATA_PATH / "collection" / TEST_COLLECTION
        if col_dir.exists():
            shutil.rmtree(col_dir)
            info(f"Dossier résiduel '{col_dir.name}' nettoyé")
        client = _open_client(QdrantClient)
        ok(f"Connexion OK — dossier : {QDRANT_DATA_PATH}")
        return client
    except Exception as e:
        fail(f"Connexion échouée : {e}")


def test_create_collection(client, VectorParams, Distance):
    header("3. Création de la collection de test")
    existing = [c.name for c in client.get_collections().collections]
    if TEST_COLLECTION in existing:
        client.delete_collection(TEST_COLLECTION)
        info(f"Collection '{TEST_COLLECTION}' existante supprimée")
    client.create_collection(
        TEST_COLLECTION,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )
    ok(f"Collection '{TEST_COLLECTION}' créée (dim={VECTOR_DIM}, distance=COSINE)")


def test_insert(client, PointStruct):
    header("4. Insertion de vecteurs de test")
    import random
    random.seed(42)

    points = []
    for i in range(NUM_TEST_VECTORS):
        vec = [random.random() for _ in range(VECTOR_DIM)]
        point_id = str(uuid.uuid4())
        points.append(PointStruct(
            id=point_id,
            vector=vec,
            payload={
                "agent":   ["hodolith", "monolith", "aerolith", "cryolith", "pyrolith"][i],
                "content": f"Mémoire de test #{i+1}",
                "index":   i,
            },
        ))

    client.upsert(TEST_COLLECTION, points=points)
    ok(f"{NUM_TEST_VECTORS} vecteurs insérés")
    return points


def test_count(client, expected: int):
    header("5. Vérification du nombre de points")
    count = client.count(TEST_COLLECTION, exact=True).count
    if count == expected:
        ok(f"Nombre de points correct : {count}")
    else:
        fail(f"Attendu {expected} points, trouvé {count}")


def test_search(client, inserted_points):
    header("6. Recherche par similarité (nearest neighbour)")
    from qdrant_client.models import Query
    # Recherche du vecteur le plus proche du premier point inséré
    query_vec = inserted_points[0].vector
    response = client.query_points(
        collection_name=TEST_COLLECTION,
        query=query_vec,
        limit=3,
        with_payload=True,
    )
    results = response.points
    if not results:
        fail("Aucun résultat retourné par la recherche")

    top = results[0]
    if top.id == inserted_points[0].id:
        ok(f"Top-1 correct : id={str(top.id)[:8]}…  score={top.score:.4f}")
    else:
        fail(f"Top-1 inattendu : {top.id} (attendu {inserted_points[0].id})")

    for r in results:
        agent = r.payload.get("agent", "?")
        info(f"  [{agent:10s}] score={r.score:.4f}  id={str(r.id)[:8]}…")


def test_filter(client):
    header("7. Recherche filtrée par payload")
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    import random
    random.seed(99)

    query_vec = [random.random() for _ in range(VECTOR_DIM)]
    response = client.query_points(
        collection_name=TEST_COLLECTION,
        query=query_vec,
        query_filter=Filter(
            must=[FieldCondition(key="agent", match=MatchValue(value="monolith"))]
        ),
        limit=5,
        with_payload=True,
    )
    results = response.points
    if results:
        ok(f"Filtre payload OK : {len(results)} résultat(s) pour agent=monolith")
    else:
        fail("Filtre payload : aucun résultat pour agent=monolith")


def test_persistence(client, QdrantClient):
    header("8. Persistance (reconnexion + lecture)")
    # Embedded mode allows only one instance at a time.
    # Close → reopen to simulate a fresh process reading from disk.
    client.close()
    client2 = _open_client(QdrantClient)
    count = client2.count(TEST_COLLECTION, exact=True).count
    if count == NUM_TEST_VECTORS:
        ok(f"Données persistantes après reconnexion ({count} points)")
    else:
        # Don't call fail() yet — close client2 cleanly first
        client2.close()
        fail(f"Persistance échouée : {count} points au lieu de {NUM_TEST_VECTORS}")
    return client2  # caller must use this client going forward


def test_production_collection(client, QdrantClient):
    header("9. Collection de production olith_memories")
    collections = [c.name for c in client.get_collections().collections]
    if "olith_memories" in collections:
        count = client.count("olith_memories", exact=True).count
        ok(f"Collection 'olith_memories' trouvée — {count} points")
    else:
        info("Collection 'olith_memories' absente (normale avant le premier memory_init)")


def cleanup(client):
    header("Nettoyage")
    client.delete_collection(TEST_COLLECTION)
    ok(f"Collection '{TEST_COLLECTION}' supprimée")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test Qdrant embedded pour 0Lith")
    parser.add_argument("--cleanup", action="store_true",
                        help="Supprime la collection de test après les tests")
    args = parser.parse_args()

    print("""
  ┌─────────────────────────────────────────┐
  │  0Lith — Test Qdrant Embedded Mode      │
  │  dim=1024 · COSINE · py-backend/        │
  └─────────────────────────────────────────┘""")

    QdrantClient, VectorParams, Distance, PointStruct = test_import()
    client = test_connect(QdrantClient)
    test_create_collection(client, VectorParams, Distance)
    inserted = test_insert(client, PointStruct)
    test_count(client, NUM_TEST_VECTORS)
    test_search(client, inserted)
    test_filter(client)
    client = test_persistence(client, QdrantClient)
    test_production_collection(client, QdrantClient)

    if args.cleanup:
        cleanup(client)
    else:
        info(f"Collection '{TEST_COLLECTION}' conservée. Lance avec --cleanup pour la supprimer.")

    client.close()

    print(f"""
{'='*60}
  TOUS LES TESTS PASSENT — Qdrant embarqué opérationnel
  Data : {QDRANT_DATA_PATH}
{'='*60}
""")


if __name__ == "__main__":
    main()
