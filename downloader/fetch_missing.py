#!/usr/bin/env python3
"""Download the active user database from each MaxTime controller that still
needs one, using the needs_download.csv exported by the triage dashboard.

Python 3 stdlib only, so it runs on a locked down Windows machine with any
plain Python install. Strictly read only against controllers: one sign in
POST plus GET requests, nothing that changes state.

Usage:
    python3 fetch_missing.py needs_download.csv --out downloaded

Credentials are prompted at runtime, held in memory only, never stored,
never logged. Files are written as CCC_IDID_<name>.db (or the filename the
controller supplies) into the output folder; moving them into SharePoint
stays a manual, visible step.

STATUS: the sign in and download endpoints are not implemented yet.
They require one HAR capture from the work computer: see CAPTURE.md in
this folder. Everything around them (CSV input, throttling, resume,
timeouts, the summary table) is finished and tested.
"""

import argparse
import csv
import getpass
import http.cookiejar
import sys
import time
import urllib.request
from pathlib import Path


class MaxTimeClient:
    """HTTP client for one controller's MaxTime web UI.

    The three methods below are filled in from a HAR capture of one real
    sign in and download (see CAPTURE.md). Until then they raise.
    """

    def __init__(self, base_url, timeout=20):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))

    def login(self, username, password):
        """POST the Controller sign in form. Fill in from the HAR."""
        raise NotImplementedError(
            "Sign in endpoint unknown. Capture a HAR per CAPTURE.md and "
            "have Claude fill in MaxTimeClient.")

    def active_database(self):
        """Return (identifier, display name) of the user database marked
        Active on the Database Management page. Fill in from the HAR."""
        raise NotImplementedError

    def download(self, identifier, dest_path):
        """GET the database export and write it to dest_path.
        Fill in from the HAR."""
        raise NotImplementedError


def slug(text):
    keep = []
    for ch in text.strip():
        keep.append(ch if ch.isalnum() or ch in "@_" else "_")
    return "".join(keep)


def already_downloaded(out_dir, signal_id):
    return sorted(out_dir.glob("???_%s_*" % signal_id))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv_path", help="needs_download.csv from the dashboard")
    ap.add_argument("--out", default="downloaded", help="output folder")
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds to wait between controllers (default 3)")
    ap.add_argument("--timeout", type=float, default=20.0,
                    help="per request timeout in seconds")
    ap.add_argument("--only", help="comma separated signal IDs to limit the run,"
                    " e.g. --only 4070 for a supervised first test")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv_path, newline="", encoding="utf-8-sig")))
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        rows = [r for r in rows if r["id"] in wanted]
    if not rows:
        print("Nothing to do: the CSV has no matching rows.")
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    username = input("MaxTime username: ")
    password = getpass.getpass("MaxTime password (not echoed, not stored): ")

    ok, failed, skipped = [], [], []
    for i, r in enumerate(rows):
        sid, url = r["id"], r["url"]
        label = "%s %s @ %s (%s)" % (sid, r.get("main", ""), r.get("side", ""), url)
        if already_downloaded(out_dir, sid):
            print("skip %s: already in %s" % (sid, out_dir))
            skipped.append(sid)
            continue
        if i and args.delay:
            time.sleep(args.delay)
        print("[%d/%d] %s" % (i + 1, len(rows), label))
        try:
            client = MaxTimeClient(url, timeout=args.timeout)
            client.login(username, password)
            ident, name = client.active_database()
            dest = out_dir / ("%s.db" % slug(name))
            client.download(ident, dest)
            print("  saved %s" % dest.name)
            ok.append(sid)
        except NotImplementedError as e:
            print("\nNot ready yet: %s" % e)
            return 2
        except Exception as e:
            print("  FAILED: %s" % e)
            failed.append((sid, str(e)))

    print("\nSummary: %d downloaded, %d failed, %d skipped"
          % (len(ok), len(failed), len(skipped)))
    for sid, why in failed:
        print("  failed %s: %s" % (sid, why))
    if failed:
        print("Rerun the same command to retry: finished signals are skipped.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
