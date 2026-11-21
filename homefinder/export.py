"""Write scored listings to dashboard/data.js for the local dashboard.

The dashboard loads data.js with a <script> tag (not fetch), so it works when
index.html is opened straight from disk.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional


def _area_summary(listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_beds: Dict[Any, List[float]] = {}
    seen_groups = set()
    for l in listings:
        if l["group_id"] in seen_groups or l.get("beds") is None:
            continue
        seen_groups.add(l["group_id"])
        by_beds.setdefault(l["beds"], []).append(l["price"])
    return [
        {"beds": beds, "count": len(prices), "median": round(median(prices)),
         "min": min(prices), "max": max(prices)}
        for beds, prices in sorted(by_beds.items())
    ]


def build_meta(listings: List[Dict[str, Any]], cfg: Dict[str, Any],
               usage: Dict[str, Any]) -> Dict[str, Any]:
    """Everything about a run except the listings themselves."""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "center": {
            "lat": cfg["search"]["latitude"],
            "lon": cfg["search"]["longitude"],
            "radius_miles": cfg["search"]["radius_miles"],
        },
        "filters": cfg["filters"],
        "scoring": cfg["scoring"],
        "usage": usage,
        "summary": _area_summary(listings),
        "listing_count": len(listings),
    }


def write_dashboard_data(listings: List[Dict[str, Any]], cfg: Dict[str, Any],
                         usage: Dict[str, Any],
                         seasonal: Optional[List[Dict[str, Any]]] = None) -> Path:
    payload = dict(build_meta(listings, cfg, usage), listings=listings)
    if seasonal is not None:
        payload["seasonal"] = seasonal
    out = Path(cfg["dashboard_data"])
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=1, default=str)
    out.write_text(f"window.HOMEFINDER = {body};\n", encoding="utf-8")
    return out
