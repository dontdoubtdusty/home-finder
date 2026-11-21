"""Step 1: work out an affordable rent from income, bills and savings.

Three methods; the safe budget is the lowest of the ones that apply:

* rule30    - rent + utilities <= 30% of gross monthly income
* rule40x   - landlords' check: yearly gross income >= 40 x monthly rent
* bills     - take-home pay - monthly bills - utilities = left for rent

Move-in cost for a given rent = rent x (1 + deposit months) + pet deposit + other
(first month + security deposit + pet deposit + fees/movers).

Saved to data/budget.json (git-ignored, never synced to the phone).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

ROUND_TO = 25
METHODS = {
    "rule30": "30% of income",
    "rule40x": "Landlord 40x rule",
    "bills": "Take-home minus bills",
}


class BudgetError(ValueError):
    pass


def _money(v: Any, name: str, allow_blank: bool = True) -> float:
    if v is None or v == "":
        if allow_blank:
            return 0.0
        raise BudgetError(f"{name} is required")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise BudgetError(f"{name} must be a number")
    if not 0 <= x <= 10_000_000:
        raise BudgetError(f"{name} must be between 0 and 10,000,000")
    return x


def _text(v: Any, limit: int = 40) -> str:
    return str(v or "").strip()[:limit]


def round_down(x: float) -> int:
    return int(math.floor(x / ROUND_TO) * ROUND_TO)


def clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate raw input from the Budget screen into the stored shape."""
    if not isinstance(payload, dict):
        raise BudgetError("Budget must be an object")
    earners = payload.get("earners") or []
    bills = payload.get("bills") or []
    if not isinstance(earners, list) or not isinstance(bills, list):
        raise BudgetError("Bad budget data")
    if len(earners) > 10 or len(bills) > 40:
        raise BudgetError("Too many rows")
    out_e = []
    for i, e in enumerate(earners, 1):
        if not isinstance(e, dict):
            raise BudgetError("Bad income row")
        period = e.get("gross_period", "year")
        if period not in ("year", "month"):
            raise BudgetError("Pay period must be 'year' or 'month'")
        out_e.append({
            "name": _text(e.get("name")) or f"Person {i}",
            "gross": _money(e.get("gross"), "Gross pay"),
            "gross_period": period,
            "take_home": _money(e.get("take_home"), "Take-home pay"),
        })
    out_b = []
    for b in bills:
        if not isinstance(b, dict):
            raise BudgetError("Bad bill row")
        out_b.append({"name": _text(b.get("name")) or "Bill",
                      "amount": _money(b.get("amount"), "Bill amount")})
    deposit_months = _money(payload.get("deposit_months", 1), "Deposit")
    if deposit_months > 3:
        raise BudgetError("Deposit must be 3 months of rent or less")
    return {
        "earners": out_e,
        "bills": out_b,
        "utilities": _money(payload.get("utilities"), "Utilities"),
        "savings": _money(payload.get("savings"), "Savings"),
        "deposit_months": deposit_months,
        "pet_deposit": _money(payload.get("pet_deposit"), "Pet deposit"),
        "other_move_in": _money(payload.get("other_move_in"), "Other move-in costs"),
    }


def compute(b: Dict[str, Any]) -> Dict[str, Any]:
    """Budget results for a cleaned budget."""
    gross_m = sum(e["gross"] / 12 if e["gross_period"] == "year" else e["gross"]
                  for e in b["earners"])
    take_home = sum(e["take_home"] for e in b["earners"])
    bills = sum(x["amount"] for x in b["bills"])
    util = b["utilities"]

    methods: List[Dict[str, Any]] = []
    if gross_m > 0:
        methods.append({"key": "rule30", "label": METHODS["rule30"],
                        "amount": round_down(max(0.0, 0.30 * gross_m - util)),
                        "how": f"30% of ${gross_m:,.0f}/mo gross = ${0.30 * gross_m:,.0f}, "
                               f"minus ${util:,.0f} utilities"})
        methods.append({"key": "rule40x", "label": METHODS["rule40x"],
                        "amount": round_down(gross_m * 12 / 40),
                        "how": f"${gross_m * 12:,.0f}/yr gross ÷ 40 (what landlords check)"})
    if take_home > 0:
        methods.append({"key": "bills", "label": METHODS["bills"],
                        "amount": round_down(max(0.0, take_home - bills - util)),
                        "how": f"${take_home:,.0f} take-home − ${bills:,.0f} bills − "
                               f"${util:,.0f} utilities"})

    budget: Optional[int] = None
    limited_by: Optional[str] = None
    if methods:
        low = min(methods, key=lambda m: m["amount"])
        budget, limited_by = low["amount"], low["key"]

    dm = b["deposit_months"]
    fixed = b["pet_deposit"] + b["other_move_in"]
    move_in_max: Optional[int] = None
    if b["savings"] > 0:
        move_in_max = round_down(max(0.0, (b["savings"] - fixed) / (1 + dm)))
    return {
        "gross_monthly": round(gross_m, 2),
        "take_home_monthly": round(take_home, 2),
        "bills_monthly": round(bills, 2),
        "methods": methods,
        "budget": budget,
        "limited_by": limited_by,
        "move_in": {
            "savings": b["savings"], "deposit_months": dm, "fixed": fixed,
            "max_rent_by_savings": move_in_max,
            "at_budget": None if budget is None else round(budget * (1 + dm) + fixed, 2),
        },
    }


def move_in_cost(rent: float, b: Dict[str, Any]) -> float:
    return rent * (1 + b["deposit_months"]) + b["pet_deposit"] + b["other_move_in"]


def load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return clean(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save(path: Path, b: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(b, indent=2), encoding="utf-8")
    tmp.replace(path)
