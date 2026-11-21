from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Listing:
    """One rental listing as reported by one source.

    ``pets`` and ``amenities`` are ``None`` when the source does not report them
    (unknown), and a list (possibly empty) when it does.
    """

    source: str
    source_id: str
    price: float
    url: Optional[str] = None
    address: Optional[str] = None
    unit: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    property_type: Optional[str] = None
    pets: Optional[List[str]] = None
    amenities: Optional[List[str]] = None
    listed_date: Optional[str] = None  # ISO date (YYYY-MM-DD)
    observed_date: Optional[str] = None  # when this price was seen; defaults to today
    # Earlier (date, price) points reported by the source itself.
    price_history: List[Tuple[str, float]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"
