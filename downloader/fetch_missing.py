#!/usr/bin/env python3
"""Download the active user database from each MaxTime controller that still
needs one, using the needs_download.csv exported by the triage dashboard.

Python 3 stdlib only, so it runs on a locked down Windows machine with any
plain Python install.

How MaxTime actually works (established from a real capture):
  * The controller's own API at http://IP:52270/maxtime/api/* is reachable
    directly on the local network and needs no login. The web UI signs in
    to a separate profile server, but the controller endpoints below carry
    no cookie or token.
  * The active user database name is read from
        GET  /maxtime/api/mibs/UsrDBName
  * The database file is streamed back by
        POST /maxtime/api/db/download   body {"name": <name>, "type": "user"}

Both calls only read; nothing here changes controller state.

Usage:
    python3 fetch_missing.py needs_download.csv --out downloaded
    python3 fetch_missing.py needs_download.csv --only 4070   # supervised first run

Each saved file is named after the controller's own active database name, so
it matches the SharePoint naming. Moving files into SharePoint stays a
manual, visible step.
"""

import argparse
import csv
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The controller reports its active database as e.g. 012_7004_SR90@SCHOOL_DR.
DBNAME_RE = re.compile(rb"\d{3}_\d{4}_[ -~]{1,80}")
# Saved file extension. The controller name carries none; set this if the real
# download turns out to have one (confirm on the first supervised run).
SAVE_EXT = ""


class MaxTimeError(Exception):
    pass


class MaxTimeClient:
    """Read only client for one controller's MaxTime API. No auth needed."""

    def __init__(self, base_url, timeout=25):
        # base_url is like http://<controller-ip>:52270/maxtime/
        self.base = base_url.rstrip("/")
        if self.base.endswith("/maxtime"):
            self.origin = self.base[: -len("/maxtime")]
        else:
            self.origin = self.base
        self.api = self.origin + "/maxtime/api"
        self.timeout = timeout

    def _headers(self, content_type=None):
        h = {
            "Accept": "*/*",
            "Origin": self.origin,
            "Referer": self.origin + "/maxtime/Administration/DatabaseManagement",
            "User-Agent": "maxtime-triage-downloader",
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _open(self, req):
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise MaxTimeError(
                    "controller refused the request (HTTP %d): this controller "
                    "may require auth, unlike the captured one" % e.code)
            raise MaxTimeError("HTTP %d from %s" % (e.code, req.full_url))
        except urllib.error.URLError as e:
            raise MaxTimeError("cannot reach controller: %s" % e.reason)

    def active_database_name(self):
        """Return the active user database name, read from the UsrDBName MIB."""
        req = urllib.request.Request(self.api + "/mibs/UsrDBName",
                                     headers=self._headers())
        blob = self._open(req).read()
        matches = DBNAME_RE.findall(blob)
        if not matches:
            raise MaxTimeError("could not find a database name in UsrDBName "
                               "(got %d bytes)" % len(blob))
        # Trim trailing non name bytes the greedy match may have grabbed.
        name = matches[0].decode("ascii", "replace").rstrip()
        name = re.split(r"[\x00-\x1f]", name)[0].rstrip()
        return name

    def download(self, name, dest_path):
        """Stream the named user database to dest_path."""
        body = ('{"name":%s,"type":"user"}' % _json_str(name)).encode("utf-8")
        req = urllib.request.Request(
            self.api + "/db/download", data=body,
            headers=self._headers("text/plain;charset=UTF-8"), method="POST")
        resp = self._open(req)
        tmp = dest_path.with_suffix(dest_path.suffix + ".part")
        total = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
        if total == 0:
            tmp.unlink(missing_ok=True)
            raise MaxTimeError("download returned an empty file")
        tmp.replace(dest_path)
        return total


def _json_str(s):
    """Minimal JSON string encoder (stdlib json would also do, kept explicit)."""
    out = ['"']
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def already_downloaded(out_dir, signal_id):
    return sorted(out_dir.glob("???_%s_*" % signal_id))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv_path", help="needs_download.csv from the dashboard")
    ap.add_argument("--out", default="downloaded", help="output folder")
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds to wait between controllers (default 3)")
    ap.add_argument("--timeout", type=float, default=25.0,
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

    ok, failed, skipped = [], [], []
    for i, r in enumerate(rows):
        sid, url = r["id"], r["url"]
        label = "%s  %s @ %s  (%s)" % (sid, r.get("main", ""), r.get("side", ""), url)
        if already_downloaded(out_dir, sid):
            print("skip %s: already in %s" % (sid, out_dir))
            skipped.append(sid)
            continue
        if i and args.delay:
            time.sleep(args.delay)
        print("[%d/%d] %s" % (i + 1, len(rows), label))
        try:
            client = MaxTimeClient(url, timeout=args.timeout)
            name = client.active_database_name()
            print("   active database: %s" % name)
            m = re.match(r"(\d{3})_(\d{4})_", name)
            if m and m.group(2) != sid:
                print("   WARNING: controller reports id %s but CSV row is %s;"
                      " skipping to avoid saving the wrong signal" % (m.group(2), sid))
                failed.append((sid, "id mismatch: controller had %s" % m.group(2)))
                continue
            dest = out_dir / (name + SAVE_EXT)
            size = client.download(name, dest)
            print("   saved %s (%d bytes)" % (dest.name, size))
            ok.append(sid)
        except MaxTimeError as e:
            print("   FAILED: %s" % e)
            failed.append((sid, str(e)))

    print("\nSummary: %d downloaded, %d failed, %d skipped"
          % (len(ok), len(failed), len(skipped)))
    for sid, why in failed:
        print("   failed %s: %s" % (sid, why))
    if failed:
        print("Rerun the same command to retry; finished signals are skipped.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
