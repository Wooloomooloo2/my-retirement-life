"""Read-only reader for a My Financial Life (MFL) ``.mfl`` file (ADR-020, Phase 1).

MFL is a transaction-ledger app backed by SQLite; its ``.mfl`` backup/snapshot
files are plain SQLite 3 databases (MFL has no JSON export). This module opens
a user-selected ``.mfl`` **read-only** and returns an in-memory
:class:`MflSnapshot` — accounts with their *current* balances, investment
holdings, loans, and a top-level-rolled-up budget — for the import wizard to map
onto MRL entities. It never writes to the MFL file and adds no dependency
(``sqlite3`` is stdlib).

Balance maths mirror MFL's own desktop logic so imported figures match what the
user sees in MFL:

* **Recorded balance** (cash / credit / property / vehicle / loan accounts) =
  ``opening_balance + Σ txn.amount`` over every transaction — MFL
  ``account_summary._status_breakdown`` / ``_period_summary``. Transfers net out
  naturally because each account carries its own leg. All money is stored as
  integer **pence**.
* **Investment account value** = cash leg (same recorded-balance formula) +
  market value of open positions, where a position's value is
  ``net_qty × latest_price × price_multiplier`` — MFL ``holdings.compute_holdings_view``
  (``account_value = cash + holdings_market_value``). The ``lot`` table is not
  read; positions are derived by replaying the share legs of the ledger, which
  is how MFL itself computes them.
* **Property / vehicle worth** prefers the latest ``valuation`` row when present,
  else falls back to the recorded balance.

Share-action vocabulary is vendored from MFL ``import_engine/qif_actions.py``.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# --- Share-action vocabulary (vendored from MFL qif_actions.py) -------------
SHARE_IN_ACTIONS = {"buy", "buyx", "shrsin", "reinvdiv", "reinvlg", "reinvsh",
                    "reinvint", "reinvmd", "cvrshrt"}
SHARE_OUT_ACTIONS = {"sell", "sellx", "shrsout", "shtsell"}
SPLIT_ACTIONS = {"stksplit", "stocksplit"}

# Highest MFL schema_version this reader has been written/verified against.
# A newer file is read best-effort but surfaces a warning on the snapshot.
# v32 (0032_category_import_map) is additive to MFL's own category-import
# internals (category_import_map table + a "Needs Review" holding category) and
# touches none of the tables this reader consumes, so it needs no reader change.
KNOWN_SCHEMA_VERSION = 32

_PENCE = Decimal(100)
_CENT = Decimal("0.01")
_EPS = 1e-9


def _money(d: Decimal) -> Decimal:
    """Quantise to 2dp (pence). Cash/loan figures come from integer pence and are
    already exact; investment market values (qty × price × multiplier) carry float
    noise that must be rounded to a real money amount."""
    return d.quantize(_CENT, rounding=ROUND_HALF_UP)


class MflReadError(Exception):
    """The selected file is not a readable MFL database."""


def _norm(action: Optional[str]) -> str:
    return (action or "").strip().lower()


def _pence_to_decimal(pence: Optional[int]) -> Decimal:
    return (Decimal(int(pence or 0)) / _PENCE)


# --- Snapshot dataclasses ---------------------------------------------------
@dataclass
class MflHolding:
    security_id: int
    name: str
    symbol: str
    instrument_type: str
    quantity: float
    price: Optional[float]            # latest unit price, None if unpriced
    price_multiplier: float
    market_value: Optional[Decimal]   # qty × price × multiplier, None if unpriced


@dataclass
class MflLoan:
    original_amount: Decimal
    principal_paid: Decimal
    outstanding: Decimal              # original − principal_paid
    interest_rate: Optional[float]    # annual %, as stored
    term_months: Optional[int]
    monthly_payment: Decimal
    start_date: Optional[str]


@dataclass
class MflAccount:
    source_id: int
    source_ref: str                   # account.iri (stable) or str(id) — provenance key
    name: str
    family: str                       # cash / credit / investment / property / vehicle / loan
    type: str
    currency: str
    is_liability: bool
    balance: Decimal                  # CURRENT value, in the account's own currency
    opening_balance: Decimal
    holdings: list[MflHolding] = field(default_factory=list)   # investment only
    loan: Optional[MflLoan] = None                             # loan only


@dataclass
class MflBudgetCategory:
    name: str                         # top-level category name
    kind: str                         # 'expense' / 'income' / ...
    monthly: Decimal
    annual: Decimal


@dataclass
class MflBudget:
    name: str
    start_month: Optional[str]        # 'YYYY-MM'
    length_months: Optional[int]
    currency: Optional[str]
    categories: list[MflBudgetCategory] = field(default_factory=list)


@dataclass
class MflSnapshot:
    source_path: str
    schema_version: int
    person_name: str
    base_currency: str
    accounts: list[MflAccount] = field(default_factory=list)
    budget: Optional[MflBudget] = None
    fx_rates: dict = field(default_factory=dict)   # (base, quote) -> rate (latest)
    warnings: list[str] = field(default_factory=list)


# --- Reader -----------------------------------------------------------------
def read_snapshot(path: str) -> MflSnapshot:
    """Open an MFL ``.mfl`` SQLite file read-only and return an MflSnapshot.

    Raises :class:`MflReadError` if the file can't be opened as an MFL database
    or is missing tables this reader needs.
    """
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:                       # pragma: no cover - defensive
        raise MflReadError(f"Could not open '{path}' read-only: {exc}") from exc
    con.row_factory = sqlite3.Row
    try:
        return _read(con, path)
    except sqlite3.Error as exc:
        raise MflReadError(f"'{path}' is not a readable MFL database: {exc}") from exc
    finally:
        con.close()


def _read(con: sqlite3.Connection, path: str) -> MflSnapshot:
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"account", "txn", "person", "setting"}
    missing = required - tables
    if missing:
        raise MflReadError(
            f"Missing expected MFL tables: {', '.join(sorted(missing))}")

    warnings: list[str] = []

    schema_version = 0
    if "schema_version" in tables:
        row = con.execute("SELECT MAX(version) v FROM schema_version").fetchone()
        schema_version = int(row["v"] or 0)
        if schema_version > KNOWN_SCHEMA_VERSION:
            warnings.append(
                f"MFL file schema v{schema_version} is newer than this importer "
                f"was built for (v{KNOWN_SCHEMA_VERSION}); imported figures should "
                f"be reviewed carefully.")

    settings = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM setting")}
    base_currency = settings.get("base_currency") or "GBP"

    person = con.execute("SELECT name, base_currency FROM person ORDER BY id LIMIT 1").fetchone()
    person_name = (person["name"] if person else "") or ""
    if person and person["base_currency"]:
        base_currency = person["base_currency"]

    # Per-account transaction aggregates (cash leg) in one pass.
    txn_sum = {r["account_id"]: int(r["s"] or 0) for r in con.execute(
        "SELECT account_id, SUM(amount) s FROM txn GROUP BY account_id")}

    sec_meta, latest_price = _securities(con, tables)
    valuations = _latest_valuations(con, tables)
    loans = _loans(con, tables)

    accounts: list[MflAccount] = []
    for a in con.execute(
        "SELECT id, iri, name, type, family, currency, is_liability, "
        "opening_balance FROM account WHERE archived_at IS NULL"
    ):
        family = a["family"] or ""
        currency = a["currency"] or base_currency
        opening = _pence_to_decimal(a["opening_balance"])
        recorded = opening + _pence_to_decimal(txn_sum.get(a["id"], 0))

        holdings: list[MflHolding] = []
        loan: Optional[MflLoan] = None

        if family == "investment":
            holdings, market_value = _holdings_for_account(
                con, a["id"], sec_meta, latest_price)
            balance = recorded + market_value      # cash leg + priced market value
            if any(h.price is None for h in holdings):
                warnings.append(
                    f"Investment account '{a['name']}' has unpriced holdings; "
                    f"its value excludes them.")
        elif family in ("property", "vehicle"):
            balance = valuations.get(a["id"], recorded)   # prefer a manual valuation
        else:                                              # cash / credit / loan
            balance = recorded
            if family == "loan":
                loan = loans.get(a["id"])

        accounts.append(MflAccount(
            source_id=a["id"],
            source_ref=a["iri"] or f"account:{a['id']}",
            name=a["name"] or "",
            family=family,
            type=a["type"] or "",
            currency=currency,
            is_liability=bool(a["is_liability"]),
            balance=balance,
            opening_balance=opening,
            holdings=holdings,
            loan=loan,
        ))

    budget = _budget(con, tables, warnings)
    fx_rates = _fx_rates(con, tables)

    return MflSnapshot(
        source_path=path,
        schema_version=schema_version,
        person_name=person_name,
        base_currency=base_currency,
        accounts=accounts,
        budget=budget,
        fx_rates=fx_rates,
        warnings=warnings,
    )


def _securities(con, tables):
    """Return (security_id -> meta dict, security_id -> latest unit price)."""
    if "security" not in tables:
        return {}, {}
    meta = {}
    for s in con.execute(
        "SELECT id, name, symbol, instrument_type, price_multiplier FROM security"
    ):
        meta[s["id"]] = {
            "name": s["name"] or "",
            "symbol": s["symbol"] or "",
            "instrument_type": s["instrument_type"] or "stock",
            "multiplier": float(s["price_multiplier"]) if s["price_multiplier"] is not None else 1.0,
        }
    latest = {}
    if "security_price" in tables:
        for p in con.execute(
            "SELECT security_id, price FROM security_price WHERE (security_id, price_date) "
            "IN (SELECT security_id, MAX(price_date) FROM security_price GROUP BY security_id)"
        ):
            latest[p["security_id"]] = float(p["price"])
    return meta, latest


def _holdings_for_account(con, account_id, sec_meta, latest_price):
    """Replay the share legs of one investment account into open positions.

    Returns (list[MflHolding], total_priced_market_value: Decimal).
    """
    net_qty: dict[int, float] = {}
    for t in con.execute(
        "SELECT action, security_id, quantity FROM txn WHERE account_id=? "
        "AND security_id IS NOT NULL AND action IS NOT NULL "
        "ORDER BY posted_date, id", (account_id,)
    ):
        action = _norm(t["action"])
        sid = t["security_id"]
        qty = float(t["quantity"]) if t["quantity"] is not None else 0.0
        if action in SPLIT_ACTIONS:
            if qty > 0:
                net_qty[sid] = net_qty.get(sid, 0.0) * qty
        elif action in SHARE_IN_ACTIONS:
            net_qty[sid] = net_qty.get(sid, 0.0) + qty
        elif action in SHARE_OUT_ACTIONS:
            net_qty[sid] = net_qty.get(sid, 0.0) - qty

    holdings: list[MflHolding] = []
    market_value = Decimal(0)
    for sid, qty in net_qty.items():
        if abs(qty) <= _EPS:
            continue
        meta = sec_meta.get(sid, {})
        price = latest_price.get(sid)
        mult = meta.get("multiplier", 1.0)
        mv = None
        if price is not None:
            mv = _money(Decimal(str(qty)) * Decimal(str(price)) * Decimal(str(mult)))
            market_value += mv
        holdings.append(MflHolding(
            security_id=sid,
            name=meta.get("name", ""),
            symbol=meta.get("symbol", ""),
            instrument_type=meta.get("instrument_type", "stock"),
            quantity=qty,
            price=price,
            price_multiplier=mult,
            market_value=mv,
        ))
    holdings.sort(key=lambda h: (h.symbol or h.name))
    return holdings, market_value


def _latest_valuations(con, tables):
    """account_id -> latest valuation value (Decimal), if any valuations exist."""
    if "valuation" not in tables:
        return {}
    out = {}
    for v in con.execute(
        "SELECT account_id, value FROM valuation WHERE (account_id, valued_on) "
        "IN (SELECT account_id, MAX(valued_on) FROM valuation GROUP BY account_id)"
    ):
        out[v["account_id"]] = _pence_to_decimal(v["value"])
    return out


def _loans(con, tables):
    """account_id -> MflLoan."""
    if "loan" not in tables:
        return {}
    out = {}
    for r in con.execute(
        "SELECT account_id, original_amount, principal_paid, interest_rate, "
        "term_months, payment, start_date FROM loan"
    ):
        original = _pence_to_decimal(r["original_amount"])
        paid = _pence_to_decimal(r["principal_paid"])
        out[r["account_id"]] = MflLoan(
            original_amount=original,
            principal_paid=paid,
            outstanding=original - paid,
            interest_rate=float(r["interest_rate"]) if r["interest_rate"] is not None else None,
            term_months=int(r["term_months"]) if r["term_months"] is not None else None,
            monthly_payment=_pence_to_decimal(r["payment"]),
            start_date=r["start_date"],
        )
    return out


def _budget(con, tables, warnings) -> Optional[MflBudget]:
    """Most-recent budget, with categories rolled up to their top-level parent.

    Per category: total allocation over the budget window → monthly average →
    ×12 annual. Child categories are aggregated into their root ancestor.
    """
    if not {"budget", "budget_line", "budget_allocation", "category"} <= tables:
        return None
    b = con.execute(
        "SELECT id, name, start_month, length_months, currency FROM budget "
        "ORDER BY COALESCE(created_at, start_month) DESC, id DESC LIMIT 1"
    ).fetchone()
    if b is None:
        return None

    # Category tree. MFL's roots (parent_id NULL) are organisational *kinds*
    # — Expense / Income / Transfer / Interest / Uncategorised. The categories a
    # user actually budgets against (Housing, Groceries, Transport, …) are the
    # children of those roots, with finer sub-categories beneath. "Top-level"
    # for MRL therefore means the highest ancestor that sits *below* a kind-root
    # (e.g. Fuel → Transport, Council Tax → Housing), not the kind-root itself.
    cats = {c["id"]: dict(parent=c["parent_id"], name=c["name"] or "", kind=c["kind"] or "")
            for c in con.execute("SELECT id, parent_id, name, kind FROM category")}
    roots = {cid for cid, c in cats.items() if c["parent"] is None}

    def top_level(cid):
        seen = set()
        while cid is not None and cid not in seen:
            parent = cats.get(cid, {}).get("parent")
            if parent is None or parent in roots:
                return cid          # child-of-root (or a root itself) = top level
            seen.add(cid)
            cid = parent
        return cid

    months = int(b["length_months"]) if b["length_months"] else 12
    months = max(months, 1)

    # Sum allocations per category for this budget's lines.
    per_root: dict[int, Decimal] = {}
    for r in con.execute(
        "SELECT bl.category_id cid, COALESCE(SUM(ba.amount),0) total "
        "FROM budget_line bl LEFT JOIN budget_allocation ba ON ba.budget_line_id = bl.id "
        "WHERE bl.budget_id = ? GROUP BY bl.category_id", (b["id"],)
    ):
        rid = top_level(r["cid"])
        if rid is None:
            continue
        per_root[rid] = per_root.get(rid, Decimal(0)) + _pence_to_decimal(r["total"])

    categories = []
    for rid, total in per_root.items():
        if abs(total) <= 0:
            continue
        monthly = (total / months).quantize(Decimal("0.01"))
        categories.append(MflBudgetCategory(
            name=cats.get(rid, {}).get("name", "Uncategorised") or "Uncategorised",
            kind=cats.get(rid, {}).get("kind", ""),
            monthly=monthly,
            annual=(monthly * 12).quantize(Decimal("0.01")),
        ))
    categories.sort(key=lambda c: c.name.lower())
    return MflBudget(
        name=b["name"] or "Budget",
        start_month=b["start_month"],
        length_months=b["length_months"],
        currency=b["currency"],
        categories=categories,
    )


def _fx_rates(con, tables):
    """(base, quote) -> latest rate, for the mapping phase to derive MRL FX."""
    if "fx_rate" not in tables:
        return {}
    out = {}
    for r in con.execute(
        "SELECT base, quote, rate FROM fx_rate WHERE (base, quote, date) IN "
        "(SELECT base, quote, MAX(date) FROM fx_rate GROUP BY base, quote)"
    ):
        out[(r["base"], r["quote"])] = float(r["rate"])
    return out
