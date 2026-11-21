"""Detect the same unit listed on more than one site."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .geo import miles_between

STREET_ABBR = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "boulevard": "blvd",
    "drive": "dr", "lane": "ln", "court": "ct", "place": "pl", "terrace": "ter",
    "parkway": "pkwy", "highway": "hwy", "circle": "cir", "square": "sq",
    "trail": "trl", "way": "way", "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
}

UNIT_RE = re.compile(
    r"(?:\b(?:apt|apartment|unit|ste|suite|no)\b\.?|#)\s*#?\s*([a-z0-9][a-z0-9-]*)",
    re.IGNORECASE,
)

# Same building, no address match: treat as the same unit only if this close.
GEO_MATCH_MILES = 0.02  # ~30 m


def _norm_unit(unit: Optional[str]) -> str:
    if not unit:
        return ""
    m = UNIT_RE.search(unit)
    u = m.group(1) if m else unit
    u = re.sub(r"[^a-z0-9]", "", u.lower())
    return u.lstrip("0") or u


def address_key(address: Optional[str], unit: Optional[str] = None,
                zip_code: Optional[str] = None) -> Optional[str]:
    """Normalized 'street|unit|zip' key, or None if there's no usable street address."""
    if not address:
        return None
    street = address.split(",")[0].lower()
    m = UNIT_RE.search(street)
    if m:
        unit = unit or m.group(0)
        street = street[: m.start()] + street[m.end():]
    tokens = [STREET_ABBR.get(t, t) for t in re.findall(r"[a-z0-9]+", street)]
    # Need a house number to be a real address.
    if not tokens or not tokens[0][0].isdigit():
        return None
    z = re.sub(r"\D", "", zip_code or "")[:5]
    return f"{' '.join(tokens)}|{_norm_unit(unit)}|{z}"


def _same_by_geo(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    d = miles_between(a.get("latitude"), a.get("longitude"),
                      b.get("latitude"), b.get("longitude"))
    if d is None or d > GEO_MATCH_MILES:
        return False
    if a.get("beds") != b.get("beds"):
        return False
    if _norm_unit(a.get("unit")) != _norm_unit(b.get("unit")):
        return False
    sa, sb = a.get("sqft"), b.get("sqft")
    # Without square footage, a whole apartment building would collapse into one.
    if not sa or not sb:
        return False
    return abs(sa - sb) / max(sa, sb) <= 0.03


def group_duplicates(listings: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map each listing id to a group id shared by listings for the same unit."""
    parent = {l["id"]: l["id"] for l in listings}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    # Bucket by street+unit; merge when ZIPs agree or one side has no ZIP.
    buckets: Dict[str, List[tuple]] = {}
    for l in listings:
        key = address_key(l.get("address"), l.get("unit"), l.get("zip"))
        if not key:
            continue
        street_unit, _, z = key.rpartition("|")
        for other_id, other_zip in buckets.get(street_unit, []):
            if not z or not other_zip or z == other_zip:
                union(other_id, l["id"])
        buckets.setdefault(street_unit, []).append((l["id"], z))

    # Geo fallback only across different sources (same source = different listing).
    for i, a in enumerate(listings):
        for b in listings[i + 1:]:
            if a["source"] != b["source"] and _same_by_geo(a, b):
                union(a["id"], b["id"])

    return {l["id"]: find(l["id"]) for l in listings}
