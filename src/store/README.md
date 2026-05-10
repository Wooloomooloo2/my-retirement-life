# My Retirement Life Ontology

**Namespace:** `https://myretirementlife.app/ontology#` (prefix: `mrl:`)  
**Version:** 0.1.0  
**File:** [mrl-ontology.ttl](mrl-ontology.ttl)

---

## Design principles

- **Simple class hierarchy** — classes are defined for human understanding and extensibility, not for OWL reasoning
- **Independent reference entities** — currencies, jurisdictions, and other shared concepts are named individuals, not string literals; this allows properties (exchange rates, symbols, rules) to be attached to them and shared across all references
- **Late binding** — the ontology is intentionally high-level; subclasses and properties can be added without breaking existing data
- **TTL as truth** — the `.ttl` file is the authoritative source; the Python store wrapper loads it on startup

---

## Class hierarchy

```
owl:Thing
├── mrl:Currency                   (independent reference entity)
├── mrl:Jurisdiction               (independent reference entity)
├── mrl:Person
├── mrl:Account
│   ├── mrl:CashAccount            ✅ MVP
│   ├── mrl:InvestmentAccount      🔮 post-MVP
│   ├── mrl:PensionAccount         🔮 post-MVP
│   ├── mrl:PropertyAsset          🔮 post-MVP
│   └── mrl:OtherAsset             🔮 post-MVP
├── mrl:BudgetLine
├── mrl:LifeEvent
└── mrl:ProjectionSettings
```

---

## Key design decisions

### Currency and Jurisdiction as named individuals

`mrl:Currency_GBP`, `mrl:Currency_USD`, `mrl:EUR` etc. are instances of `mrl:Currency`, not string literals. This means:

```turtle
# What we do
mrl:myAccount mrl:accountCurrency mrl:Currency_GBP .

# What we avoid
mrl:myAccount mrl:accountCurrency "GBP" .
```

The benefit: exchange rates, symbols, and locale rules can be attached to `mrl:Currency_GBP` once and queried across every account that references it. When we add exchange rate data in a later release, no existing triples need to change.

### Account as superclass

`mrl:CashAccount` is a subclass of `mrl:Account`. Properties common to all accounts (`accountName`, `accountBalance`, `accountCurrency`, `accountJurisdiction`, `ownedBy`) are defined on `mrl:Account`. Subclass-specific properties are defined on the subclass.

Post-MVP account types (`mrl:InvestmentAccount`, `mrl:PensionAccount` etc.) are declared in the ontology now so future data can reference them, even though the application does not yet populate them.

### Amounts as decimals in base currency

All monetary amounts on `mrl:Person`, `mrl:BudgetLine`, and `mrl:LifeEvent` are stored in the person's base currency. `mrl:Account` stores its balance in its own `mrl:accountCurrency`. The projection engine converts account balances to base currency at query time using exchange rates when available.

---

## Seed data

The ontology file includes seed data for common currencies and jurisdictions. These are loaded into the store at application startup alongside the class and property definitions.

**Currencies included:** GBP, USD, EUR, AUD, CAD, CHF, JPY, NZD  
**Jurisdictions included:** GB, US, EU, AU, CA

Additional currencies and jurisdictions can be added to the TTL file or inserted via SPARQL UPDATE.

---

## Extending the ontology

To add a new asset type (e.g. a cryptocurrency account):

```turtle
mrl:CryptoAccount a owl:Class ;
    rdfs:subClassOf mrl:Account ;
    rdfs:label "Crypto Account" ;
    rdfs:comment "Cryptocurrency holdings." .

mrl:walletAddress a owl:DatatypeProperty ;
    rdfs:domain mrl:CryptoAccount ;
    rdfs:range xsd:string ;
    rdfs:label "wallet address" .
```

No existing data is affected. The new subclass inherits all `mrl:Account` properties automatically.

---

## SPARQL examples

**Get all cash accounts for a person:**
```sparql
PREFIX mrl: <https://myretirementlife.app/ontology#>

SELECT ?account ?name ?balance ?currency
WHERE {
    ?account a mrl:CashAccount ;
             mrl:ownedBy mrl:Person_<uuid> ;
             mrl:accountName ?name ;
             mrl:accountBalance ?balance ;
             mrl:accountCurrency ?curr .
    ?curr mrl:currencyCode ?currency .
}
```

**Get all accounts with their currency symbols:**
```sparql
PREFIX mrl: <https://myretirementlife.app/ontology#>

SELECT ?name ?balance ?symbol
WHERE {
    ?account mrl:ownedBy mrl:Person_<uuid> ;
             mrl:accountName ?name ;
             mrl:accountBalance ?balance ;
             mrl:accountCurrency ?curr .
    ?curr mrl:currencySymbol ?symbol .
}
```
