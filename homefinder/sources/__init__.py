from __future__ import annotations

from typing import Any, Dict, List

from .base import Source, SourceError
from .csv_import import CsvImportSource
from .phone import PhoneSource
from .rentcast import RentCastSource

REGISTRY = {
    RentCastSource.name: RentCastSource,
    CsvImportSource.name: CsvImportSource,
    PhoneSource.name: PhoneSource,
}


def build_sources(cfg: Dict[str, Any], db, store=None) -> List[Source]:
    """Instantiate enabled sources. ``store`` is the Firebase store, if enabled."""
    sources: List[Source] = []
    for name, source_cfg in cfg["sources"].items():
        if not source_cfg.get("enabled", True):
            continue
        cls = REGISTRY.get(name)
        if cls is None:
            raise SourceError(f"Unknown source '{name}' in config.yaml")
        if cls is PhoneSource:
            if store is None:
                continue  # phone submissions only exist when Firebase is on
            sources.append(PhoneSource(source_cfg, cfg["search"], db, store=store))
        else:
            sources.append(cls(source_cfg, cfg["search"], db))
    return sources


__all__ = ["Source", "SourceError", "build_sources", "REGISTRY"]
