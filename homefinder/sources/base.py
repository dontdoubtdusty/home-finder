from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import Listing


class SourceError(Exception):
    pass


class Source:
    """A listing source.

    ``fetch`` returns the source's current listings in the search area, or ``None``
    when it skipped fetching (e.g. API budget used up), which leaves previously
    stored listings untouched.

    If ``complete`` is True after a fetch, the result is the source's full set, so
    stored listings missing from it are marked inactive. A partial fetch (e.g. the
    budget ran out mid-pagination) sets ``complete`` to False and only adds/updates.
    """

    name = "base"

    def __init__(self, cfg: Dict[str, Any], search: Dict[str, Any], db):
        self.cfg = cfg
        self.search = search
        self.db = db
        self.complete = True

    def fetch(self) -> Optional[List[Listing]]:
        raise NotImplementedError
