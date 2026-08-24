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


# A 4 digit signal ID appears delimited by a separator, never glued to a
# letter (which would be a route number like KY1267) or another digit.
ID_TOKEN_RE = re.compile(r"(?<![0-9A-Za-z])(\d{4})(?![0-9])")
# Standard SharePoint name: county, underscore, id, underscore, then the rest,
# with no stray space. Anything matching an ID but not this is nonstandard.
STANDARD_RE = re.compile(r"^\d{3}_\d{4}_\S")
LEADING_COUNTY_RE = re.compile(r"^(?:new)?(\d{3})[ _-]")
# Non timing extensions and system files to ignore outright.
IGNORE_EXTS = {"xlsx", "xls", "csv", "pdf", "ini", "lnk", "url", "zip",
               "docx", "doc", "png", "jpg", "jpeg", "gif", "txt"}
# A .key file is a controller key file, not a timing database.
KEY_EXTS = {"key"}
# Markers of a separate subsystem database (not intersection timing).
SPECIAL_RE = re.compile(r"ICWS|AWF|FLUSH|ITS[ _]?PLUS|\bEVENT\b", re.I)


def _ext(name):
    base = name.rsplit("/", 1)[-1]
    if "." in base and not base.startswith("."):
        return base.rsplit(".", 1)[-1].lower()
    return ""


def classify_file(name, valid_ids):
    """Classify one filename and pull out its signal ID if known.

    kind is one of: ignore, key, special, timing, unmatched.
    Only 'timing' files count as timing coverage. 'key' and 'special' files
    are shown for context but never counted. Matching is by the 4 digit ID
    against the set of known signals, because SharePoint names are hand typed
    and their prefixes, separators, and spacing are inconsistent.
    """
    base = str(name).strip().replace("\\", "/").split("/")[-1]
    result = {"name": base, "id": None, "county_prefix": None,
              "kind": "ignore", "standard": False}
    if not base or base.startswith(".") or base.lower() == "desktop.ini":
        return result
    ext = _ext(base)
    if ext in IGNORE_EXTS or base.lower().startswith("0000_d7"):
        return result

    ids = [t for t in ID_TOKEN_RE.findall(base) if t in valid_ids]
    result["id"] = ids[0] if ids else None
    m = LEADING_COUNTY_RE.match(base)
    if m:
        result["county_prefix"] = m.group(1)

    if ext in KEY_EXTS:
        result["kind"] = "key"
    elif SPECIAL_RE.search(base):
        result["kind"] = "special"
    elif result["id"] is None:
        result["kind"] = "unmatched"
    else:
        result["kind"] = "timing"
        result["standard"] = bool(STANDARD_RE.match(base))
    return result


def parse_listing(filenames, valid_ids):
    return [classify_file(n, valid_ids) for n in filenames if str(n).strip()]


def analyze(links, master, filenames):
    valid_ids = {i for i in links if i.isdigit() and len(i) == 4}
    valid_ids |= {m["id"] for m in master if m["id"].isdigit() and len(m["id"]) == 4}

    files = parse_listing(filenames, valid_ids)

    timing_by_id, files_by_id = {}, {}
    key_count = ignored_count = 0
    for f in files:
        if f["kind"] == "ignore":
            ignored_count += 1
            continue
        if f["kind"] == "key":
            key_count += 1
        if f["id"]:
            files_by_id.setdefault(f["id"], []).append(f)
            if f["kind"] == "timing":
                timing_by_id.setdefault(f["id"], []).append(f)
    covered = set(timing_by_id)

    def related(sid):
        return [{"name": f["name"], "kind": f["kind"]}
                for f in files_by_id.get(sid, []) if f["kind"] != "timing"]

    master_by_id, master_rows_by_id = {}, {}
    for m in master:
        master_rows_by_id.setdefault(m["id"], []).append(m)
        if m["id"] not in master_by_id:
            master_by_id[m["id"]] = m
    master_dup_ids = sorted(
        [{"id": sid,
          "rows": [{"row": r["row"], "county": r["county"],
                    "s1": r["s1"], "s2": r["s2"], "status": r["status"]}
                   for r in rows]}
         for sid, rows in master_rows_by_id.items() if len(rows) > 1],
        key=lambda d: (len(d["id"]), d["id"]))

    needs_download = []
    for sid in sorted(links, key=lambda s: (len(s), s)):
        if sid not in covered:
            e = dict(links[sid])
            e["id"] = sid
            mm = master_by_id.get(sid)
            e["master_row"] = mm["row"] if mm else None
            e["related_files"] = related(sid)
            needs_download.append(e)

    duplicates = [
        {"id": sid, "files": sorted(x["name"] for x in v)}
        for sid, v in sorted(timing_by_id.items()) if len(v) > 1
    ]

    mark_timing = []
    for sid in sorted(covered, key=lambda s: (len(s), s)):
        m = master_by_id.get(sid)
        if m and classify_status(m["status"]) == "todo":
            mark_timing.append({
                "id": sid, "master_row": m["row"], "county": m["county"],
                "s1": m["s1"], "s2": m["s2"], "status": m["status"],
            })

    nonstandard_naming, county_mismatch = [], []
    for f in files:
        if f["kind"] != "timing":
            continue
        if not f["standard"]:
            nonstandard_naming.append({"name": f["name"], "id": f["id"]})
        m = master_by_id.get(f["id"])
        if f["county_prefix"] and m and m["county_id"].isdigit():
            expect = "%03d" % int(m["county_id"])
            if f["county_prefix"] != expect:
                county_mismatch.append({
                    "file": f["name"], "file_county": f["county_prefix"],
                    "master_county": expect, "id": f["id"]})

    special_files = sorted(
        [{"name": f["name"], "id": f["id"]} for f in files if f["kind"] == "special"],
        key=lambda d: d["name"])
    unmatched_files = sorted(f["name"] for f in files if f["kind"] == "unmatched")

    links_not_in_master = [
        {"id": s, "county": links[s]["county"],
         "main": links[s]["main"], "side": links[s]["side"]}
        for s in sorted(links, key=lambda s: (len(s), s)) if s not in master_by_id]
    master_not_in_links = sorted(
        (s for s in master_by_id if s not in links), key=lambda s: (len(s), s))
    says_done_no_file = [
        {"id": s, "related_files": related(s)}
        for s in sorted(links, key=lambda s: (len(s), s))
        if s not in covered and s in master_by_id
        and classify_status(master_by_id[s]["status"]) == "done"]

    return {
        "needs_download": needs_download,
        "duplicates": duplicates,
        "mark_timing": mark_timing,
        "anomalies": {
            "nonstandard_naming": nonstandard_naming,
            "special_files": special_files,
            "unmatched_files": unmatched_files,
            "county_mismatch": county_mismatch,
            "links_not_in_master": links_not_in_master,
            "master_dup_ids": master_dup_ids,
            "says_done_no_file": says_done_no_file,
        },
        "info": {
            "master_not_in_links": master_not_in_links,
            "covered_count": len(covered),
            "timing_file_count": sum(len(v) for v in timing_by_id.values()),
            "key_file_count": key_count,
            "ignored_count": ignored_count,
        },
    }
