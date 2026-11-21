import copy
import tempfile
import unittest
from pathlib import Path

from homefinder.config import DEFAULTS
from homefinder.db import Database
from homefinder.dedupe import address_key, group_duplicates
from homefinder.models import Listing
from homefinder.scoring import check_filters, score_listings
from homefinder.sources.csv_import import CsvImportSource, parse_row
from homefinder.sources.rentcast import parse_listing

CENTER = (40.0, -75.0)


def cfg(**overrides):
    c = copy.deepcopy(DEFAULTS)
    c["search"].update(latitude=CENTER[0], longitude=CENTER[1], radius_miles=5)
    for section, values in overrides.items():
        c[section].update(values)
    return c


def row(id_, price, beds=2, lat=40.0, lon=-75.0, source="rentcast", **kw):
    d = {"id": f"{source}:{id_}", "source": source, "price": price, "beds": beds,
         "baths": 1, "sqft": None, "latitude": lat, "longitude": lon, "address": None,
         "unit": None, "zip": None, "pets": None, "amenities": None,
         "listed_date": None, "first_seen": "2026-11-01", "history": []}
    d.update(kw)
    return d


class AddressKeyTest(unittest.TestCase):
    def test_normalizes_suffixes_and_units(self):
        a = address_key("123 Main Street Apt 4B, Springfield, IL", None, "62701-1234")
        b = address_key("123 main st", "#4b", "62701")
        self.assertEqual(a, b)
        self.assertEqual(a, "123 main st|4b|62701")

    def test_leading_zero_unit(self):
        self.assertEqual(address_key("5 Oak Ave", "Unit 04"), address_key("5 Oak Avenue", "4"))

    def test_requires_house_number(self):
        self.assertIsNone(address_key("Main Street", None, None))
        self.assertIsNone(address_key(None))


class DedupeTest(unittest.TestCase):
    def test_same_address_different_sites(self):
        ls = [
            row("a", 2000, address="10 Elm Street", unit="2", zip="19000"),
            row("b", 1900, source="zillow", address="10 Elm St #2", zip=""),
            row("c", 1900, source="zillow", address="10 Elm St #3"),
        ]
        g = group_duplicates(ls)
        self.assertEqual(g["rentcast:a"], g["zillow:b"])
        self.assertNotEqual(g["rentcast:a"], g["zillow:c"])

    def test_geo_fallback_needs_sqft(self):
        a = row("a", 2000, sqft=900)
        b = row("b", 2050, source="craigslist", sqft=905)
        c = row("c", 2050, source="craigslist")  # no sqft -> not merged
        g = group_duplicates([a, b, c])
        self.assertEqual(g[a["id"]], g[b["id"]])
        self.assertNotEqual(g[a["id"]], g[c["id"]])


class ScoringTest(unittest.TestCase):
    def test_below_market_and_cross_site(self):
        ls = [row(str(i), p, lat=40.0 + i * 0.001) for i, p in enumerate([2000, 2100, 2200, 2050])]
        cheap = row("deal", 1600, lat=40.002, address="1 Deal St", zip="19000")
        dup = row("dup", 1750, source="zillow", lat=40.002, address="1 Deal Street", zip="19000",
                  url="https://example.com")
        out = {l["id"]: l for l in score_listings(ls + [cheap, dup], cfg(), today="2026-11-21")}
        d = out["rentcast:deal"]
        self.assertIn("below_market", d["flags"])
        self.assertIn("cheapest_site", d["flags"])
        self.assertAlmostEqual(d["pct_below_market"], 22.9, places=1)  # median 2075
        self.assertNotIn("cheapest_site", out["zillow:dup"]["flags"])
        self.assertEqual(out["zillow:dup"]["comp_count"], 4)  # dup's own group excluded

    def test_price_drop_and_stale(self):
        l = row("x", 1800, listed_date="2026-09-01",
                history=[{"date": "2026-09-01", "price": 2000}, {"date": "2026-11-01", "price": 1800}])
        out = score_listings([l], cfg(), today="2026-11-21")[0]
        self.assertIn("price_drop", out["flags"])
        self.assertEqual(out["pct_price_drop"], 10.0)
        self.assertIn("stale", out["flags"])
        self.assertEqual(out["days_on_market"], 81)

    def test_outside_radius_dropped(self):
        far = row("far", 1000, lat=41.0)
        self.assertEqual(score_listings([far], cfg(), today="2026-11-21"), [])

    def test_filters_with_unknowns(self):
        f = cfg(filters={"rent_max": 2500, "pets": ["dog"], "amenities_required": ["parking"]})["filters"]
        self.assertEqual(check_filters(row("a", 2000), f), (True, ["pets", "amenities"]))
        self.assertFalse(check_filters(row("a", 2000, pets=["cat"], amenities=["parking"]), f)[0])
        self.assertTrue(check_filters(row("a", 2000, pets=["cat", "dog"], amenities=["parking"]), f)[0])
        self.assertFalse(check_filters(row("a", 2600), f)[0])
        f["exclude_unknown"] = True
        self.assertFalse(check_filters(row("a", 2000), f)[0])


class SourceParsingTest(unittest.TestCase):
    def test_rentcast(self):
        l = parse_listing({
            "id": "123-Main-St,-Apt-4", "addressLine1": "123 Main St", "addressLine2": "Apt 4",
            "city": "Springfield", "state": "IL", "zipCode": "62701", "latitude": 39.8,
            "longitude": -89.6, "bedrooms": 2, "bathrooms": 1, "squareFootage": 900,
            "price": 1500, "listedDate": "2026-10-01T00:00:00.000Z",
            "history": {"2026-10-01": {"event": "Rental Listing", "price": 1650}},
        })
        self.assertEqual(l.id, "rentcast:123-Main-St,-Apt-4")
        self.assertEqual(l.listed_date, "2026-10-01")
        self.assertEqual(l.price_history, [("2026-10-01", 1650.0)])
        self.assertIsNone(l.pets)
        self.assertIsNone(parse_listing({"id": "x"}))

    def test_csv_row(self):
        l = parse_row({"Source": "Zillow", "address": "9 Pine Rd", "price": "$1,725",
                       "pets": "Cat; Dog", "amenities": "W/D; parking", "beds": "2"})
        self.assertEqual(l.source, "zillow")
        self.assertEqual(l.price, 1725)
        self.assertEqual(l.pets, ["cat", "dog"])
        self.assertEqual(l.amenities, ["in_unit_laundry", "parking"])
        self.assertIsNone(parse_row({"address": "9 Pine Rd", "price": ""}))
        self.assertEqual(parse_row({"address": "9 Pine Rd", "price": "1", "pets": "none"}).pets, [])


class DatabaseTest(unittest.TestCase):
    def test_snapshot_history_and_deactivation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(str(Path(tmp) / "t.db"))
            a = Listing(source="rentcast", source_id="a", price=2000)
            b = Listing(source="rentcast", source_id="b", price=1500)
            db.save_snapshot("rentcast", [a, b], today="2026-11-01")
            a2 = Listing(source="rentcast", source_id="a", price=1900)
            stats = db.save_snapshot("rentcast", [a2], today="2026-11-08")
            self.assertEqual(stats, {"new": 0, "updated": 1, "removed": 1})
            active = db.active_listings()
            self.assertEqual([l["id"] for l in active], ["rentcast:a"])
            self.assertEqual([h["price"] for h in active[0]["history"]], [2000, 1900])
            self.assertEqual(active[0]["first_seen"], "2026-11-01")
            # Partial fetch must not deactivate anything.
            db.save_snapshot("rentcast", [], complete=False, today="2026-11-09")
            self.assertEqual(len(db.active_listings()), 1)
            db.close()

    def test_csv_folder_keeps_latest_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.csv").write_text(
                "source,address,price,observed_date\n"
                "zillow,9 Pine Rd,1800,2026-11-01\n"
                "zillow,9 Pine Road,1700,2026-11-15\n", encoding="utf-8")
            src = CsvImportSource({"folder": tmp}, {}, None)
            out = src.fetch()
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].price, 1700)
            self.assertEqual(sorted(out[0].price_history),
                             [("2026-11-01", 1800.0), ("2026-11-15", 1700.0)])


if __name__ == "__main__":
    unittest.main()
