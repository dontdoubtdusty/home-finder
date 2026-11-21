import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from homefinder.desktop import DesktopApp, make_handler

CONFIG = """
search: {latitude: 40.0, longitude: -75.0, radius_miles: 3}
sources:
  rentcast: {enabled: false}
  csv_import: {enabled: true, folder: imports}
"""


class DesktopServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "config.yaml").write_text(CONFIG, encoding="utf-8")
        (root / "imports").mkdir()
        (root / "imports" / "a.csv").write_text(
            "source,address,price,beds,latitude,longitude\nzillow,1 A St,1500,1,40.0,-75.0\n",
            encoding="utf-8")
        self.app = DesktopApp(root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.app.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.app.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def req(self, path, method="GET", token=None, host=None):
        headers = {}
        if token:
            headers["X-Token"] = token
        if host:
            headers["Host"] = host
        r = urllib.request.Request(self.base + path, method=method, headers=headers,
                                   data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_requires_token_and_local_host(self):
        self.assertEqual(self.req("/data.js")[0], 403)
        self.assertEqual(self.req("/data.js", token="wrong")[0], 403)
        self.assertEqual(self.req("/api/refresh", "POST")[0], 403)
        self.assertEqual(self.req("/data.js", token=self.app.token, host="evil.example")[0], 403)
        self.assertEqual(self.req(f"/?t={self.app.token}")[0], 200)

    def test_refresh_job_writes_dashboard_data(self):
        t = self.app.token
        self.assertEqual(self.req("/api/refresh", "POST", token=t)[0], 202)
        for _ in range(50):
            status = json.loads(self.req("/api/status", token=t)[1])
            if not status["job"]["running"]:
                break
            time.sleep(0.1)
        self.assertTrue(status["job"]["ok"], status["job"]["log"])
        self.assertEqual(status["rentcast"]["enabled"], False)
        code, body = self.req("/data.js", token=t)
        self.assertEqual(code, 200)
        self.assertIn(b"1 A St", body)


class DesktopSettingsTest(DesktopServerTest):
    def post_json(self, path, obj, token):
        body = json.dumps(obj).encode()
        r = urllib.request.Request(self.base + path, data=body, method="POST",
                                   headers={"X-Token": token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_settings_roundtrip(self):
        t = self.app.token
        code, body = self.req("/api/settings", token=t)
        self.assertEqual(code, 200)
        s = json.loads(body)
        s.update(beds=[0, 1], rent_max=650, radius_miles=12)
        s.pop("options")
        code, res = self.post_json("/api/settings", s, t)
        self.assertEqual(code, 200, res)
        self.assertTrue(res["saved"])
        self.assertTrue(res["area_changed"])  # radius grew 3 -> 12
        for _ in range(50):
            if not self.app.job["running"]:
                break
            time.sleep(0.1)
        again = json.loads(self.req("/api/settings", token=t)[1])
        self.assertEqual((again["beds"], again["rent_max"], again["radius_miles"]), ([0, 1], 650, 12))

    def test_settings_rejects_bad_input_and_no_token(self):
        self.assertEqual(self.post_json("/api/settings", {"beds": [9]}, self.app.token)[0], 400)
        self.assertEqual(self.req("/api/settings", "POST")[0], 403)


if __name__ == "__main__":
    unittest.main()
