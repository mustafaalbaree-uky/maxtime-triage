#!/usr/bin/env python3
"""Offline test of the downloader against a mock MaxTime controller that
replays the real endpoints (UsrDBName MIB, db/download). Stdlib only.

Run: python3 downloader/test_downloader.py
"""
import csv
import http.server
import re
import sys
import threading
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import fetch_missing as F

ACTIVE_NAME = "012_7070_SR151@MAIN_ST"
DB_BYTES = b"SQLite format 3\x00" + b"MOCKDBCONTENT" * 500


def make_mib_blob(name):
    """A fake ~9KB MIB blob with the db name embedded, like the real one."""
    pad = b"\x00\x01mib-header\x00" * 40
    return pad + name.encode("ascii") + b"\x00\x02trailer\x00" + b"\x00" * 8000


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/maxtime/api/mibs/UsrDBName":
            blob = make_mib_blob(ACTIVE_NAME)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(blob)
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8")
        if self.path == "/maxtime/api/db/download":
            assert '"type":"user"' in body, body
            assert ACTIVE_NAME in body, body
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            # stream in chunks like the real chunked response
            for i in range(0, len(DB_BYTES), 4096):
                self.wfile.write(DB_BYTES[i:i + 4096])
        else:
            self.send_error(404)


def main():
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/maxtime/" % port

    fails = 0

    # 1. name discovery from the MIB blob
    client = F.MaxTimeClient(base)
    name = client.active_database_name()
    if name == ACTIVE_NAME:
        print("ok name discovery: %s" % name)
    else:
        print("FAIL name discovery: got %r" % name); fails += 1

    # 2. streamed download writes the exact bytes
    out = HERE.parent / "data" / "dl_test"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()
    dest = out / (name + F.SAVE_EXT)
    size = client.download(name, dest)
    got = dest.read_bytes()
    if got == DB_BYTES and size == len(DB_BYTES):
        print("ok download streamed %d bytes to %s" % (size, dest.name))
    else:
        print("FAIL download: %d bytes, match=%s" % (size, got == DB_BYTES)); fails += 1

    # 3. full main() flow: CSV in, id-match check, resume skip
    csv_path = out / "needs.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "county", "main", "side", "ip", "port", "url"])
        w.writerow(["7070", "MAPLE", "SR 151", "MAIN ST", "127.0.0.1", port, base])
    rc = _run_main([str(csv_path), "--out", str(out), "--delay", "0"])
    if rc == 0 and (out / (ACTIVE_NAME + F.SAVE_EXT)).exists():
        print("ok main flow downloaded via CSV")
    else:
        print("FAIL main flow rc=%s" % rc); fails += 1

    # 4. resume: second run skips the already present file
    rc2, out_txt = _run_main_capture([str(csv_path), "--out", str(out), "--delay", "0"])
    if "skip 7070" in out_txt and rc2 == 0:
        print("ok resume skips existing file")
    else:
        print("FAIL resume: %s" % out_txt.strip()); fails += 1

    # 5. id mismatch guard: CSV claims a different id than the controller reports
    bad = out / "bad.csv"
    with open(bad, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "county", "main", "side", "ip", "port", "url"])
        w.writerow(["9999", "X", "A", "B", "127.0.0.1", port, base])
    empty = HERE.parent / "data" / "dl_empty"
    empty.mkdir(exist_ok=True)
    for f in empty.glob("*"):
        f.unlink()
    rc3, out3 = _run_main_capture([str(bad), "--out", str(empty), "--delay", "0"])
    if "WARNING" in out3 and "id mismatch" in out3 and rc3 == 1:
        print("ok id mismatch guard refuses to save wrong signal")
    else:
        print("FAIL id mismatch guard: rc=%s %s" % (rc3, out3.strip())); fails += 1

    srv.shutdown()
    print("\n%s" % ("all downloader tests passed" if not fails
                    else "%d downloader test(s) FAILED" % fails))
    return 1 if fails else 0


def _run_main(argv):
    old = sys.argv
    sys.argv = ["fetch_missing.py"] + argv
    try:
        return F.main()
    finally:
        sys.argv = old


def _run_main_capture(argv):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _run_main(argv)
    return rc, buf.getvalue()


if __name__ == "__main__":
    sys.exit(main())
