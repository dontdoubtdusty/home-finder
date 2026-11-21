"""Sync scored listings to Firebase (Firestore) for the phone app.

Firestore layout (rules in firebase/firestore.rules):

    listings/{id}        scored listings, written only by this PC
    meta/summary         search center, filters, area medians, last update
    state/{id}           shared favorite / hidden / note per listing (written by the app)
    submissions/{id}     listings added from the phone (read back here as a source)
    allowed_users/{email} who may sign in to the app

The service-account key gives full access to the project. Keep it out of git
(secrets/ is ignored) and never put it in the app.
"""
from __future__ import annotations

import hashlib
import json
import logging
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

log = logging.getLogger(__name__)

BATCH_SIZE = 400  # Firestore allows 500 writes per batch


def doc_id(listing_id: str) -> str:
    """Firestore document ids can't contain '/'."""
    return listing_id.replace("/", "_")


def _clean(value: Any) -> Any:
    """Make a value Firestore-safe (no tuples, no NaN)."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def _hash(data: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


# --- Storage adapter -----------------------------------------------------------

class FirestoreStore:
    """Thin wrapper so the sync logic can be tested without a real project."""

    def __init__(self, service_account_path: str):
        warnings.filterwarnings("ignore", category=FutureWarning, module="google")
        import firebase_admin
        from firebase_admin import credentials, firestore

        path = Path(service_account_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Firebase service account key not found at {path}. See SETUP.md."
            )
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(str(path)))
        self._fs = firestore
        self.client = firestore.client()

    def listing_status(self) -> Dict[str, Dict[str, Any]]:
        docs = self.client.collection("listings").select(
            ["active", "inactive_since", "_hash"]).stream()
        return {d.id: d.to_dict() or {} for d in docs}

    def _batched(self, ops: List[tuple]) -> None:
        for i in range(0, len(ops), BATCH_SIZE):
            batch = self.client.batch()
            for kind, ref, data in ops[i:i + BATCH_SIZE]:
                if kind == "set":
                    batch.set(ref, data)
                elif kind == "update":
                    batch.update(ref, data)
                else:
                    batch.delete(ref)
            batch.commit()

    def write_listings(self, docs: Dict[str, Dict[str, Any]]) -> None:
        col = self.client.collection("listings")
        self._batched([("set", col.document(k), v) for k, v in docs.items()])

    def mark_inactive(self, ids: Iterable[str], since: str) -> None:
        col = self.client.collection("listings")
        self._batched([("update", col.document(k), {"active": False, "inactive_since": since})
                       for k in ids])

    def delete_listings(self, ids: Iterable[str]) -> None:
        col = self.client.collection("listings")
        self._batched([("delete", col.document(k), None) for k in ids])

    def favorites(self) -> Set[str]:
        q = self.client.collection("state").where("favorite", "==", True).stream()
        return {d.id for d in q}

    def set_meta(self, data: Dict[str, Any]) -> None:
        self.client.collection("meta").document("summary").set(data)

    def submissions(self) -> List[Dict[str, Any]]:
        return [dict(d.to_dict() or {}, _id=d.id)
                for d in self.client.collection("submissions").stream()]

    def allow(self, email: str) -> None:
        self.client.collection("allowed_users").document(email.lower()).set(
            {"added": datetime.now(timezone.utc).isoformat()})

    def disallow(self, email: str) -> None:
        self.client.collection("allowed_users").document(email.lower()).delete()

    def allowed(self) -> List[str]:
        return sorted(d.id for d in self.client.collection("allowed_users").stream())


def open_store(cfg: Dict[str, Any]) -> FirestoreStore:
    return FirestoreStore(cfg["firebase"]["service_account"])


# --- Sync logic ----------------------------------------------------------------

def push(store, scored: List[Dict[str, Any]], meta: Dict[str, Any],
         prune_days: int = 30, today: Optional[str] = None) -> Dict[str, int]:
    """Upload scored listings; deactivate missing ones; prune old unfavorited ones."""
    today = today or date.today().isoformat()
    existing = store.listing_status()

    to_write: Dict[str, Dict[str, Any]] = {}
    current: Set[str] = set()
    for l in scored:
        key = doc_id(l["id"])
        current.add(key)
        data = _clean(dict(l, id=key, active=True, inactive_since=None))
        data["_hash"] = _hash(data)
        old = existing.get(key)
        if old is None or old.get("_hash") != data["_hash"] or not old.get("active"):
            to_write[key] = data
    store.write_listings(to_write)

    gone = [k for k, v in existing.items() if k not in current and v.get("active", True)]
    store.mark_inactive(gone, today)

    cutoff = (date.fromisoformat(today) - timedelta(days=prune_days)).isoformat()
    keep = store.favorites()
    prune = [k for k, v in existing.items()
             if k not in current and k not in keep
             and (v.get("inactive_since") or today) < cutoff]
    store.delete_listings(prune)

    store.set_meta(_clean(dict(meta, updated_at=datetime.now(timezone.utc).isoformat())))
    return {"written": len(to_write), "unchanged": len(current) - len(to_write),
            "deactivated": len(gone), "pruned": len(prune)}
