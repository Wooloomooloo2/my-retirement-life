"""
Triple store interface — wraps Oxigraph for the application.
All data persistence goes through this module.

Named graphs:
  https://myretirementlife.app/ontology/graph  — ontology (loaded from TTL)
  https://myretirementlife.app/data/graph      — user instance data
"""
import pyoxigraph as og
from src.config import settings

MRL = "https://myretirementlife.app/ontology#"
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

    def query(self, sparql: str):
        """Execute a SPARQL SELECT query."""
        return self._store.query(sparql)

    def update(self, sparql: str) -> None:
        """Execute a SPARQL UPDATE query."""
        self._store.update(sparql)

    def add(self, subject: str, predicate: str, obj,
            graph: og.NamedNode = None) -> None:
        """
        Add a single triple to the store.
        Defaults to the user data graph.
        obj can be a pre-built Oxigraph term, or a string (auto-detected
        as NamedNode if starts with http/https, otherwise Literal).
        """
        s = og.NamedNode(subject)
        p = og.NamedNode(predicate)
        if isinstance(obj, (og.NamedNode, og.Literal, og.BlankNode)):
            o = obj
        elif isinstance(obj, str) and obj.startswith(("http://", "https://")):
            o = og.NamedNode(obj)
        else:
            o = og.Literal(str(obj))
        g = graph or DATA_GRAPH
        self._store.add(og.Quad(s, p, o, g))

    def next_iri(self, class_name: str) -> str:
        """
        Generate the next IRI for a given class following the
        mrl:ClassName_N pattern (ADR-006).

        Queries the data graph for the highest existing N for the class
        and returns N+1. Returns mrl:ClassName_1 if no instances exist.

        Args:
            class_name: The local class name, e.g. 'Person', 'CashAccount'

        Returns:
            Full IRI string, e.g. 'https://myretirementlife.app/ontology#Person_1'
        """
        sparql = f"""
            PREFIX mrl: <{MRL}>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            SELECT (MAX(?n) AS ?maxN)
            WHERE {{
                GRAPH <{DATA_GRAPH.value}> {{
                    ?s a mrl:{class_name} .
                    BIND(xsd:integer(STRAFTER(STR(?s), "{class_name}_")) AS ?n)
                }}
            }}
        """
        results = list(self._store.query(sparql))
        max_n = 0
        if results:
            val = results[0].get("maxN")
            if val is not None and str(val.value).isdigit():
                max_n = int(val.value)
        return f"{MRL}{class_name}_{max_n + 1}"

    def __len__(self) -> int:
        """Return the total number of triples across all graphs."""
        return len(self._store)


# Singleton instance — imported by the rest of the app
store = RetirementStore()
