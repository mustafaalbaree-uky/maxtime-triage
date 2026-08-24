#!/usr/bin/env python3
"""Compute expected triage results from the two real sheets plus a mock
SharePoint listing, and write them to data/expected.json so the browser
tool can be checked against them. Also writes the mock listing itself.

Usage: python3 tools/verify.py <links.xlsx> <master.xlsx>
"""

import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import triage_lib as T


def build_mock_listing(links, master):
    """A synthetic folder listing exercising every rule:
    every links signal has a file EXCEPT five removed ones; one id is
    duplicated; one file has a wrong county prefix; one file's id exists
    nowhere; one filename does not parse.
    """
    ids = sorted(links, key=lambda s: (len(s), s))
    removed = ids[2:7]
    master_by_id = {m["id"]: m for m in master}
    names = []
    for sid in ids:
        if sid in removed:
            continue
        m = master_by_id.get(sid)
        cc = "%03d" % int(m["county_id"]) if m and m["county_id"].isdigit() else "099"
        f = links[sid]
        label = ("%s@%s" % (f["main"], f["side"])).replace(" ", "_")
        names.append("%s_%s_%s.db" % (cc, sid, label))
    dup_id = ids[0]
    names.append("%s_%s_OLD_COPY.db" % (names[0][:3], dup_id))
    kept = [s for s in ids if s not in removed]
    mismatch_id = kept[1]
    names = [n for n in names if "_%s_" % mismatch_id not in n]
    names.append("999_%s_WRONG_COUNTY.db" % mismatch_id)
    names.append("055_9999_NOT_IN_ANY_SHEET.db")
    names.append("notes about the folder.txt")
    return sorted(names), removed, dup_id, mismatch_id


def main():
    links_path, master_path = sys.argv[1], sys.argv[2]
    links = T.parse_links(links_path)
    master = T.parse_master(master_path)
    names, removed, dup_id, mismatch_id = build_mock_listing(links, master)
    result = T.analyze(links, master, names)

    need_ids = [e["id"] for e in result["needs_download"]]
    assert set(need_ids) == set(removed), (need_ids, removed)
    assert [d["id"] for d in result["duplicates"]] == [dup_id]
    an = result["anomalies"]
    assert any(c["id"] == mismatch_id for c in an["county_mismatch"])
    assert "055_9999_NOT_IN_ANY_SHEET.db" in an["file_id_unknown"]
    assert an["unparsed_filenames"] == ["notes about the folder.txt"]

    data = pathlib.Path(__file__).parent.parent / "data"
    data.mkdir(exist_ok=True)
    (data / "mock_listing.txt").write_text("\n".join(names) + "\n")
    (data / "expected.json").write_text(json.dumps(result, indent=1))

    print("links signals: %d   master rows with id: %d" % (len(links), len(master)))
    print("mock files: %d" % len(names))
    print("needs download: %d  %s" % (len(need_ids), need_ids))
    print("duplicates: %s" % [d["id"] for d in result["duplicates"]])
    print("mark timing: %d" % len(result["mark_timing"]))
    for k, v in an.items():
        print("anomaly %s: %d" % (k, len(v)))
    print("info master_not_in_links: %d" % len(result["info"]["master_not_in_links"]))
    print("wrote data/mock_listing.txt and data/expected.json")


if __name__ == "__main__":
    main()
