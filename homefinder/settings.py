"""Search settings edited from the app's Settings screen.

Saved to data/settings.json (git-ignored) and layered over config.yaml by
load_config, so config.yaml (comments, API key) is never rewritten.
Only the search area, filters and deal-tag strictness can be changed here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

AMENITIES = ["in_unit_laundry", "laundry_on_site", "parking", "garage", "dishwasher", "ac",
             "gym", "pool", "elevator", "balcony", "furnished"]
PETS = ["cat", "dog"]
BEDS = [0, 1, 2, 3, 4]  # 4 means "4 or more"
PRESETS = {
    "more": {"below_market_pct": 5, "stale_days": 21, "price_drop_min_pct": 1},
    "balanced": {"below_market_pct": 10, "stale_days": 30, "price_drop_min_pct": 2},
    "great": {"below_market_pct": 15, "stale_days": 45, "price_drop_min_pct": 5},
}


class SettingsError(ValueError):
    pass


def load_overrides(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_overrides(path: Path, overrides: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    tmp.replace(path)


def current(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The settings the screen shows (never includes API keys)."""
    f, s, sc = cfg["filters"], cfg["search"], cfg["scoring"]
    preset = next((name for name, vals in PRESETS.items()
                   if all(sc.get(k) == v for k, v in vals.items())), "custom")
    return {
        "latitude": s["latitude"], "longitude": s["longitude"], "radius_miles": s["radius_miles"],
        "rent_min": f.get("rent_min") or 0, "rent_max": f.get("rent_max"),
        "beds": list(f.get("beds") or []), "beds_min": f.get("beds_min") or 0,
        "baths_min": f.get("baths_min") or 0,
        "pets": list(f.get("pets") or []),
        "amenities_required": list(f.get("amenities_required") or []),
        "amenities_preferred": list(f.get("amenities_preferred") or []),
        "exclude_unknown": bool(f.get("exclude_unknown")),
        "deal_preset": preset,
        "options": {"amenities": AMENITIES, "pets": PETS, "beds": BEDS,
                    "presets": list(PRESETS)},
    }


def _num(v: Any, name: str, lo: float, hi: float, allow_none: bool = False):
    if v is None or v == "":
        if allow_none:
            return None
        raise SettingsError(f"{name} is required")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SettingsError(f"{name} must be a number")
    if not lo <= x <= hi:
        raise SettingsError(f"{name} must be between {lo:g} and {hi:g}")
    return int(x) if x.is_integer() else x


def _subset(v: Any, allowed: List[Any], name: str) -> List[Any]:
    if not isinstance(v, list):
        raise SettingsError(f"{name} must be a list")
    bad = [x for x in v if x not in allowed]
    if bad:
        raise SettingsError(f"Unknown {name}: {bad}")
    return sorted(set(v), key=allowed.index)


def validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a Settings-screen payload into config overrides, or raise SettingsError."""
    if not isinstance(payload, dict):
        raise SettingsError("Settings must be an object")
    rent_min = _num(payload.get("rent_min") or 0, "Min rent", 0, 100000)
    rent_max = _num(payload.get("rent_max"), "Max rent", 0, 100000, allow_none=True)
    if rent_max is not None and rent_max < rent_min:
        raise SettingsError("Max rent must be at least the min rent")
    required = _subset(payload.get("amenities_required", []), AMENITIES, "must-have amenities")
    preferred = [a for a in _subset(payload.get("amenities_preferred", []), AMENITIES,
                                    "nice-to-have amenities") if a not in required]
    preset = payload.get("deal_preset", "balanced")
    if preset not in PRESETS:
        raise SettingsError("Unknown deal setting")
    return {
        "search": {
            "latitude": _num(payload.get("latitude"), "Latitude", -90, 90),
            "longitude": _num(payload.get("longitude"), "Longitude", -180, 180),
            "radius_miles": _num(payload.get("radius_miles"), "Search radius", 0.5, 50),
        },
        "filters": {
            "rent_min": rent_min,
            "rent_max": rent_max,
            "beds": _subset(payload.get("beds", []), BEDS, "bedroom choices"),
            "beds_min": 0,  # the bedroom choices replace the old minimum
            "baths_min": _num(payload.get("baths_min") or 0, "Bathrooms", 0, 10),
            "pets": _subset(payload.get("pets", []), PETS, "pets"),
            "amenities_required": required,
            "amenities_preferred": preferred,
            "exclude_unknown": bool(payload.get("exclude_unknown")),
        },
        "scoring": dict(PRESETS[preset]),
    }
