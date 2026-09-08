#!/usr/bin/env python3
"""Ask one MaxTime controller whether its cabinet IO module configuration can
be read over HTTP, the way fetch_missing.py already reads the active database
name. Run this on the work computer against a single controller before anyone
decides to automate the box check.

The manual check this is standing in for:

    Controller > Advanced IO > Cabinet Configuration > IO Modules
    A TS2 DR1 BIU sitting in IO module 2 means the signal has a clickbox,
    so there is a clickbox configuration file to fetch at http://IP:57150.

If that answer can be read from the controller API, 220 controller visits
collapse into one script run. If it cannot, nothing is lost and the check
stays manual.

Python 3 stdlib only, so it runs on a locked down Windows machine.

Read only by construction: this script issues GET requests and nothing else.
It sends no credentials, writes no files, and changes no controller state.

Usage:
    python3 probe_iomodules.py 10.20.30.40
    python3 probe_iomodules.py 10.20.30.40 --port 52270
    python3 probe_iomodules.py 10.20.30.40 --mib CabinetIOModules
    python3 probe_iomodules.py 10.20.30.40 --all-mibs
    python3 probe_iomodules.py 10.20.30.40 --raw

What it does, in order:

  1. Reads /maxtime/api/mibs/UsrDBName, the endpoint the downloader already
     uses, to prove this controller answers the open API at all.
  2. Downloads the MaxTime web UI and its JavaScript bundles and pulls every
     `api/mibs/<Name>` string out of them, so the real MIB name is discovered
     rather than guessed. Names mentioning cabinet, IO, module, BIU, rack or
     TS2 are tried first.
  3. GETs each candidate and reports the status, the size, and whether the
     bytes carry the ASCII markers BIU, TS2 or DR1.

Print the output and send it over. The line that matters is the one naming a
MIB whose body contains BIU.
"""

import argparse
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# The API port established from a real capture. The links sheet's own port
# column is the web UI port and is not always this one, so it is a flag.
DEFAULT_API_PORT = 52270

# Every `api/mibs/<Name>` reference the UI bundles carry.
MIB_REF_RE = re.compile(r"(?:api/)?mibs/([A-Za-z][A-Za-z0-9_]{2,60})")
# Script and stylesheet sources in the UI's index page.
SRC_RE = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+\.js[^"']*)["']""", re.I)
# Candidate MIB names worth trying first.
INTERESTING_RE = re.compile(r"cabinet|iomod|io_mod|module|biu|rack|ts2|detector",
                            re.I)
# Markers that would prove a response describes the cabinet IO modules.
MARKERS = (b"BIU", b"TS2", b"DR1", b"TS1", b"SIU")
# Guesses used only when the bundles yield nothing, so the run still says
# something useful on a controller that serves the UI from somewhere else.
FALLBACK_MIBS = (
    "CabinetConfig", "CabinetIOModules", "IOModules", "IOModuleConfig",
    "IOModuleType", "AdvancedIO", "CabinetType", "ModuleConfig",
)

PRINTABLE_RE = re.compile(rb"[ -~]{4,}")


def get(url, timeout, origin):
    """One read only GET. Returns (status, body) or (None, error text)."""
    req = urllib.request.Request(url, method="GET", headers={
        "Accept": "*/*",
        "Origin": origin,
        "Referer": origin + "/maxtime/",
        "User-Agent": "maxtime-triage-probe",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:2000]
    except urllib.error.URLError as e:
        return None, str(e.reason).encode()
    except Exception as e:  # socket timeouts, resets, anything else
        return None, str(e).encode()


def strings(body, limit=40):
    """The printable runs inside a MIB blob, which is mostly binary."""
    return [m.decode("ascii", "replace")
            for m in PRINTABLE_RE.findall(body)][:limit]


def discover_mibs(origin, timeout, verbose):
    """Every MIB name the UI's own JavaScript mentions."""
    found = set()
    status, body = get(origin + "/maxtime/", timeout, origin)
    if status != 200:
        print("  the UI index did not load (%s), skipping discovery"
              % (status if status else body.decode("utf-8", "replace")))
        return found
    text = body.decode("utf-8", "replace")
    found.update(MIB_REF_RE.findall(text))
    srcs = SRC_RE.findall(text)
    if verbose:
        print("  the index page references %d script(s)" % len(srcs))
    for src in srcs[:20]:
        url = urllib.parse.urljoin(origin + "/maxtime/", src)
        st, b = get(url, timeout, origin)
        if st != 200:
            continue
        names = set(MIB_REF_RE.findall(b.decode("utf-8", "replace")))
        if verbose:
            print("  %-60s %4d MIB names" % (src[-60:], len(names)))
        found.update(names)
    return found


def probe(origin, mib, timeout, raw):
    """GET one MIB and say whether it looks like the cabinet IO modules."""
    url = "%s/maxtime/api/mibs/%s" % (origin, mib)
    status, body = get(url, timeout, origin)
    if status is None:
        print("  %-34s could not connect: %s"
              % (mib, body.decode("utf-8", "replace")))
        return False
    if status != 200:
        print("  %-34s HTTP %s" % (mib, status))
        return False
    hits = [m.decode() for m in MARKERS if m in body]
    print("  %-34s HTTP 200, %6d bytes%s"
          % (mib, len(body), ("   <-- carries " + ", ".join(hits)) if hits else ""))
    if raw or hits:
        for s in strings(body):
            print("       %s" % s)
    return bool(hits)


def main():
    ap = argparse.ArgumentParser(
        description="Test whether one controller will report its cabinet IO "
                    "modules over the open MaxTime API. Read only.")
    ap.add_argument("host", help="controller IP or hostname")
    ap.add_argument("--port", type=int, default=DEFAULT_API_PORT,
                    help="API port (default %d)" % DEFAULT_API_PORT)
    ap.add_argument("--mib", action="append", default=[],
                    help="test this MIB name directly; repeatable")
    ap.add_argument("--all-mibs", action="store_true",
                    help="probe every MIB name found, not only the likely ones")
    ap.add_argument("--raw", action="store_true",
                    help="print the printable strings of every response")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    host = args.host.strip()
    if "://" in host:
        host = urllib.parse.urlparse(host).hostname or host
    origin = "http://%s:%d" % (host, args.port)
    print("Controller %s" % origin)
    print("Read only: GET requests, no credentials, nothing written.\n")

    print("1. The endpoint the downloader already uses")
    st, body = get(origin + "/maxtime/api/mibs/UsrDBName", args.timeout, origin)
    if st == 200:
        m = re.search(rb"\d{3}_\d{4}_[ -~]{1,80}", body)
        print("   HTTP 200, %d bytes. Active database: %s"
              % (len(body), m.group().decode() if m else "(name not found)"))
    elif st is None:
        print("   could not connect: %s" % body.decode("utf-8", "replace"))
        print("\n   Nothing else will work from here. Check the IP, check that "
              "port %d is open from this machine, and try a controller you "
              "know responds." % args.port)
        return 2
    else:
        print("   HTTP %s. This controller does not answer the open API the "
              "way the captured one did." % st)

    if args.mib:
        print("\n2. The MIB names given on the command line")
        any_hit = False
        for mib in args.mib:
            any_hit |= probe(origin, mib, args.timeout, args.raw)
        return 0 if any_hit else 1

    print("\n2. MIB names the controller's own web UI mentions")
    names = discover_mibs(origin, args.timeout, True)
    print("   found %d MIB name(s) in the UI bundles" % len(names))
    likely = sorted(n for n in names if INTERESTING_RE.search(n))
    if likely:
        print("   likely relevant: %s" % ", ".join(likely))
    else:
        print("   none of them mention cabinet, IO module, BIU, rack or TS2")

    order = likely if likely else []
    if args.all_mibs:
        order = sorted(names)
    if not order:
        order = list(FALLBACK_MIBS)
        print("   falling back to guessed names")

    print("\n3. Reading each candidate")
    hits = [mib for mib in order
            if probe(origin, mib, args.timeout, args.raw)]

    print()
    if hits:
        print("A cabinet IO module MIB is readable over the open API: %s"
              % ", ".join(hits))
        print("Send this output over. The box check can be automated.")
        return 0
    print("No candidate came back carrying BIU, TS2 or DR1.")
    print("Next thing to try, in this order:")
    print("  a. python3 probe_iomodules.py %s --all-mibs" % host)
    print("  b. open the controller UI, go Controller, Advanced IO, Cabinet")
    print("     Configuration, IO Modules with DevTools (F12) on the Network")
    print("     tab, and send the request URL that page fires.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
