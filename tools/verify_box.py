#!/usr/bin/env python3
"""Run webapp/box.html's own logic against the real sheets, outside a browser.

The page keeps its pure functions between LOGIC-START and LOGIC-END markers
with no DOM in them. This script pulls that block out, hands it the two real
sheets plus a mock clickbox folder listing built to trip every rule, and
prints what the page would show. Nothing here touches the browser copy of the
logic, so a rule that changes in one place and not the other shows up as a
different count.

    python3 tools/verify_box.py
    python3 tools/verify_box.py --master data/master.xlsx --links data/frankfort.xlsx

Needs node on PATH. Prints nothing that is not already in the sheets.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage_lib as T  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOGIC_RE = re.compile(r"/\* =+ LOGIC-START =+.*?\*/(.*?)/\* =+ LOGIC-END =+ \*/",
                      re.S)

DRIVER = r"""
const fs = require("node:fs");
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const links = parseLinks(data.links);
const parsed = parseMaster(data.master);
const master = parsed.rows, meta = parsed.meta;
const r = analyzeBox(links, master, data.listing);
const cols = computeColumns(r, master, meta, data.found);
const count = a => a.length;
const out = {
  links: Object.keys(links).length,
  masterRows: master.length,
  meta,
  inScope: count(r.rows),
  outOfScope: count(r.oos),
  check: count(r.check),
  have: count(r.have),
  label: count(r.label),
  settled: count(r.settled),
  noip: count(r.noip),
  notInMaster: count(r.notInMaster),
  clickboxFiles: count(r.clickbox),
  dupIds: count(r.dupIds),
  fileFlags: Object.fromEntries(
    Object.entries(r.fileFlags).map(([k, v]) => [k, count(v)])),
  whyCounts: (() => {
    const c = {};
    for (const e of r.check) for (const w of e.why) c[w] = (c[w] || 0) + 1;
    return c;
  })(),
  columnLengths: cols
    ? { det: cols.det.length, boxfr: cols.boxfr.length, boxdone: cols.boxdone.length,
        span: cols.lastRow - cols.firstRow + 1 }
    : null,
  changed: cols
    ? { det: cols.det.filter(x => x.out !== x.base).length,
        boxfr: cols.boxfr.filter(x => x.out !== x.base).length,
        boxdone: cols.boxdone.filter(x => x.out !== x.base).length }
    : null,
  samples: {
    check: r.check.slice(0, 5).map(e => ({ id: e.id, row: e.row, why: e.why,
      det: e.detection, fr: e.box_fr, done: e.box_done })),
    label: r.label.slice(0, 5).map(e => ({ id: e.id, row: e.row,
      files: e.files.map(f => f.name) })),
    noName: r.fileFlags.noName.slice(0, 5).map(f => f.name),
    nameOff: r.fileFlags.nameOff.slice(0, 5).map(f => ({ name: f.name,
      words: f.words, sheet: [f.row.s1, f.row.s2].join(" @ ") })),
    unmatched: r.fileFlags.unmatched.slice(0, 5).map(f => f.name),
  },
  fieldEffect: (() => {
    /* the same run with one recorded result, to prove the columns move */
    const id = r.check.length ? r.check[0].id : null;
    if (!id) return null;
    const c2 = computeColumns(r, master, meta,
      { [id]: { biu: "yes", saved: true } });
    const pick = key => c2[key].find(x => x.id === id);
    return { id, det: pick("det"), boxfr: pick("boxfr"), boxdone: pick("boxdone") };
  })(),
  noteEffect: (() => {
    /* a note with no BIU answer stands in for the answer in the box column,
       and an answer still outranks it */
    const id = r.check.length ? r.check[0].id : null;
    if (!id) return null;
    const only = computeColumns(r, master, meta, { [id]: { note: "LOGIN FAILED" } });
    const both = computeColumns(r, master, meta,
      { [id]: { biu: "no", note: "LOGIN FAILED" } });
    const pick = (c, key) => c[key].find(x => x.id === id);
    return { id, noteOnly: pick(only, "boxfr"), withAnswer: pick(both, "boxfr") };
  })(),

  clickboxRun: (() => {
    /* what a run of fetch_clickbox.py does to the rows: a file ticks exported,
       a failure lands on the row as its note and ticks nothing, and a note a
       person typed is never written over */
    const ids = r.check.slice(0, 3).map(e => e.id);
    if (ids.length < 3) return null;
    const found = { [ids[2]]: { biu: "yes", note: "asked the district" } };
    const run = { schema: "maxtime-clickbox-v1", run: "x", results: [
      { id: ids[0], exported: "files/a.cbx", error: "", skipped: "", note: "" },
      { id: ids[1], exported: "", skipped: "",
        error: "the clickbox never answered at port 57150 (timed out)", note: "" },
      { id: ids[2], exported: "", skipped: "",
        error: "no Save Device Properties on this screen", note: "" },
      { id: "9999", exported: "files/b.cbx", error: "", skipped: "", note: "" },
    ] };
    const by = {};
    for (const u of clickboxUpdates(run, r.check, found)) by[u.id] = u;

    /* the retry: the same signal goes through, and the note the failed run
       left on it comes off, while a note a person typed stays */
    const after = { [ids[1]]: { biu: "yes", note: "timed out", noteFrom: "clickbox" },
                    [ids[2]]: { biu: "yes", note: "asked the district" } };
    const retry = { schema: "maxtime-clickbox-v1", run: "y", results: [
      { id: ids[1], exported: "files/c.cbx", error: "", skipped: "", note: "" },
      { id: ids[2], exported: "files/d.cbx", error: "", skipped: "", note: "" },
    ] };
    for (const u of clickboxUpdates(retry, r.check, after)) by[u.id + " retried"] = u;
    return by;
  })(),
};
console.log(JSON.stringify(out, null, 2));
"""


def sheet_json(path, name):
    """read_sheet gives [(rownum, {col: value})]; JSON wants plain lists."""
    return [[rownum, {str(k): v for k, v in cells.items()}]
            for rownum, cells in T.read_sheet(path, name)]


def mock_listing(master, links):
    """A clickbox folder built to trip every file rule, from real IDs only."""
    ids = [m["id"] for m in T.in_scope_rows(master, links) if m["id"].strip()]
    ids = sorted(set(ids))[:40]
    names = []
    for i, sid in enumerate(ids):
        m = next(x for x in master if x["id"] == sid)
        street = re.sub(r"[^A-Za-z0-9]+", "_", (m["s1"] + "@" + m["s2"]).strip("_"))
        cty = (m["county_id"] or "000")[:3].rjust(3, "0")
        if i % 7 == 3:                      # carries the ID and nothing else
            names.append("%s_%s_20260812_1431.cbx" % (cty, sid))
        elif i % 7 == 5:                    # name has nothing to do with the sheet
            names.append("%s_%s_ZEPHYR_QUARRY_20260812.cbx" % (cty, sid))
        else:
            names.append("%s_%s_%s_20260812_1431.cbx" % (cty, sid, street[:28]))
        if i % 9 == 2:                      # a second export of the same signal
            names.append("%s_%s_%s_20260901_0902.cbx" % (cty, sid, street[:28]))
    names += ["clickbox_export_20260901.cbx",   # no recognizable ID
              "desktop.ini", "notes.xlsx",      # ignored outright
              "012_9999_SOMEWHERE_20260101.cbx"]  # ID nobody knows
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=str(ROOT / "data" / "master.xlsx"))
    ap.add_argument("--links", default=str(ROOT / "data" / "frankfort.xlsx"))
    ap.add_argument("--page", default=str(ROOT / "webapp" / "box.html"))
    ap.add_argument("--empty-folder", action="store_true",
                    help="run with no clickbox listing at all")
    args = ap.parse_args()

    html = Path(args.page).read_text(encoding="utf-8")
    m = LOGIC_RE.search(html)
    if not m:
        print("could not find the LOGIC block in %s" % args.page)
        return 2
    logic = m.group(1)

    master = T.parse_master(args.master)
    links = T.parse_links(args.links)
    listing = [] if args.empty_folder else mock_listing(master, links)

    payload = {
        "links": sheet_json(args.links, "system information"),
        "master": sheet_json(args.master, "MASTER SIGNAL LIST"),
        "listing": listing,
        "found": {},
    }

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "logic.cjs").write_text(logic + DRIVER, encoding="utf-8")
        (td / "data.json").write_text(json.dumps(payload), encoding="utf-8")
        r = subprocess.run(["node", str(td / "logic.cjs"), str(td / "data.json")],
                           capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        return 1
    print(r.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
