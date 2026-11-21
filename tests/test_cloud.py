import unittest

from homefinder.cloud import doc_id, push
from homefinder.sources.phone import PhoneSource, parse_submission


class FakeStore:
    """In-memory stand-in for cloud.FirestoreStore."""

    def __init__(self):
        self.listings = {}
        self.state = {}
        self.meta = None
        self.subs = []
        self.writes = 0

    def listing_status(self):
        return {k: {"active": v.get("active"), "inactive_since": v.get("inactive_since"),
                    "_hash": v.get("_hash")} for k, v in self.listings.items()}

    def write_listings(self, docs):
        self.writes += len(docs)
        self.listings.update(docs)

    def mark_inactive(self, ids, since):
        for k in ids:
            self.listings[k].update(active=False, inactive_since=since)

    def delete_listings(self, ids):
        for k in ids:
            del self.listings[k]

    def favorites(self):
        return {k for k, v in self.state.items() if v.get("favorite")}

    def set_meta(self, data):
        self.meta = data

    def submissions(self):
        return [dict(s) for s in self.subs]


def scored(id_, price, **kw):
    d = {"id": id_, "price": price, "flags": [], "score": 0.0, "history": [("2026-11-01", price)]}
    d.update(kw)
    return d


class PushTest(unittest.TestCase):
    def test_lifecycle(self):
        store = FakeStore()
        stats = push(store, [scored("rentcast:a/1", 2000), scored("rentcast:b", 1500)],
                     {"summary": []}, today="2026-11-01")
        self.assertEqual(stats["written"], 2)
        self.assertIn("rentcast:a_1", store.listings)  # '/' not allowed in doc ids
        self.assertEqual(store.listings["rentcast:a_1"]["history"], [["2026-11-01", 2000]])
        self.assertIn("updated_at", store.meta)

        # Unchanged data is not rewritten.
        stats = push(store, [scored("rentcast:a/1", 2000), scored("rentcast:b", 1500)],
                     {}, today="2026-11-02")
        self.assertEqual((stats["written"], stats["unchanged"]), (0, 2))

        # b disappears -> inactive, kept for a while.
        store.state["rentcast:b"] = {"favorite": True}
        stats = push(store, [scored("rentcast:a/1", 1900)], {}, today="2026-11-03")
        self.assertEqual((stats["written"], stats["deactivated"]), (1, 1))
        self.assertFalse(store.listings["rentcast:b"]["active"])

        # After prune_days: favorited b is kept; unfavorited c would be removed.
        push(store, [scored("rentcast:a/1", 1900), scored("x:c", 900)], {}, today="2026-11-04")
        push(store, [scored("rentcast:a/1", 1900)], {}, today="2026-11-05")
        stats = push(store, [scored("rentcast:a/1", 1900)], {}, prune_days=30, today="2026-12-20")
        self.assertEqual(stats["pruned"], 1)
        self.assertIn("rentcast:b", store.listings)
        self.assertNotIn("x:c", store.listings)

        # A listing that comes back is reactivated.
        push(store, [scored("rentcast:a/1", 1900), scored("rentcast:b", 1450)], {}, today="2026-12-21")
        self.assertTrue(store.listings["rentcast:b"]["active"])
        self.assertIsNone(store.listings["rentcast:b"]["inactive_since"])

    def test_doc_id(self):
        self.assertEqual(doc_id("a/b/c"), "a_b_c")


class PhoneSourceTest(unittest.TestCase):
    def test_parse(self):
        l = parse_submission({
            "_id": "abc", "source": "Zillow", "url": "javascript:alert(1)", "price": 1800,
            "address": "9 Pine Rd", "beds": 2, "pets": ["cat"], "amenities": None,
            "created_at": "2026-11-10T12:00:00Z", "updated_at": "2026-11-15T09:00:00Z",
            "history": [{"date": "2026-11-10", "price": 1900}],
        })
        self.assertEqual(l.id, "zillow:abc")
        self.assertIsNone(l.url)  # unsafe URL dropped
        self.assertEqual(l.observed_date, "2026-11-15")
        self.assertEqual(l.price_history, [("2026-11-10", 1900.0)])
        self.assertEqual(l.pets, ["cat"])
        self.assertIsNone(l.amenities)
        self.assertIsNone(parse_submission({"_id": "x", "price": 0, "address": "1 A St"}))
        self.assertIsNone(parse_submission({"_id": "x", "price": 100}))

    def test_source(self):
        store = FakeStore()
        store.subs = [{"_id": "1", "price": 1000, "address": "1 A St"},
                      {"_id": "2", "price": "bad", "address": "2 B St"}]
        out = PhoneSource({}, {}, None, store=store).fetch()
        self.assertEqual([l.id for l in out], ["phone:1"])


if __name__ == "__main__":
    unittest.main()
