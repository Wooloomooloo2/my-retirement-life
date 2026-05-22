"""
Live exchange-rate client.

This module is the SINGLE outbound-network integration point for My Retirement
Life. Everything else in the application runs locally against the bundled
ontology and the user's local triple store; this is the only component that
contacts the internet during normal use.

Provider: open.er-api.com — the free, no-API-key "Open" tier of
ExchangeRate-API. Endpoint:

    GET https://open.er-api.com/v6/latest/<BASE_CURRENCY_CODE>

Transparency / privacy (see docs/adr/ADR-016-live-exchange-rates.md):
  * The request transmits exactly ONE piece of information: the user's base
    currency code (e.g. "GBP"), as the final path segment of the URL. No
    account balances, names, dates, or any other personal or financial data
    ever leave the machine.
  * The call is only ever made when the user explicitly triggers a rate
    refresh from the Accounts page. There is no background polling.
  * Responses are NOT cached (per the design decision in ADR-016): each
    refresh is a fresh live lookup. When the machine is offline the refresh
    fails cleanly and any existing user-entered rates are left untouched.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

# Surfaced in the UI so the user can see exactly where rates come from.
PROVIDER_NAME = "open.er-api.com"
PROVIDER_URL = "https://www.exchangerate-api.com"

_ENDPOINT = "https://open.er-api.com/v6/latest/{base}"
_TIMEOUT_SECONDS = 15
_HEADERS = {"User-Agent": "MyRetirementLife/1.0 (exchange-rate refresh)"}


class FxError(Exception):
    """Raised when live exchange rates cannot be fetched or parsed.

    Carries a human-readable message suitable for showing to the user.
    """


def fetch_rates(base_code: str) -> dict:
    """
    Fetch today's exchange rates for a base currency.

    Rates are returned in the provider's native orientation:
        1 unit of base_code = N units of each listed currency.

    Args:
        base_code: ISO 4217 code of the base/reference currency, e.g. "GBP".

    Returns:
        {
            "base":     "GBP",
            "as_of":    "Fri, 22 May 2026 00:00:01 +0000",  # provider timestamp
            "provider": "open.er-api.com",
            "rates":    {"USD": 1.27, "EUR": 1.17, "INR": 106.4, ...},
        }

    Raises:
        FxError: on any network, HTTP, or response-format problem. Callers
                 should catch this and leave existing rates unchanged.
    """
    base = (base_code or "").strip().upper()
    if not base:
        raise FxError("No base currency code provided.")

    url = _ENDPOINT.format(base=base)
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        # No connectivity, DNS failure, timeout, or HTTP error status.
        raise FxError(f"could not reach {PROVIDER_NAME} ({exc})") from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise FxError(f"unexpected response from {PROVIDER_NAME}") from exc

    if payload.get("result") != "success":
        detail = payload.get("error-type", "unknown error")
        raise FxError(f"{PROVIDER_NAME} returned an error: {detail}")

    rates = payload.get("rates")
    if not isinstance(rates, dict) or not rates:
        raise FxError(f"{PROVIDER_NAME} returned no rates")

    return {
        "base":     payload.get("base_code", base),
        "as_of":    payload.get("time_last_update_utc", ""),
        "provider": PROVIDER_NAME,
        "rates":    {str(k): float(v) for k, v in rates.items()
                     if isinstance(v, (int, float))},
    }
