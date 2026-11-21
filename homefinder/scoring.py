"""Filter listings and score how good a deal each one is.

Deal signals (each listed in ``flags`` when it fires):

* below_market  - price is at least ``below_market_pct`` under the median of
                  comparable listings (same beds, within ``comp_radius_miles``).
                  Uses price per sqft when both sides have square footage.
* price_drop    - current price is at least ``price_drop_min_pct`` under the
                  highest price recorded for the listing.
* stale         - on the market at least ``stale_days`` (negotiation leverage).
* cheapest_site - the same unit is listed on several sites and this is the
                  cheapest copy.

The score is roughly "percent of value": percent below market + percent of price
drops + small bonuses for staleness, cross-site savings and preferred amenities.
"""
from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from .dedupe import group_duplicates
from .geo import miles_between


def _days_between(start: Optional[str], end: str) -> Optional[int]:
    if not start:
        return None
    try:
        return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days
    except ValueError:
        return None


def check_filters(l: Dict[str, Any], f: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (passes, unknowns). ``unknowns`` names requirements we couldn't verify."""
    price = l["price"]
    if f.get("rent_min") and price < f["rent_min"]:
        return False, []
    if f.get("rent_max") and price > f["rent_max"]:
        return False, []
    if f.get("beds_min") and l.get("beds") is not None and l["beds"] < f["beds_min"]:
        return False, []
    if f.get("baths_min") and l.get("baths") is not None and l["baths"] < f["baths_min"]:
        return False, []

    unknowns: List[str] = []
    if f.get("beds_min") and l.get("beds") is None:
        unknowns.append("beds")
    if f.get("baths_min") and l.get("baths") is None:
        unknowns.append("baths")

    for field, wanted in (("pets", f.get("pets") or []),
                          ("amenities", f.get("amenities_required") or [])):
        if not wanted:
            continue
        have = l.get(field)
        if have is None:
            unknowns.append(field)
        elif not set(wanted) <= set(have):
            return False, []

    if unknowns and f.get("exclude_unknown"):
        return False, unknowns
    return True, unknowns


def _near(a: Dict[str, Any], b: Dict[str, Any], limit: float) -> bool:
    d = miles_between(a.get("latitude"), a.get("longitude"),
                      b.get("latitude"), b.get("longitude"))
    return d is not None and d <= limit


def _comp_value(l: Dict[str, Any], use_sqft: bool) -> float:
    return l["price"] / l["sqft"] if use_sqft else l["price"]


def score_listings(listings: List[Dict[str, Any]], cfg: Dict[str, Any],
                   today: Optional[str] = None) -> List[Dict[str, Any]]:
    """Annotate and return listings inside the search radius, best deals first.

    Listings outside the radius are dropped. Listings failing filters are kept
    with ``passes_filters = False`` so the dashboard can toggle them.
    """
    today = today or date.today().isoformat()
    search, filters, sc = cfg["search"], cfg["filters"], cfg["scoring"]

    in_area = []
    for l in listings:
        d = miles_between(search["latitude"], search["longitude"],
                          l.get("latitude"), l.get("longitude"))
        if d is not None and d > search["radius_miles"]:
            continue
        l = dict(l)
        l["distance_miles"] = None if d is None else round(d, 2)
        in_area.append(l)

    groups = group_duplicates(in_area)
    members: Dict[str, List[Dict[str, Any]]] = {}
    for l in in_area:
        l["group_id"] = groups[l["id"]]
        members.setdefault(l["group_id"], []).append(l)

    # A listing with no coordinates borrows them from a matched copy on another site.
    for l in in_area:
        if l.get("latitude") is None:
            donor = next((m for m in members[l["group_id"]] if m.get("latitude") is not None), None)
            if donor:
                l["latitude"], l["longitude"] = donor["latitude"], donor["longitude"]
                l["distance_miles"] = donor["distance_miles"]

    # One representative (cheapest) per unit so duplicates don't skew comps.
    reps = [min(ms, key=lambda x: x["price"]) for ms in members.values()]

    preferred = set(filters.get("amenities_preferred") or [])
    for l in in_area:
        flags: List[str] = []
        score = 0.0
        same_group = members[l["group_id"]]

        # --- Below market -------------------------------------------------
        comps = [
            r for r in reps
            if r["group_id"] != l["group_id"]
            and r.get("beds") == l.get("beds")
            and _near(l, r, sc["comp_radius_miles"])
        ]
        sqft_comps = [c for c in comps if c.get("sqft")]
        use_sqft = bool(l.get("sqft")) and len(sqft_comps) >= sc["min_comps"]
        pool = sqft_comps if use_sqft else comps
        l["comp_count"] = len(pool)
        l["comp_basis"] = "price/sqft" if use_sqft else "price"
        l["market_median"] = None
        l["pct_below_market"] = None
        if l.get("beds") is not None and len(pool) >= sc["min_comps"]:
            med = median(_comp_value(c, use_sqft) for c in pool)
            pct = (med - _comp_value(l, use_sqft)) / med * 100
            l["market_median"] = round(med * l["sqft"], 0) if use_sqft else round(med, 0)
            l["pct_below_market"] = round(pct, 1)
            score += pct
            if pct >= sc["below_market_pct"]:
                flags.append("below_market")

        # --- Price drops ----------------------------------------------------
        history = l.get("history") or []
        peak = max([h["price"] for h in history] + [l["price"]])
        drop_pct = (peak - l["price"]) / peak * 100 if peak else 0.0
        l["peak_price"] = peak
        l["pct_price_drop"] = round(drop_pct, 1)
        if drop_pct >= sc["price_drop_min_pct"]:
            flags.append("price_drop")
            score += drop_pct

        # --- Days on market -------------------------------------------------
        listed = min(
            [x for x in (l.get("listed_date"), l.get("first_seen")) if x] or [today]
        )
        dom = _days_between(listed, today) or 0
        l["days_on_market"] = dom
        if dom >= sc["stale_days"]:
            flags.append("stale")
            score += min(dom / sc["stale_days"], 3) * 2

        # --- Same unit on several sites --------------------------------------
        sites = {m["source"] for m in same_group}
        l["other_listings"] = [
            {"id": m["id"], "source": m["source"], "price": m["price"], "url": m.get("url")}
            for m in same_group if m["id"] != l["id"]
        ]
        l["site_count"] = len(sites)
        if len(sites) > 1:
            prices = [m["price"] for m in same_group]
            spread = max(prices) - min(prices)
            l["cross_site_spread"] = spread
            if l["price"] == min(prices) and spread > 0:
                flags.append("cheapest_site")
                score += spread / max(prices) * 100
        else:
            l["cross_site_spread"] = 0

        # --- Filters & preferences ------------------------------------------
        passes, unknowns = check_filters(l, filters)
        l["passes_filters"] = passes
        l["unknown"] = unknowns
        if preferred and l.get("amenities"):
            score += 2 * len(preferred & set(l["amenities"]))

        l["flags"] = flags
        l["score"] = round(score, 1)

    in_area.sort(key=lambda x: (not x["passes_filters"], -x["score"]))
    return in_area
