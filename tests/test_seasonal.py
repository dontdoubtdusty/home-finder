import tempfile
import unittest
from pathlib import Path

from homefinder.db import Database
from homefinder.models import Listing
from homefinder.seasonal import month_pattern


def row(beds, price, month):
    return {"beds": beds, "price": price, "listed_date": f"{month}-10", "first_seen": "2026-11-21"}


class MonthPatternTest(unittest.TestCase):
    def test_compares_within_bedroom_count(self):
        rows = ([row(1, 800, "2026-01")] * 5 + [row(3, 1600, "2026-01")] * 5 +
                [row(1, 1000, "2026-08")] * 5 + [row(3, 2000, "2026-08")] * 5)
        out = {m["month"]: m for m in month_pattern(rows)}
        # Both sizes are ~11% under their typical price in January and ~11% over in August.
        self.assertLess(out["2026-01"]["pct_vs_typical"], -10)
        self.assertGreater(out["2026-08"]["pct_vs_typical"], 10)
        self.assertEqual(out["2026-01"]["count"], 10)

    def test_skips_thin_months_and_unknowns(self):
        rows = [row(1, 900, "2026-03")] * 4 + [row(None, 900, "2026-03")] * 9 + [row(1, 900, "2026-04")] * 5
        self.assertEqual([m["month"] for m in month_pattern(rows)], ["2026-04"])

    def test_listing_starts_uses_first_price_and_includes_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(str(Path(tmp) / "t.db"))
            l = Listing(source="x", source_id="1", address="1 Main St", price=900, beds=1,
                        listed_date="2026-06-01", price_history=[("2026-06-01", 1000)])
            db.save_snapshot("x", [l], today="2026-06-02")
            db.save_snapshot("x", [], today="2026-07-01")  # now off the market
            starts = db.listing_starts()
            db.close()
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["price"], 1000)
        self.assertEqual(starts[0]["listed_date"], "2026-06-01")


if __name__ == "__main__":
    unittest.main()
