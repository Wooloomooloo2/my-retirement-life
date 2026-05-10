"""
Triple store interface - wraps Oxigraph for the application.
All data persistence goes through this module.
"""
import pyoxigraph as og
from src.config import settings


class RetirementStore:
    """
    Wrapper around the Oxigraph persistent triple store.
    Provides a clean interface for the rest of the application.
    """

    def __init__(self):
        store_path = str(settings.store_path)
        self._store = og.Store(store_path)

    def query(self, sparql: str) -> og.QuerySolutions:
        """Execute a SPARQL SELECT query."""
        return self._store.query(sparql)

    def update(self, sparql: str) -> None:
        """Execute a SPARQL UPDATE query."""
        self._store.update(sparql)

    def add(self, subject: str, predicate: str, obj: str, graph: str = None) -> None:
        """Add a single triple to the store."""
        s = og.NamedNode(subject)
        p = og.NamedNode(predicate)
        # Determine if object is a URI or a literal
        if obj.startswith("http://") or obj.startswith("https://"):
            o = og.NamedNode(obj)
        else:
            o = og.Literal(obj)
        quad = og.Quad(s, p, o, og.DefaultGraph())
        self._store.add(quad)

    def __len__(self) -> int:
        """Return the number of triples in the store."""
        return len(self._store)


# Singleton instance - imported by the rest of the app
store = RetirementStore()
