"""Bebe's Home Search: desktop app.

Serves the dashboard on 127.0.0.1 and opens it in a chromeless Edge/Chrome app
window. The page's Refresh button runs collect + score (+ phone sync) here.

Security: the server only binds to localhost, checks the Host header, and every
request needs a random per-launch token, so other websites open in your browser
can't read your listings or trigger refreshes.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

APP_NAME = "Bebe's Home Search"
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BebesHomeSearch"
IDLE_EXIT_SECONDS = 45  # quit this long after the window closes / stops pinging

log = logging.getLogger("homefinder")


# --------------------------------------------------------------------- helpers

def message_box(text: str, error: bool = False) -> None:
    """Show a Windows message box (the exe has no console)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    except Exception:
        print(text, file=sys.stderr)


def project_root() -> Path:
    """Folder holding config.yaml: the exe's folder (or a parent), else the cwd."""
    if os.environ.get("HOMEFINDER_ROOT"):
        return Path(os.environ["HOMEFINDER_ROOT"]).resolve()
    start =Path(sys.executable if getattr(sys, "frozen", False) else os.getcwd()).resolve()
    if start.is_file():
        start = start.parent
    for d in [start, *start.parents]:
        if (d / "config.yaml").exists():
            return d
    return start


def bundled_dashboard() -> Path:
    """index.html shipped inside the exe (or the repo copy when run from source)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "dashboard" / "index.html"


def find_browser() -> Optional[str]:
    candidates = [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        p = Path(os.path.expandvars(c))
        if p.exists():
            return str(p)
    return None


class LogCapture(logging.Handler):
    def __init__(self, sink: List[str]):
        super().__init__(logging.INFO)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if record.levelno >= logging.WARNING:
            msg = f"{record.levelname.title()}: {msg}"
        self.sink.append(msg)


# --------------------------------------------------------------------- app

class DesktopApp:
    def __init__(self, root: Path):
        self.root = root
        self.config_path = root / "config.yaml"
        self.token = secrets.token_urlsafe(24)
        self.port = 0
        self.last_ping = time.time()
        self.lock = threading.Lock()
        self.job: Dict[str, Any] = {"running": False, "kind": None, "ok": None,
                                    "started": None, "finished": None, "log": []}

    # ---- jobs (refresh = call RentCast etc.; rescore = recompute only)
    def start_job(self, kind: str) -> bool:
        with self.lock:
            if self.job["running"]:
                return False
            self.job = {"running": True, "kind": kind, "ok": None,
                        "started": datetime.now().isoformat(timespec="seconds"),
                        "finished": None, "log": []}
        threading.Thread(target=self._run_job, args=(kind,), daemon=True).start()
        return True

    def _run_job(self, kind: str) -> None:
        from .__main__ import _open_store, collect, report, sync
        from .config import load_config
        from .db import Database

        handler = LogCapture(self.job["log"])
        log.addHandler(handler)
        log.setLevel(logging.INFO)  # INFO progress lines are what the window shows
        ok = True
        try:
            cfg = load_config(self.config_path)
            db = Database(cfg["database"])
            try:
                store = None
                if cfg["firebase"].get("enabled"):
                    try:
                        store = _open_store(cfg, required=False)
                    except Exception as exc:
                        log.warning("Phone app sync skipped: %s", exc)
                if kind == "refresh":
                    log.info("Looking for new listings…")
                    ok = collect(cfg, db, store)
                scored = report(cfg, db)
                if store is not None:
                    try:
                        sync(cfg, db, store, scored)
                    except Exception as exc:
                        log.warning("Phone app sync failed: %s", exc)
                        ok = False
                log.info("All done!")
            finally:
                db.close()
        except Exception as exc:  # show anything unexpected in the window
            log.error("%s", exc)
            ok = False
        finally:
            log.removeHandler(handler)
            with self.lock:
                self.job.update(running=False, ok=ok,
                                finished=datetime.now().isoformat(timespec="seconds"))

    def status(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"job": dict(self.job, log=list(self.job["log"][-30:])),
                               "app": APP_NAME}
        try:
            from .config import load_config
            from .db import Database
            cfg = load_config(self.config_path)
            db = Database(cfg["database"])
            try:
                month = datetime.now().strftime("%Y-%m")
                out["rentcast"] = {
                    "used": db.api_calls("rentcast", month),
                    "budget": cfg["sources"]["rentcast"].get("monthly_request_budget"),
                    "enabled": cfg["sources"]["rentcast"].get("enabled", True),
                }
            finally:
                db.close()
            out["firebase"] = bool(cfg["firebase"].get("enabled"))
        except Exception as exc:
            out["config_error"] = str(exc)
        return out

    def get_settings(self) -> Dict[str, Any]:
        from .config import load_config
        from .settings import current
        return current(load_config(self.config_path))

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate + save, then re-rank. Raises SettingsError on bad input."""
        from .config import load_config
        from .settings import save_overrides, validate
        if self.job["running"]:
            return {"saved": False, "busy": True}
        cfg = load_config(self.config_path)
        before = cfg["search"]
        overrides = validate(payload)
        after = overrides["search"]
        save_overrides(Path(cfg["settings_file"]), overrides)
        area_changed = (after["radius_miles"] > before["radius_miles"]
                        or abs(after["latitude"] - before["latitude"]) > 1e-4
                        or abs(after["longitude"] - before["longitude"]) > 1e-4)
        started = self.start_job("rescore")
        return {"saved": True, "area_changed": area_changed, "rescore_started": started}

    def data_file(self) -> Path:
        try:
            from .config import load_config
            return Path(load_config(self.config_path)["dashboard_data"])
        except Exception:
            return self.root / "dashboard" / "data.js"

    def index_file(self) -> Path:
        local = self.root / "dashboard" / "index.html"
        return local if local.exists() else bundled_dashboard()

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"


def make_handler(app: DesktopApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BebesHomeSearch"

        def log_message(self, fmt, *args):  # keep quiet
            pass

        def _authorized(self) -> bool:
            host = self.headers.get("Host", "")
            if host not in (f"127.0.0.1:{app.port}", f"localhost:{app.port}"):
                return False
            q = parse_qs(urlparse(self.path).query)
            token = self.headers.get("X-Token") or (q.get("t") or [""])[0]
            return secrets.compare_digest(token, app.token)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            if not self._authorized():
                return self._send(403, b"Forbidden", "text/plain")
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, app.index_file().read_bytes(), "text/html; charset=utf-8")
            if path == "/data.js":
                f = app.data_file()
                body = f.read_bytes() if f.exists() else b"window.HOMEFINDER = null;"
                return self._send(200, body, "text/javascript; charset=utf-8")
            if path == "/api/status":
                return self._json(app.status())
            if path == "/api/settings":
                try:
                    return self._json(app.get_settings())
                except Exception as exc:
                    return self._json({"error": str(exc)}, 500)
            return self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            if not self._authorized():
                return self._send(403, b"Forbidden", "text/plain")
            path = urlparse(self.path).path
            if path == "/api/ping":
                app.last_ping = time.time()
                return self._json({"ok": True})
            if path in ("/api/refresh", "/api/rescore"):
                started = app.start_job(path.rsplit("/", 1)[1])
                return self._json({"started": started}, 202 if started else 409)
            if path == "/api/settings":
                from .settings import SettingsError
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > 20000:
                    return self._json({"error": "Bad request"}, 400)
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    result = app.save_settings(payload)
                except (SettingsError, ValueError) as exc:
                    return self._json({"error": str(exc)}, 400)
                return self._json(result, 200 if result.get("saved") else 409)
            return self._send(404, b"Not found", "text/plain")

    return Handler


# --------------------------------------------------------------------- instance

def existing_instance() -> Optional[str]:
    """URL of an already-running instance, if any."""
    f = STATE_DIR / "instance.json"
    try:
        info = json.loads(f.read_text())
        req = urllib.request.Request(
            f"http://127.0.0.1:{info['port']}/api/ping", data=b"", method="POST",
            headers={"X-Token": info["token"]})
        with urllib.request.urlopen(req, timeout=1.5) as r:
            if r.status == 200:
                return f"http://127.0.0.1:{info['port']}/?t={info['token']}"
    except Exception:
        pass
    return None


def open_window(url: str) -> Optional[subprocess.Popen]:
    browser = find_browser()
    if not browser:
        import webbrowser
        webbrowser.open(url)
        return None
    profile = STATE_DIR / "browser"
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([
        browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1320,880",
        "--no-first-run", "--no-default-browser-check", "--disable-features=Translate",
    ])


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(STATE_DIR / "app.log"), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")

    url = existing_instance()
    if url:
        open_window(url)
        return 0

    root = project_root()
    if not (root / "config.yaml").exists():
        message_box(
            f"I couldn't find config.yaml.\n\nPut {APP_NAME}.exe in the home-finder folder "
            "(next to config.yaml). See README.md for setting up config.yaml.", error=True)
        return 2

    app = DesktopApp(root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    app.port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (STATE_DIR / "instance.json").write_text(json.dumps({"port": app.port, "token": app.token}))

    # HOMEFINDER_HEADLESS=1: serve only (for automated testing); quits after the idle timeout.
    proc = None if os.environ.get("HOMEFINDER_HEADLESS") else open_window(app.url())
    app.last_ping = time.time()
    try:
        while True:
            time.sleep(2)
            window_open = proc is not None and proc.poll() is None
            recently_pinged = time.time() - app.last_ping < IDLE_EXIT_SECONDS
            if not window_open and not recently_pinged and not app.job["running"]:
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        try:
            (STATE_DIR / "instance.json").unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
