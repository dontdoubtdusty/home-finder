"""RentCast long-term rental listings (https://developers.rentcast.io).

Free tier: 50 requests/month. Each page of up to 500 listings is one request.
RentCast does not report pets or amenities, so those are stored as unknown.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

import requests

from ..models import Listing
from .base import Source, SourceError

log = logging.getLogger(__name__)

API_URL = "https://api.rentcast.io/v1/listings/rental/long-term"


def _date_only(value: Optional[str]) -> Optional[str]:
    return value[:10] if value else None


def parse_listing(item: Dict[str, Any]) -> Optional[Listing]:
    price = item.get("price")
    if not price or not item.get("id"):
        return None

    history = []
    for when, event in (item.get("history") or {}).items():
        if isinstance(event, dict) and event.get("price"):
            history.append((when[:10], float(event["price"])))

    return Listing(
        source=RentCastSource.name,
        source_id=str(item["id"]),
        price=float(price),
        url=None,
        address=item.get("addressLine1") or item.get("formattedAddress"),
        unit=item.get("addressLine2"),
        city=item.get("city"),
        state=item.get("state"),
        zip=item.get("zipCode"),
        latitude=item.get("latitude"),
        longitude=item.get("longitude"),
        beds=item.get("bedrooms"),
        baths=item.get("bathrooms"),
        sqft=item.get("squareFootage"),
        property_type=item.get("propertyType"),
        pets=None,
        amenities=None,
        listed_date=_date_only(item.get("listedDate")),
        price_history=history,
        raw=item,
    )


class RentCastSource(Source):
    name = "rentcast"

    def _api_key(self) -> str:
        key = self.cfg.get("api_key") or os.environ.get(
            self.cfg.get("api_key_env") or "RENTCAST_API_KEY", ""
        )
        if not key:
            raise SourceError(
                "No RentCast API key. Set sources.rentcast.api_key in config.yaml "
                "or the RENTCAST_API_KEY environment variable."
            )
        return key

    def fetch(self) -> Optional[List[Listing]]:
        key = self._api_key()
        month = date.today().strftime("%Y-%m")
        budget = int(self.cfg.get("monthly_request_budget", 45))
        page_size = min(int(self.cfg.get("page_size", 500)), 500)
        max_pages = max(int(self.cfg.get("max_pages", 1)), 1)

        listings: List[Listing] = []
        self.complete = False
        for page in range(max_pages):
            used = self.db.api_calls(self.name, month)
            if used >= budget:
                log.warning("RentCast: monthly budget used (%d/%d); skipping.", used, budget)
                return listings if listings else None

            params = {
                "latitude": self.search["latitude"],
                "longitude": self.search["longitude"],
                "radius": self.search["radius_miles"],
                "status": "Active",
                "limit": page_size,
                "offset": page * page_size,
            }
            resp = requests.get(
                API_URL,
                params=params,
                headers={"X-Api-Key": key, "Accept": "application/json"},
                timeout=30,
            )
            self.db.record_api_call(self.name, month)
            if resp.status_code in (401, 403):
                raise SourceError(f"RentCast rejected the API key (HTTP {resp.status_code}).")
            if resp.status_code == 429:
                raise SourceError("RentCast rate limit / quota exceeded (HTTP 429).")
            resp.raise_for_status()

            items = resp.json()
            listings.extend(l for l in (parse_listing(i) for i in items) if l)
            log.info("RentCast page %d: %d listings (requests this month: %d/%d)",
                     page + 1, len(items), used + 1, budget)
            if len(items) < page_size:
                self.complete = True
                break
        else:
            log.warning("RentCast: hit max_pages=%d; results may be incomplete.", max_pages)
        return listings
