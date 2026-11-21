"""Command line entry point.

    py -m homefinder run          collect, score, write dashboard, sync to phone app
    py -m homefinder collect      collect only
    py -m homefinder report       score + write dashboard from stored data (no API calls)
    py -m homefinder sync         score + push to the phone app (no API calls)
    py -m homefinder top          print the best deals in the terminal
    py -m homefinder usage        show API requests used this month
    py -m homefinder allow EMAIL  let a Google account sign in to the phone app
    py -m homefinder disallow EMAIL
    py -m homefinder allowed      list who can sign in
"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import ConfigError, load_config
from .db import Database
from .export import build_meta, write_dashboard_data
from .scoring import score_listings
from .sources import SourceError, build_sources

log = logging.getLogger("homefinder")

COMMANDS = ["run", "collect", "report", "sync", "top", "usage", "allow", "disallow", "allowed"]
NEEDS_CLOUD = {"sync", "allow", "disallow", "allowed"}


def collect(cfg: Dict[str, Any], db: Database, store=None) -> bool:
    ok = True
    for source in build_sources(cfg, db, store=store):
        try:
            listings = source.fetch()
        # requests errors subclass OSError; ValueError covers bad JSON / CSV values.
        except (SourceError, OSError, ValueError) as exc:
            log.error("%s: %s", source.name, exc)
            ok = False
            continue
        if listings is None:
            continue
        stats = db.save_snapshot(source.name, listings, complete=source.complete)
        log.info("%s: %d new, %d updated, %d no longer listed",
                 source.name, stats["new"], stats["updated"], stats["removed"])
    return ok


def usage_info(cfg: Dict[str, Any], db: Database) -> Dict[str, Any]:
    month = date.today().strftime("%Y-%m")
    rc = cfg["sources"]["rentcast"]
    return {"month": month, "rentcast_used": db.api_calls("rentcast", month),
            "rentcast_budget": rc.get("monthly_request_budget")}


def report(cfg: Dict[str, Any], db: Database) -> List[Dict[str, Any]]:
    scored = score_listings(db.active_listings(), cfg)
    path = write_dashboard_data(scored, cfg, usage_info(cfg, db))
    shown = sum(1 for l in scored if l["passes_filters"])
    log.info("Scored %d listings in area (%d match filters). Dashboard data: %s",
             len(scored), shown, path)
    return scored


def sync(cfg: Dict[str, Any], db: Database, store, scored: List[Dict[str, Any]]) -> None:
    from .cloud import push
    meta = build_meta(scored, cfg, usage_info(cfg, db))
    stats = push(store, scored, meta, prune_days=int(cfg["firebase"]["prune_days"]))
    log.info("Phone app: %d updated, %d unchanged, %d no longer listed, %d removed",
             stats["written"], stats["unchanged"], stats["deactivated"], stats["pruned"])


def print_top(scored: List[Dict[str, Any]], n: int) -> None:
    rows = [l for l in scored if l["passes_filters"]][:n]
    if not rows:
        print("No listings match your filters yet.")
        return
    fmt = lambda v: "?" if v is None else f"{v:g}"
    print(f"{'score':>6}  {'price':>7}  {'bd/ba':>6}  {'mi':>5}  {'flags':<36} address")
    for l in rows:
        bb = f"{fmt(l.get('beds'))}/{fmt(l.get('baths'))}"
        dist = "" if l.get("distance_miles") is None else f"{l['distance_miles']:.1f}"
        addr = ", ".join(x for x in (l.get("address"), l.get("unit")) if x)
        print(f"{l['score']:>6.1f}  {l['price']:>7,.0f}  {bb:>6}  {dist:>5}  "
              f"{','.join(l['flags']):<36} {addr} [{l['source']}]")


def _open_store(cfg: Dict[str, Any], required: bool):
    if not cfg["firebase"].get("enabled"):
        if required:
            raise ConfigError("Set firebase.enabled: true in config.yaml (see SETUP.md).")
        return None
    from .cloud import open_store
    return open_store(cfg)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="homefinder", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("email", nargs="?", help="for allow / disallow")
    parser.add_argument("--config", default="config.yaml", type=Path)
    parser.add_argument("-n", type=int, default=15, help="rows for 'top'")
    parser.add_argument("--open", action="store_true", help="open the dashboard after")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    if args.command in ("allow", "disallow") and not args.email:
        parser.error(f"{args.command} needs an email address")

    try:
        cfg = load_config(args.config)
        store = None
        if args.command in NEEDS_CLOUD or args.command == "run":
            store = _open_store(cfg, required=args.command in NEEDS_CLOUD)
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 2

    if args.command == "allow":
        store.allow(args.email)
        print(f"{args.email.lower()} can now sign in to the phone app.")
        return 0
    if args.command == "disallow":
        store.disallow(args.email)
        print(f"{args.email.lower()} removed.")
        return 0
    if args.command == "allowed":
        print("\n".join(store.allowed()) or "Nobody yet. Add someone with: allow EMAIL")
        return 0

    db = Database(cfg["database"])
    try:
        ok = True
        if args.command in ("run", "collect"):
            ok = collect(cfg, db, store)
        if args.command in ("run", "report", "sync", "top"):
            scored = report(cfg, db)
            if args.command != "sync":
                print_top(scored, args.n)
            if store is not None and args.command in ("run", "sync"):
                try:
                    sync(cfg, db, store, scored)
                except Exception as exc:  # network / permission errors from Google libs
                    log.error("Phone app sync failed: %s", exc)
                    ok = False
        if args.command == "usage":
            u = usage_info(cfg, db)
            print(f"RentCast {u['month']}: {u['rentcast_used']}/{u['rentcast_budget']} requests")
        if args.open:
            index = Path(cfg["dashboard_data"]).parent / "index.html"
            webbrowser.open(index.resolve().as_uri())
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
