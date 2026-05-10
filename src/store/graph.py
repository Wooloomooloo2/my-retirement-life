"""
Triple store interface — wraps Oxigraph for the application.
All data persistence goes through this module.

Named graphs:
  https://myretirementlife.app/ontology/graph  — ontology (loaded from TTL)
  https://myretirementlife.app/data/graph      — user instance data
"""
import pyoxigraph as og
from src.config import settings

# Named graph for user data — kept separate from the ontology graph
DATA_GRAPH = og.NamedNode("https://myretirementlife.app/data/graph")


class RetirementStore:
    """
    Wrapper around the Oxigraph persistent store.
    Provides a clean interface for the rest of the application.
    """

    def __init__(self):
        store_path = str(settings.store_path)
        self._store = og.Store(store_path)

    @property
    def store(self) -> og.Store:
        """Direct access to the underlying Oxigraph store (for the loader)."""
        return self._store

    def query(self, sparql: str) -> og.QuerySolutions:
        """Execute a SPARQL SELECT query."""
        return self._store.query(sparql)

    def update(self, sparql: str) -> None:
        """Execute a SPARQL UPDATE query."""
        self._store.update(sparql)

    def add(self, subject: str, predicate: str, obj: str,
            graph: og.NamedNode = None) -> None:
        """
        Add a single triple to the store.
        Defaults to the user data graph.
        Object is treated as a NamedNode if it starts with http/https,
        otherwise as a plain literal.
        """
        s = og.NamedNode(subject)
        p = og.NamedNode(predicate)
        o = og.NamedNode(obj) if obj.startswith(("http://", "https://")) else og.Literal(obj)
        g = graph or DATA_GRAPH
        self._store.add(og.Quad(s, p, o, g))

    def __len__(self) -> int:
        """Return the total number of triples across all graphs."""
        return len(self._store)


# Singleton instance — imported by the rest of the app
store = RetirementStore()
