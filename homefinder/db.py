from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id             TEXT PRIMARY KEY,
    origin         TEXT NOT NULL,  -- the collector that produced it (rentcast, csv_import)
    source         TEXT NOT NULL,  -- the site it was listed on (rentcast, zillow, ...)
    source_id      TEXT NOT NULL,
    url            TEXT,
    address        TEXT,
    unit           TEXT,
    city           TEXT,
    state          TEXT,
    zip            TEXT,
    latitude       REAL,
    longitude      REAL,
    beds           REAL,
    baths          REAL,
    sqft           REAL,
    property_type  TEXT,
    pets           TEXT,   -- JSON list, NULL = unknown
    amenities      TEXT,   -- JSON list, NULL = unknown
    price          REAL NOT NULL,
    listed_date    TEXT,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    raw            TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    listing_id  TEXT NOT NULL,
    observed    TEXT NOT NULL,
    price       REAL NOT NULL,
    PRIMARY KEY (listing_id, observed, price)
);

CREATE TABLE IF NOT EXISTS api_usage (
    source  TEXT NOT NULL,
    month   TEXT NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, month)
);
"""


def _json_or_none(value: Optional[List[str]]) -> Optional[str]:
    return None if value is None else json.dumps(sorted(set(value)))


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- API budget -------------------------------------------------------

    def api_calls(self, source: str, month: str) -> int:
        row = self.conn.execute(
            "SELECT count FROM api_usage WHERE source=? AND month=?", (source, month)
        ).fetchone()
        return row["count"] if row else 0

    def record_api_call(self, source: str, month: str) -> None:
        self.conn.execute(
            "INSERT INTO api_usage(source, month, count) VALUES (?, ?, 1) "
            "ON CONFLICT(source, month) DO UPDATE SET count = count + 1",
            (source, month),
        )
        self.conn.commit()

    # --- Listings ---------------------------------------------------------

    def save_snapshot(self, origin: str, listings: Iterable[Listing],
                      complete: bool = True, today: Optional[str] = None) -> Dict[str, int]:
        """Store listings fetched by one collector (``origin``).

        If ``complete``, this collector's stored listings missing from ``listings``
        are marked inactive.
        """
        today = today or date.today().isoformat()
        seen_ids = set()
        new = updated = 0
        for lst in listings:
            if lst.id in seen_ids:
                continue
            seen_ids.add(lst.id)
            observed = lst.observed_date or today
            existing = self.conn.execute(
                "SELECT first_seen FROM listings WHERE id=?", (lst.id,)
            ).fetchone()
            first_seen = existing["first_seen"] if existing else observed
            if existing:
                updated += 1
            else:
                new += 1
            self.conn.execute(
                """
                INSERT INTO listings (id, origin, source, source_id, url, address, unit, city, state,
                    zip, latitude, longitude, beds, baths, sqft, property_type, pets,
                    amenities, price, listed_date, first_seen, last_seen, active, raw)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
                ON CONFLICT(id) DO UPDATE SET
                    origin=excluded.origin, url=excluded.url, address=excluded.address, unit=excluded.unit,
                    city=excluded.city, state=excluded.state, zip=excluded.zip,
                    latitude=excluded.latitude, longitude=excluded.longitude,
                    beds=excluded.beds, baths=excluded.baths, sqft=excluded.sqft,
                    property_type=excluded.property_type, pets=excluded.pets,
                    amenities=excluded.amenities, price=excluded.price,
                    listed_date=COALESCE(excluded.listed_date, listings.listed_date),
                    last_seen=excluded.last_seen, active=1, raw=excluded.raw
                """,
                (
                    lst.id, origin, lst.source, lst.source_id, lst.url, lst.address, lst.unit,
                    lst.city, lst.state, lst.zip, lst.latitude, lst.longitude, lst.beds,
                    lst.baths, lst.sqft, lst.property_type, _json_or_none(lst.pets),
                    _json_or_none(lst.amenities), lst.price, lst.listed_date, first_seen,
                    observed, json.dumps(lst.raw, default=str),
                ),
            )
            for when, price in lst.price_history:
                self._add_price(lst.id, when, price)
            self._add_price(lst.id, observed, lst.price)

        removed = 0
        if complete:
            query = "UPDATE listings SET active=0 WHERE origin=? AND active=1"
            params: List[Any] = [origin]
            if seen_ids:
                query += f" AND id NOT IN ({','.join('?' * len(seen_ids))})"
                params.extend(seen_ids)
            removed = self.conn.execute(query, params).rowcount
        self.conn.commit()
        return {"new": new, "updated": updated, "removed": removed}

    def _add_price(self, listing_id: str, observed: str, price: float) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO price_history(listing_id, observed, price) VALUES (?,?,?)",
            (listing_id, observed[:10], float(price)),
        )

    def active_listings(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM listings WHERE active=1").fetchall()
        history = self._history_by_listing()
        out = []
        for row in rows:
            d = dict(row)
            d.pop("raw", None)
            d["pets"] = json.loads(d["pets"]) if d["pets"] is not None else None
            d["amenities"] = json.loads(d["amenities"]) if d["amenities"] is not None else None
            d["history"] = history.get(d["id"], [])
            out.append(d)
        return out

    def _history_by_listing(self) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for row in self.conn.execute(
            "SELECT listing_id, observed, price FROM price_history ORDER BY observed"
        ):
            out.setdefault(row["listing_id"], []).append(
                {"date": row["observed"], "price": row["price"]}
            )
        return out
