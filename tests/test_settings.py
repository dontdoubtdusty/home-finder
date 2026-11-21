import copy
import json
import tempfile
import unittest
from pathlib import Path

from homefinder.config import DEFAULTS, load_config
from homefinder.scoring import check_filters
from homefinder.settings import SettingsError, current, validate

GOOD = {
    "latitude": 37.13, "longitude": -80.41, "radius_miles": 10,
    "rent_min": 0, "rent_max": 650, "beds": [0, 1], "baths_min": 1,
    "pets": ["cat", "dog"], "amenities_required": ["parking", "ac"],
    "amenities_preferred": ["dishwasher", "parking"], "exclude_unknown": False,
    "deal_preset": "balanced",
}


class ValidateTest(unittest.TestCase):
    def test_good_payload(self):
        o = validate(GOOD)
        self.assertEqual(o["filters"]["beds"], [0, 1])
        self.assertEqual(o["filters"]["rent_max"], 650)
        # A must-have can't also be a nice-to-have.
        self.assertEqual(o["filters"]["amenities_preferred"], ["dishwasher"])
        self.assertEqual(o["scoring"]["below_market_pct"], 10)
        self.assertNotIn("sources", o)  # never touches API keys

    def test_rejects_bad_values(self):
        for change in ({"beds": [7]}, {"pets": ["parrot"]}, {"rent_min": 900},
                       {"radius_miles": 500}, {"latitude": "x"}, {"deal_preset": "wild"},
                       {"amenities_required": "parking"}):
            with self.subTest(change=change), self.assertRaises(SettingsError):
                validate(dict(GOOD, **change))

    def test_no_max_rent(self):
        self.assertIsNone(validate(dict(GOOD, rent_max=None))["filters"]["rent_max"])


class BedFilterTest(unittest.TestCase):
    def f(self, beds):
        f = copy.deepcopy(DEFAULTS["filters"])
        f["beds"] = beds
        return f

    def test_exact_choices(self):
        f = self.f([0, 2])
        self.assertTrue(check_filters({"price": 600, "beds": 0}, f)[0])
        self.assertFalse(check_filters({"price": 600, "beds": 1}, f)[0])
        self.assertTrue(check_filters({"price": 600, "beds": 2}, f)[0])
        self.assertEqual(check_filters({"price": 600, "beds": None}, f), (True, ["beds"]))

    def test_four_plus(self):
        f = self.f([4])
        self.assertTrue(check_filters({"price": 600, "beds": 5}, f)[0])
        self.assertFalse(check_filters({"price": 600, "beds": 3}, f)[0])

    def test_empty_means_any(self):
        self.assertTrue(check_filters({"price": 600, "beds": 6}, self.f([]))[0])


class OverlayTest(unittest.TestCase):
    def test_settings_file_overrides_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                "search: {latitude: 1.0, longitude: 2.0, radius_miles: 5}\n"
                "filters: {rent_max: 900, pets: [cat]}\n"
                "sources: {rentcast: {api_key: SECRET}}\n", encoding="utf-8")
            (root / "data").mkdir()
            (root / "data" / "settings.json").write_text(json.dumps(validate(GOOD)), encoding="utf-8")
            cfg = load_config(root / "config.yaml")
            self.assertEqual(cfg["filters"]["rent_max"], 650)
            self.assertEqual(cfg["filters"]["beds"], [0, 1])
            self.assertEqual(cfg["search"]["radius_miles"], 10)
            self.assertEqual(cfg["sources"]["rentcast"]["api_key"], "SECRET")  # untouched
            shown = current(cfg)
            self.assertNotIn("SECRET", json.dumps(shown))
            self.assertEqual(shown["deal_preset"], "balanced")


if __name__ == "__main__":
    unittest.main()
