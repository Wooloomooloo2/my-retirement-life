"""
reload_ontology.py — force-reload the ontology named graph into the local store.

WHERE THIS GOES:  my-retirement-life/tools/reload_ontology.py
RUN (from the repo root, in your .venv, with the app CLOSED):

    python tools\\reload_ontology.py

WHY: the ontology loads only once into the persistent Oxigraph store and is
skipped on later startups while the ontology graph already has triples
(ADR-005). After editing docs/ontology/mrl-ontology.ttl — e.g. adding the new
INR/CNY/AED currencies — the already-populated graph is stale, so the edits
don't appear until the graph is force-reloaded.

This clears and reloads ONLY the ontology graph
(https://myretirementlife.app/ontology/graph). Your instance data in the data
graph is NOT touched.

NOTE: close the running app first. Oxigraph (RocksDB) is single-process, so the
store is locked while the app — or the packaged .exe — is open.
"""
import sys
from pathlib import Path

# This script lives in <repo>/tools/, so the repo root (which contains the
# `src` package) is one level up. Put it on the import path BEFORE importing
# src, otherwise Python only sees the tools/ folder and `import src` fails.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.store.graph import store
from src.store.ontology_loader import load_ontology, ontology_triple_count


def main() -> None:
    before = ontology_triple_count(store.store)
    after = load_ontology(store.store, force=True)
    print(f"Ontology graph reloaded: {before} -> {after} triples.")
    if after == before:
        print("(Triple count unchanged — that's expected if the only change "
              "was adding a few individuals; check the Profile/Accounts "
              "currency dropdowns for INR, CNY and AED.)")


if __name__ == "__main__":
    main()