"""
Ontology loader — reads mrl-ontology.ttl into the Oxigraph store on startup.

The ontology is loaded into a named graph so it is clearly separated from
user instance data and can be queried or reloaded independently.

The loader is idempotent: if the ontology graph already contains triples
it will not reload unless force=True is passed. This avoids redundant work
on every application restart.
"""
from pathlib import Path
import logging

import pyoxigraph as og

logger = logging.getLogger(__name__)

# Named graph that holds the ontology — separates it from user data
ONTOLOGY_GRAPH = og.NamedNode("https://myretirementlife.app/ontology/graph")

# Path to the TTL file relative to the project root
ONTOLOGY_TTL = Path(__file__).parent.parent.parent / "docs" / "ontology" / "mrl-ontology.ttl"


def load_ontology(store: og.Store, force: bool = False) -> int:
    """
    Load the MRL ontology TTL into the Oxigraph store.

    Args:
        store:  The Oxigraph Store instance.
        force:  If True, clear and reload even if already loaded.

    Returns:
        Number of triples in the ontology graph after loading.
    """
    if not ONTOLOGY_TTL.exists():
        logger.error(f"Ontology file not found: {ONTOLOGY_TTL}")
        raise FileNotFoundError(f"Ontology file not found: {ONTOLOGY_TTL}")

    # Check if already loaded
    existing = list(store.quads_for_pattern(None, None, None, ONTOLOGY_GRAPH))
    if existing and not force:
        logger.info(f"Ontology already loaded ({len(existing)} triples). Skipping.")
        return len(existing)

    if force and existing:
        logger.info("Force reload requested — clearing ontology graph.")
        store.remove_graph(ONTOLOGY_GRAPH)

    # Load TTL into the named ontology graph
    logger.info(f"Loading ontology from {ONTOLOGY_TTL}")
    store.load(
        path=str(ONTOLOGY_TTL),
        format=og.RdfFormat.TURTLE,
        to_graph=ONTOLOGY_GRAPH
)

    triple_count = len(list(store.quads_for_pattern(None, None, None, ONTOLOGY_GRAPH)))
    logger.info(f"Ontology loaded successfully — {triple_count} triples in ontology graph.")
    return triple_count


def ontology_triple_count(store: og.Store) -> int:
    """Return the number of triples currently in the ontology graph."""
    return len(list(store.quads_for_pattern(None, None, None, ONTOLOGY_GRAPH)))
