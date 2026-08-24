"""Shared parsing and cross referencing logic for MaxTime timing triage.

This module is the reference implementation. webapp/index.html ports the
same rules to JavaScript; tools/verify.py asserts the two agree.
Stdlib only, so it also runs on a locked down work machine.
"""

import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

FILE_ID_RE = re.compile(r"^(\d{3})_(\d{4})(?=\D|$)")


def _col_of(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n


def read_sheet(path, sheet_name=None):
    """Return list of dict rows {col_index: value} for one sheet of an xlsx."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
    sheets = re.findall(r'<sheet [^>]*name="([^"]+)"[^>]*sheetId="\d+"', wb)
    idx = 0
    if sheet_name is not None and sheet_name in sheets:
        idx = sheets.index(sheet_name)
    sheet_file = "xl/worksheets/sheet%d.xml" % (idx + 1)
    root = ET.fromstring(z.read(sheet_file))
    rows = []
    for row in root.iter(NS + "row"):
        r = {}
        for c in row.findall(NS + "c"):
            t = c.get("t")
            v = c.find(NS + "v")
            if t == "inlineStr":
                is_ = c.find(NS + "is")
                val = "".join(tt.text or "" for tt in is_.iter(NS + "t")) if is_ is not None else ""
            elif v is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)]
            else:
                val = v.text
            r[_col_of(c.get("r"))] = val
        rows.append((int(row.get("r")), r))
    return rows


def _find_col(header_row, *needles, exact=None):
    """Locate a column index by header text. needles: all must appear (ci)."""
    for col, text in header_row.items():
        t = str(text).strip().lower()
        if exact is not None and t == exact.lower():
            return col
        if needles and all(n.lower() in t for n in needles):
            return col
    return None


def parse_links(path):
    """id -> {county, main, side, ip, port, url} for MaxTime master signals."""
    rows = read_sheet(path, "system information")
    header = rows[0][1]
    c_id = _find_col(header, exact="ID")
    c_county = _find_col(header, exact="County")
    c_main = _find_col(header, exact="Main")
    c_side = _find_col(header, exact="Side")
    c_ip = _find_col(header, exact="IP")
    c_port = _find_col(header, exact="Port")
    out = {}
    for rownum, r in rows[1:]:
        sid = str(r.get(c_id, "")).strip()
        if not sid:
            continue
        ip = str(r.get(c_ip, "")).strip()
        port = str(r.get(c_port, "")).strip()
        out[sid] = {
            "row": rownum,
            "county": str(r.get(c_county, "")).strip(),
            "main": str(r.get(c_main, "")).strip(),
            "side": str(r.get(c_side, "")).strip(),
            "ip": ip,
            "port": port,
            "url": ("http://%s:%s/maxtime/" % (ip, port)) if ip and port else "",
        }
    return out


def parse_master(path):
    """List of master rows: {row, id, county, county_id, s1, s2, status}."""
    rows = read_sheet(path, "MASTER SIGNAL LIST")
    header = rows[0][1]
    c_id = _find_col(header, exact="ID#")
    c_county = _find_col(header, "county")  # first header containing county
    c_cid = _find_col(header, exact="CountyID")
    c_s1 = _find_col(header, exact="Street 1")
    c_s2 = _find_col(header, exact="Street 2")
    c_ab = _find_col(header, "timing", "sharepoint")
    out = []
    for rownum, r in rows[1:]:
        sid = str(r.get(c_id, "")).strip()
        if not sid:
            continue
        out.append({
            "row": rownum,
            "id": sid,
            "county": str(r.get(c_county, "")).strip(),
            "county_id": str(r.get(c_cid, "")).strip(),
            "s1": str(r.get(c_s1, "")).strip(),
            "s2": str(r.get(c_s2, "")).strip(),
            "status": str(r.get(c_ab, "")).strip(),
        })
    return out


def classify_status(text):
    """'done' if AB already records timing, 'excluded' for na, else 'todo'."""
    t = (text or "").strip().lower()
    if not t:
        return "todo"
    if "timing" in t or "yes" in t:
        return "done"
    if t == "na" or t == "n/a":
        return "excluded"
    return "todo"


def parse_listing(filenames):
    """filenames -> (files list, unparsed list).

    files: {name, county_code, id}. Extensions and folder paths are ignored.
    """
    files, unparsed = [], []
    for raw in filenames:
        name = str(raw).strip().replace("\\", "/").split("/")[-1]
        if not name:
            continue
        m = FILE_ID_RE.match(name)
        if m:
            files.append({"name": name, "county_code": m.group(1), "id": m.group(2)})
        else:
            unparsed.append(name)
    return files, unparsed


def analyze(links, master, filenames):
    files, unparsed = parse_listing(filenames)
    by_id = {}
    for f in files:
        by_id.setdefault(f["id"], []).append(f)
    covered = set(by_id)

    master_by_id = {}
    master_dup_ids = set()
    for m in master:
        if m["id"] in master_by_id:
            master_dup_ids.add(m["id"])
        else:
            master_by_id[m["id"]] = m

    needs_download = []
    for sid in sorted(links, key=lambda s: (len(s), s)):
        if sid not in covered:
            e = dict(links[sid])
            e["id"] = sid
            mm = master_by_id.get(sid)
            e["master_row"] = mm["row"] if mm else None
            needs_download.append(e)

    duplicates = [
        {"id": sid, "files": sorted(x["name"] for x in v)}
        for sid, v in sorted(by_id.items()) if len(v) > 1
    ]

    mark_timing = []
    for sid in sorted(covered, key=lambda s: (len(s), s)):
        m = master_by_id.get(sid)
        if m and classify_status(m["status"]) == "todo":
            mark_timing.append({
                "id": sid, "master_row": m["row"], "county": m["county"],
                "s1": m["s1"], "s2": m["s2"], "status": m["status"],
            })

    county_mismatch = []
    for sid, group in sorted(by_id.items()):
        m = master_by_id.get(sid)
        if not m or not m["county_id"].isdigit():
            continue
        expect = "%03d" % int(m["county_id"])
        for f in group:
            if f["county_code"] != expect:
                county_mismatch.append({
                    "file": f["name"], "file_county": f["county_code"],
                    "master_county": expect, "id": sid,
                })

    file_id_unknown = sorted(
        f["name"] for f in files
        if f["id"] not in links and f["id"] not in master_by_id
    )
    links_not_in_master = sorted(
        (s for s in links if s not in master_by_id), key=lambda s: (len(s), s)
    )
    master_not_in_links = sorted(
        (s for s in master_by_id if s not in links), key=lambda s: (len(s), s)
    )
    says_done_no_file = sorted(
        (s for s in links
         if s not in covered and s in master_by_id
         and classify_status(master_by_id[s]["status"]) == "done"),
        key=lambda s: (len(s), s),
    )

    return {
        "needs_download": needs_download,
        "duplicates": duplicates,
        "mark_timing": mark_timing,
        "anomalies": {
            "unparsed_filenames": sorted(unparsed),
            "file_id_unknown": file_id_unknown,
            "county_mismatch": county_mismatch,
            "links_not_in_master": links_not_in_master,
            "master_dup_ids": sorted(master_dup_ids),
            "says_done_no_file": says_done_no_file,
        },
        "info": {
            "master_not_in_links": master_not_in_links,
            "covered_count": len(covered),
            "file_count": len(files),
        },
    }
