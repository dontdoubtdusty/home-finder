from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULTS: Dict[str, Any] = {
    "search": {"latitude": None, "longitude": None, "radius_miles": 5},
    "filters": {
        "rent_min": 0,
        "rent_max": None,
        "beds_min": 0,
        "baths_min": 0,
        "pets": [],
        "amenities_required": [],
        "amenities_preferred": [],
        "exclude_unknown": False,
    },
    "sources": {
        "rentcast": {
            "enabled": True,
            "api_key": "",
            "api_key_env": "RENTCAST_API_KEY",
            "monthly_request_budget": 45,
            "page_size": 500,
            "max_pages": 1,
        },
        "csv_import": {"enabled": True, "folder": "imports"},
        "phone": {"enabled": True},
    },
    "firebase": {
        "enabled": False,
        "service_account": "secrets/firebase-service-account.json",
        "prune_days": 30,
    },
    "scoring": {
        "comp_radius_miles": 1.0,
        "min_comps": 3,
        "below_market_pct": 10,
        "stale_days": 30,
        "price_drop_min_pct": 2,
    },
    "database": "data/homefinder.db",
    "dashboard_data": "dashboard/data.js",
}


class ConfigError(Exception):
    pass


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy config.example.yaml to config.yaml and fill it in."
        )
    with path.open("r", encoding="utf-8") as fh:
        user_cfg = yaml.safe_load(fh) or {}
    cfg = _merge(DEFAULTS, user_cfg)

    search = cfg["search"]
    lat, lon = search.get("latitude"), search.get("longitude")
    if lat is None or lon is None or (float(lat) == 0.0 and float(lon) == 0.0):
        raise ConfigError("Set search.latitude and search.longitude in config.yaml.")
    search["latitude"], search["longitude"] = float(lat), float(lon)
    search["radius_miles"] = float(search["radius_miles"])

    # Resolve file paths relative to the config file's folder.
    root = path.resolve().parent
    cfg["_root"] = str(root)
    for key in ("database", "dashboard_data"):
        cfg[key] = str((root / cfg[key]).resolve())
    sa = cfg["firebase"]["service_account"]
    cfg["firebase"]["service_account"] = str((root / sa).resolve())
    folder = cfg["sources"]["csv_import"]["folder"]
    cfg["sources"]["csv_import"]["folder"] = str((root / folder).resolve())
    return cfg
