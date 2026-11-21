"""Month-by-month rent pattern from your own listing history.

For the "When to move" page. Each listing's first asking price is compared with
the typical (median) price of all listings with the same bedroom count, so a
month full of big houses doesn't look "expensive". Months are grouped by when the
listing went up (listed_date, else when we first saw it).
"""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, List

MIN_PER_MONTH = 5


def month_pattern(rows: List[Dict[str, Any]], min_n: int = MIN_PER_MONTH) -> List[Dict[str, Any]]:
    """[{month: "2026-11", count, pct_vs_typical}] for months with at least min_n listings."""
    rows = [r for r in rows if r.get("beds") is not None and (r.get("price") or 0) > 0
            and (r.get("listed_date") or r.get("first_seen"))]
    by_beds: Dict[float, List[float]] = {}
    for r in rows:
        by_beds.setdefault(r["beds"], []).append(r["price"])
    typical = {b: median(p) for b, p in by_beds.items() if len(p) >= 2}

    by_month: Dict[str, List[float]] = {}
    for r in rows:
        t = typical.get(r["beds"])
        if not t:
            continue
        month = str(r.get("listed_date") or r["first_seen"])[:7]
        by_month.setdefault(month, []).append(r["price"] / t - 1)
    return [
        {"month": m, "count": len(v), "pct_vs_typical": round(median(v) * 100, 1)}
        for m, v in sorted(by_month.items()) if len(v) >= min_n
    ]
