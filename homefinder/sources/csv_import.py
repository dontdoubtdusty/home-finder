"""Import listings from CSV files you collect by hand (or from other tools).

Use this for any site without an API: copy listings you find on Zillow,
Apartments.com, Craigslist, Facebook, etc. into a CSV in the imports folder.
See templates/import_template.csv for the columns.

Every CSV in the folder is read on each run, so deleting a row or file marks
that listing inactive. Add an ``observed_date`` column and keep old rows with
earlier dates to record price changes over time.
"""
from __future__ import annotations

import csv
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional

from ..dedupe import address_key
from ..models import Listing
from .base import Source

log = logging.getLogger(__name__)

# Friendly spellings people use -> canonical keys used in config.yaml
AMENITY_ALIASES = {
    "washer/dryer": "in_unit_laundry",
    "w/d": "in_unit_laundry",
    "w/d in unit": "in_unit_laundry",
    "in-unit laundry": "in_unit_laundry",
    "laundry in unit": "in_unit_laundry",
    "laundry": "laundry_on_site",
    "laundry on site": "laundry_on_site",
    "air conditioning": "ac",
    "a/c": "ac",
    "fitness center": "gym",
    "off-street parking": "parking",
}


def _num(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _list(value: Optional[str], aliases: Optional[Dict[str, str]] = None) -> Optional[List[str]]:
    """Semicolon-separated list. Blank cell = unknown (None); 'none' = known empty."""
    if value is None or not value.strip():
        return None
    if value.strip().lower() == "none":
        return []
    out = []
    for part in value.split(";"):
        p = part.strip().lower()
        if not p:
            continue
        p = (aliases or {}).get(p, p).replace(" ", "_").replace("-", "_")
        out.append(p)
    return out


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_row(row: Dict[str, str]) -> Optional[Listing]:
    row = {(k or "").strip().lower(): v for k, v in row.items()}
    price = _num(row.get("price", ""))
    address = _clean(row.get("address"))
    url = _clean(row.get("url"))
    if not price or not (address or url):
        return None

    source = (_clean(row.get("source")) or "manual").lower()
    unit = _clean(row.get("unit"))
    zip_code = _clean(row.get("zip"))
    ident = url or address_key(address, unit, zip_code) or address
    source_id = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:16]

    observed = _clean(row.get("observed_date"))
    return Listing(
        source=source,
        source_id=source_id,
        price=price,
        url=url,
        address=address,
        unit=unit,
        city=_clean(row.get("city")),
        state=_clean(row.get("state")),
        zip=zip_code,
        latitude=_num(row.get("latitude", "")),
        longitude=_num(row.get("longitude", "")),
        beds=_num(row.get("beds", "")),
        baths=_num(row.get("baths", "")),
        sqft=_num(row.get("sqft", "")),
        pets=_list(row.get("pets")),
        amenities=_list(row.get("amenities"), AMENITY_ALIASES),
        listed_date=_clean(row.get("listed_date")),
        observed_date=observed,
        raw={"csv": True},
    )


class CsvImportSource(Source):
    name = "csv_import"

    def fetch(self) -> Optional[List[Listing]]:
        folder = Path(self.cfg["folder"])
        folder.mkdir(parents=True, exist_ok=True)
        # Keep only the newest row per listing; older rows become price history.
        latest: Dict[str, Listing] = {}
        history: Dict[str, List] = {}
        for path in sorted(folder.glob("*.csv")):
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for n, row in enumerate(csv.DictReader(fh), start=2):
                    lst = parse_row(row)
                    if lst is None:
                        log.warning("%s line %d: skipped (needs price and address or url)",
                                    path.name, n)
                        continue
                    history.setdefault(lst.id, []).append(
                        (lst.observed_date, lst.price)
                    )
                    prev = latest.get(lst.id)
                    if prev is None or (lst.observed_date or "") >= (prev.observed_date or ""):
                        latest[lst.id] = lst
        for lid, lst in latest.items():
            lst.price_history = [(d, p) for d, p in history[lid] if d]
        self.complete = True
        return list(latest.values())
