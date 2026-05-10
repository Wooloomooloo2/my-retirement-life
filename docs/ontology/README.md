# My Retirement Life Ontology

**Namespace:** `https://myretirementlife.app/ontology#` (prefix: `mrl:`)  
**Extended vocabulary namespace:** `https://myretirementlife.app/ontology/ext#` (prefix: `mrlx:`)  
**Version:** 0.3.0  
**File:** [mrl-ontology.ttl](mrl-ontology.ttl)  
**Python loader:** `src/store/ontology_loader.py`

---

## Design principles

- **Simple class hierarchy** — classes are defined for human understanding and extensibility, not for OWL reasoning
- **Independent reference entities** — currencies, jurisdictions, and other shared concepts are named individuals, not string literals; this allows properties (exchange rates, symbols, rules) to be attached to them once and shared across all references
- **Two namespaces** — `mrl:` for ontology terms and instance data; `mrlx:` for controlled vocabularies and enumeration values
- **Consistent IRI patterns** — see below
- **Language-tagged labels** — all labels carry `@en` tags so additional languages can be added as extra triples without restructuring
- **SKOS for controlled vocabularies** — `mrlx:` individuals use `skos:prefLabel` and `skos:definition`; everything else uses `rdfs:label` and `rdfs:comment`
- **Named graph separation** — the ontology is loaded into its own named graph, kept separate from user instance data
- **TTL as truth** — the `.ttl` file is the authoritative source; the Python store wrapper loads it on startup

---

## IRI patterns

| Pattern | Example | Used for |
|---------|---------|----------|
| `mrl:ClassName` | `mrl:CashAccount` | Classes |
| `mrl:propertyName` | `mrl:accountBalance` | Properties (camelCase) |
| `mrl:ClassName_Code` | `mrl:Currency_GBP` | Named individuals (reference data) |
| `mrlx:ClassName_Value` | `mrlx:BudgetLineType_Mandatory` | Controlled vocabulary individuals |
| `mrl:ClassName_<uuid>` | `mrl:Person_a3f9...` | User instance data (runtime) |

---

## Named graphs

The store uses two named graphs to keep ontology and user data cleanly separated:

| Named graph | IRI | Contents |
|-------------|-----|----------|
| Ontology graph | `https://myretirementlife.app/ontology/graph` | All triples from `mrl-ontology.ttl` |
| Data graph | `https://myretirementlife.app/data/graph` | User instance data created at runtime |

This separation means ontology triples can be reloaded (e.g. after editing the TTL) without touching user data, and SPARQL queries can target either graph independently.

---

## Class hierarchy

```
owl:Thing
├── mrl:Currency                   (reference individual — mrl:Currency_GBP etc.)
├── mrl:Jurisdiction               (reference individual — mrl:Jurisdiction_GB etc.)
├── mrl:Person                     ✅ MVP
├── mrl:Account
│   ├── mrl:CashAccount            ✅ MVP
│   ├── mrl:InvestmentAccount      🔮 post-MVP
│   ├── mrl:PensionAccount         🔮 post-MVP
│   ├── mrl:PropertyAsset          🔮 post-MVP
│   └── mrl:OtherAsset             🔮 post-MVP
├── mrl:BudgetLine                 ✅ MVP
├── mrl:LifeEvent                  ✅ MVP
└── mrl:ProjectionSettings         ✅ MVP

mrlx: (controlled vocabularies)
├── mrlx:EmploymentStatus
│   ├── mrlx:EmploymentStatus_Employed
│   ├── mrlx:EmploymentStatus_SelfEmployed
│   ├── mrlx:EmploymentStatus_NotWorking
│   └── mrlx:EmploymentStatus_Retired
├── mrlx:BudgetLineType
│   ├── mrlx:BudgetLineType_Mandatory
│   ├── mrlx:BudgetLineType_Discretionary
│   └── mrlx:BudgetLineType_Loan
└── mrlx:LifeEventType
    ├── mrlx:LifeEventType_LargeExpenditure
    ├── mrlx:LifeEventType_Windfall
    ├── mrlx:LifeEventType_PropertyTransaction
    ├── mrlx:LifeEventType_RelocationAbroad
    └── mrlx:LifeEventType_CaringResponsibility
```

---

## Key design decisions

### Currency and Jurisdiction as named individuals

`mrl:Currency_GBP`, `mrl:Currency_USD` etc. are instances of `mrl:Currency`, not string literals. This means:

```turtle
# What we do
mrl:Account_abc123 mrl:accountCurrency mrl:Currency_GBP .

# What we avoid
mrl:Account_abc123 mrl:accountCurrency "GBP" .
```

The benefit: exchange rates, symbols, and locale rules can be attached to `mrl:Currency_GBP` once and queried across every account that references it. When exchange rate data is added in a later release, no existing triples need to change.

### Two namespaces: mrl: and mrlx:

`mrl:` is for ontology terms (classes, properties) and named reference individuals.  
`mrlx:` is exclusively for controlled vocabulary / enumeration values — anything taxonomical.

This makes it immediately clear from an IRI alone whether something is a domain concept or a classification value.

### Label and annotation strategy

| Element type | Label predicate | Annotation predicate |
|---|---|---|
| Classes and properties | `rdfs:label` | `rdfs:comment` |
| `mrlx:` controlled vocabulary individuals | `skos:prefLabel` | `skos:definition` |
| `mrl:` reference individuals | `rdfs:label` | `rdfs:comment` |

All labels are language-tagged with `@en`. Adding a French translation requires only adding extra triples — no restructuring:

```turtle
mrl:CashAccount rdfs:label "Cash Account"@en ;
                rdfs:label "Compte de dépôt"@fr .
```

### Account as superclass

`mrl:CashAccount` is a subclass of `mrl:Account`. Properties common to all accounts are defined on `mrl:Account`. Post-MVP account types are declared in the ontology now so future data can reference them, even though the application does not yet populate them.

---

## Seed data

The ontology file includes seed data for common currencies and jurisdictions loaded into the store at startup.

**Currencies:** GBP, USD, EUR, AUD, CAD, CHF, JPY, NZD, SEK, NOK, DKK, SGD, HKD, ZAR  
**Jurisdictions:** GB, US, EU, AU, CA, NZ, CH, SG, ZA

---

## Loading and reloading

The ontology is loaded by `src/store/ontology_loader.py` on application startup. It is idempotent — if the ontology graph already contains triples, it skips loading unless forced.

To force a reload after editing the TTL (e.g. from the Python shell or a future admin endpoint):

```python
from src.store.graph import store
from src.store.ontology_loader import load_ontology
load_ontology(store.store, force=True)
```

You can verify the current state at runtime via the diagnostic endpoint:

```
http://127.0.0.1:8000/ontology/status
```

---

## Extending the ontology

To add a new asset type, add a new subclass and any specific properties to the TTL, then force-reload:

```turtle
mrl:CryptoAccount a owl:Class ;
    rdfs:subClassOf mrl:Account ;
    rdfs:label "Crypto Account"@en ;
    rdfs:comment "Cryptocurrency holdings. Post-MVP."@en .

mrl:walletAddress a owl:DatatypeProperty ;
    rdfs:label "wallet address"@en ;
    rdfs:domain mrl:CryptoAccount ;
    rdfs:range xsd:string .
```

No existing data is affected. The new subclass inherits all `mrl:Account` properties automatically.

---

## SPARQL examples

**Get all cash accounts for a person:**
```sparql
PREFIX mrl: <https://myretirementlife.app/ontology#>

SELECT ?account ?name ?balance ?currencyCode
WHERE {
    GRAPH <https://myretirementlife.app/data/graph> {
        ?account a mrl:CashAccount ;
                 mrl:ownedBy mrl:Person_<uuid> ;
                 mrl:accountName ?name ;
                 mrl:accountBalance ?balance ;
                 mrl:accountCurrency ?curr .
    }
    GRAPH <https://myretirementlife.app/ontology/graph> {
        ?curr mrl:currencyCode ?currencyCode .
    }
}
```

**Get all currency symbols:**
```sparql
PREFIX mrl: <https://myretirementlife.app/ontology#>

SELECT ?code ?symbol ?name
WHERE {
    GRAPH <https://myretirementlife.app/ontology/graph> {
        ?curr a mrl:Currency ;
              mrl:currencyCode ?code ;
              mrl:currencySymbol ?symbol ;
              mrl:currencyName ?name .
    }
}
ORDER BY ?code
```

**Get controlled vocabulary labels in English:**
```sparql
PREFIX mrlx: <https://myretirementlife.app/ontology/ext#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

SELECT ?individual ?label
WHERE {
    GRAPH <https://myretirementlife.app/ontology/graph> {
        ?individual a mrlx:BudgetLineType ;
                    skos:prefLabel ?label .
        FILTER(LANG(?label) = "en")
    }
}
```
