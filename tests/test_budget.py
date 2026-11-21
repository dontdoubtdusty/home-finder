import unittest

from homefinder.budget import BudgetError, clean, compute, move_in_cost

BASE = {
    "earners": [
        {"name": "A", "gross": 36000, "gross_period": "year", "take_home": 2400},
        {"name": "B", "gross": 1000, "gross_period": "month", "take_home": 850},
    ],
    "bills": [{"name": "Car", "amount": 300}, {"name": "Phone", "amount": 100}],
    "utilities": 150, "savings": 3000, "deposit_months": 1,
    "pet_deposit": 300, "other_move_in": 100,
}


class BudgetTest(unittest.TestCase):
    def test_three_methods_and_lowest_wins(self):
        r = compute(clean(BASE))
        # gross = 3000 + 1000 = 4000/mo
        m = {x["key"]: x["amount"] for x in r["methods"]}
        self.assertEqual(m["rule30"], 1050)    # 1200 - 150 utilities
        self.assertEqual(m["rule40x"], 1200)   # 48000 / 40
        self.assertEqual(m["bills"], 2700)     # 3250 - 400 - 150
        self.assertEqual((r["budget"], r["limited_by"]), (1050, "rule30"))

    def test_bills_can_be_the_limit(self):
        b = dict(BASE, bills=[{"name": "Loans", "amount": 2500}])
        r = compute(clean(b))
        self.assertEqual((r["budget"], r["limited_by"]), (600, "bills"))  # 3250-2500-150

    def test_rounds_down_to_25(self):
        b = dict(BASE, earners=[{"gross": 2010, "gross_period": "month", "take_home": 0}], utilities=0)
        self.assertEqual(compute(clean(b))["budget"], 600)  # 30% = 603 -> 600

    def test_move_in(self):
        r = compute(clean(BASE))
        # (3000 - 400) / 2 = 1300 max rent; at 1050 rent: 2100 + 400
        self.assertEqual(r["move_in"]["max_rent_by_savings"], 1300)
        self.assertEqual(r["move_in"]["at_budget"], 2500)
        self.assertEqual(move_in_cost(650, clean(BASE)), 1700)

    def test_no_income_means_no_budget(self):
        r = compute(clean({"earners": [{"gross": 0, "take_home": 0}]}))
        self.assertIsNone(r["budget"])
        self.assertEqual(r["methods"], [])

    def test_take_home_only(self):
        r = compute(clean({"earners": [{"take_home": 2000}], "utilities": 100}))
        self.assertEqual(r["limited_by"], "bills")
        self.assertEqual(r["budget"], 1900)

    def test_validation(self):
        for bad in ({"earners": [{"gross": -5}]}, {"earners": [{"gross_period": "week"}]},
                    {"deposit_months": 9}, {"earners": "x"}, {"savings": "lots"}):
            with self.subTest(bad=bad), self.assertRaises(BudgetError):
                clean(dict(BASE, **bad))
        self.assertEqual(clean({"earners": [{}]})["earners"][0]["name"], "Person 1")


if __name__ == "__main__":
    unittest.main()
