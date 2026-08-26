#!/usr/bin/env python3
"""Bake a snapshot of the district master sheet into the dashboard.

Reads every content row of the MASTER SIGNAL LIST sheet, including rows whose
ID cell is blank (parse_master skips those, but the sheet column view and the
row linker need them), and writes webapp/d7.html: a copy of webapp/index.html
with the snapshot injected between the BASELINE markers.

webapp/d7.html carries real district data and must never be committed. The
repo's .gitignore covers it; the public index.html keeps BASELINE = null.

Usage: python3 tools/embed_master.py <master.xlsx> [-o webapp/d7.html]
"""

import argparse
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import triage_lib as T

ROOT = pathlib.Path(__file__).parent.parent

# Facts about the data that the dashboard shows alongside the anomaly lists.
# Update these when the situation changes, then regenerate.
NOTES = {
    "nonstandard": "Checked by hand on 26 Aug 2026: every nonstandard file "
                   "name was opened and maps to the correct signal. The ID "
                   "matching for these names is trusted.",
    "says_done": "Checked by hand on 26 Aug 2026: where the sheet said done "
                 "but no standard file existed, the file was there under a "
                 "different title and the mapping is correct.",
}

BLOCK_RE = re.compile(
    r"(/\* BASELINE-START.*?\*/\n)const BASELINE = .*?;(\n/\* BASELINE-END \*/)",
    re.S)


def snapshot(master_path):
    rows = T.read_sheet(master_path, "MASTER SIGNAL LIST")
    header = rows[0][1]
    c_id = T._find_col(header, exact="ID#")
    c_county = T._find_col(header, "county")
    c_cid = T._find_col(header, exact="CountyID")
    c_s1 = T._find_col(header, exact="Street 1")
    c_s2 = T._find_col(header, exact="Street 2")
    c_ab = T._find_col(header, "timing", "sharepoint")
    c_det = T._find_col(header, exact="Detection")
    c_boxfr = T._find_col(header, "box", "rack")
    c_boxdone = T._find_box_done_col(header)
    cols = {"county": c_county, "id": c_id, "county_id": c_cid,
            "s1": c_s1, "s2": c_s2, "status": c_ab}
    out = []
    for rownum, r in rows[1:]:
        def g(col):
            return str(r.get(col, "") or "").strip()
        rec = {
            "row": rownum, "id": g(c_id), "county": g(c_county),
            "county_id": g(c_cid), "s1": g(c_s1), "s2": g(c_s2),
            "status": g(c_ab), "detection": g(c_det),
            "box_fr": g(c_boxfr), "box_done": g(c_boxdone),
        }
        if any([rec["id"], rec["county"], rec["s1"], rec["s2"], rec["status"]]):
            out.append(rec)
    return out, cols


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("master", help="path to the master sheet xlsx")
    ap.add_argument("-o", "--out", default=str(ROOT / "webapp" / "d7.html"))
    ap.add_argument("--template", default=str(ROOT / "webapp" / "index.html"))
    args = ap.parse_args()

    rows, cols = snapshot(args.master)
    baseline = {
        "generated": datetime.date.today().isoformat(),
        "source": pathlib.Path(args.master).name,
        "firstRow": 2,
        "lastRow": max(r["row"] for r in rows),
        "cols": cols,   # 1 based sheet column of each captured field
        "rows": rows,
        "notes": NOTES,
    }
    blob = json.dumps(baseline, separators=(",", ":"), ensure_ascii=False)
    blob = blob.replace("</", "<\\/")  # never close the script tag early

    template = pathlib.Path(args.template).read_text(encoding="utf-8")
    if not BLOCK_RE.search(template):
        sys.exit("BASELINE markers not found in " + args.template)
    baked = BLOCK_RE.sub(
        lambda m: m.group(1) + "const BASELINE = " + blob + ";" + m.group(2),
        template, count=1)

    out = pathlib.Path(args.out)
    out.write_text(baked, encoding="utf-8")
    with_id = sum(1 for r in rows if r["id"])
    print("wrote %s: %d rows (%d with an ID, %d blank), sheet rows 2..%d"
          % (out, len(rows), with_id, len(rows) - with_id, baseline["lastRow"]))


if __name__ == "__main__":
    main()
