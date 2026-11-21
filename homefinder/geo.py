from __future__ import annotations

import math
from typing import Optional

EARTH_RADIUS_MILES = 3958.8


def miles_between(lat1: Optional[float], lon1: Optional[float],
                  lat2: Optional[float], lon2: Optional[float]) -> Optional[float]:
    """Great-circle distance in miles, or None if any coordinate is missing."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))
