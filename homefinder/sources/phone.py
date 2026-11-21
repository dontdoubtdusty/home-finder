"""Listings added from the phone app (Firestore ``submissions`` collection)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import Listing
from .base import Source, SourceError


def _num(v: Any) -> Optional[float]:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _list(v: Any) -> Optional[List[str]]:
    if v is None:
        return None
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if str(x).strip()]
    return None


def parse_submission(d: Dict[str, Any]) -> Optional[Listing]:
    price = _num(d.get("price"))
    if not price or not (_str(d.get("address")) or _str(d.get("url"))):
        return None
    url = _str(d.get("url"))
    if url and not url.lower().startswith(("http://", "https://")):
        url = None
    created = _str(d.get("updated_at")) or _str(d.get("created_at")) or ""
    history = []
    for h in d.get("history") or []:
        if isinstance(h, dict) and _num(h.get("price")) and _str(h.get("date")):
            history.append((str(h["date"])[:10], float(h["price"])))
    return Listing(
        source=(_str(d.get("source")) or "phone").lower(),
        source_id=str(d["_id"]),
        price=price,
        url=url,
        address=_str(d.get("address")),
        unit=_str(d.get("unit")),
        city=_str(d.get("city")),
        state=_str(d.get("state")),
        zip=_str(d.get("zip")),
        latitude=_num(d.get("latitude")),
        longitude=_num(d.get("longitude")),
        beds=_num(d.get("beds")),
        baths=_num(d.get("baths")),
        sqft=_num(d.get("sqft")),
        pets=_list(d.get("pets")),
        amenities=_list(d.get("amenities")),
        listed_date=_str(d.get("listed_date")),
        observed_date=created[:10] or None,
        price_history=history,
        raw={"phone": True},
    )


class PhoneSource(Source):
    name = "phone"

    def __init__(self, cfg, search, db, store=None):
        super().__init__(cfg, search, db)
        self.store = store

    def fetch(self) -> Optional[List[Listing]]:
        if self.store is None:
            raise SourceError("phone source needs firebase.enabled: true in config.yaml")
        self.complete = True
        return [l for l in (parse_submission(d) for d in self.store.submissions()) if l]
