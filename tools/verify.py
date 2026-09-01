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
    """A synthetic folder listing exercising every rule, including the messy
    real world naming: a stray space, a dash separator, a 'new' prefix, a
    missing county code, a .key file that must not count as timing, a subsystem
    (AWF) file, spreadsheets and dotfiles to ignore, a wrong county prefix, an
    unknown id, and a route number that must not be mistaken for a signal id.
    """
    ids = sorted(links, key=lambda s: (len(s), s))
    removed = ids[2:7]  # five signals with no timing file at all
    master_by_id = {m["id"]: m for m in master}
    names = []

    def cc_for(sid):
        m = master_by_id.get(sid)
        return "%03d" % int(m["county_id"]) if m and m["county_id"].isdigit() else "099"

    def label(sid):
        f = links[sid]
        return ("%s@%s" % (f["main"], f["side"])).replace(" ", "_")

    kept = [s for s in ids if s not in removed]
    for sid in kept:
        names.append("%s_%s_%s" % (cc_for(sid), sid, label(sid)))  # standard, no ext

    dup_id = ids[0]
    names.append("%s_%s_OLD_COPY" % (cc_for(dup_id), dup_id))  # duplicate timing db

    # nonstandard names that must still match by ID (these are NOT removed ids):
    space_id, dash_id, new_id, nocounty_id = kept[1], kept[7], kept[8], kept[9]
    names = [n for n in names if "_%s_" % space_id not in n]
    names.append("%s_ %s_%s" % (cc_for(space_id), space_id, label(space_id)))  # stray space
    names = [n for n in names if "_%s_" % dash_id not in n]
    names.append("%s-%s_%s" % (cc_for(dash_id), dash_id, label(dash_id)))      # dash
    names = [n for n in names if "_%s_" % new_id not in n]
    names.append("new%s_%s_%s" % (cc_for(new_id), new_id, label(new_id)))      # new prefix
    names = [n for n in names if "_%s_" % nocounty_id not in n]
    names.append("%s-%s.key" % (nocounty_id, label(nocounty_id)))  # KEY file, no timing db
    key_only_id = nocounty_id

    mismatch_id = kept[10]
    names = [n for n in names if "_%s_" % mismatch_id not in n]
    names.append("999_%s_WRONG_COUNTY" % mismatch_id)  # wrong county prefix

    # a subsystem file for a REMOVED id: it must not count as timing coverage,
    # but should be surfaced as a related special file.
    awf_id = removed[0]
    names.append("%s_ %s_%s_AWF_Flush" % (cc_for(awf_id), awf_id, label(awf_id)))

    names.append("055_9999_NOT_IN_ANY_SHEET")     # unknown id -> unmatched
    names.append("067-0000_KY57@KY1970_ICWS")     # id 0000 invalid, ICWS -> special
    names.append("0000_D7_MaxTime Links.xlsx")    # ignore
    names.append("desktop.ini")                   # ignore
    names.append(".849C9593-hidden")              # ignore dotfile
    names.append("District Contacts.pdf")         # ignore

    return (sorted(names), removed, dup_id, mismatch_id,
            {"space": space_id, "dash": dash_id, "new": new_id,
             "key_only": key_only_id, "awf": awf_id})


def main():
    links_path, master_path = sys.argv[1], sys.argv[2]
    links = T.parse_links(links_path)
    master = T.parse_master(master_path)
    names, removed, dup_id, mismatch_id, variants = build_mock_listing(links, master)
    result = T.analyze(links, master, names)
    an = result["anomalies"]

    need_ids = {e["id"] for e in result["needs_download"]}
    covered = {v for v in links} - need_ids
    # the nonstandard-named ones must be treated as covered (matched by ID)
    for key in ("space", "dash", "new"):
        assert variants[key] in covered, (key, variants[key], "not covered")
    # a key-only signal has no timing db, so it still needs download
    assert variants["key_only"] in need_ids, "key file wrongly counted as timing"
    # the AWF file must not cover its (removed) signal
    assert variants["awf"] in need_ids, "AWF file wrongly counted as timing"
    # ...but the AWF file shows up as a related special hint on that row
    awf_row = next(e for e in result["needs_download"] if e["id"] == variants["awf"])
    assert any(r["kind"] == "special" for r in awf_row["related_files"]), awf_row
    # needs-download is the five removed signals plus the key-only one
    assert set(need_ids) == set(removed) | {variants["key_only"]}, \
        (sorted(need_ids), removed, variants["key_only"])
    assert [d["id"] for d in result["duplicates"]] == [dup_id]
    assert any(c["id"] == mismatch_id for c in an["county_mismatch"])
    assert "055_9999_NOT_IN_ANY_SHEET" in an["unmatched_files"]
    assert any(s["name"].startswith("067-0000") for s in an["special_files"])
    assert {n["id"] for n in an["nonstandard_naming"]} >= {
        variants["space"], variants["dash"], variants["new"]}
    assert result["info"]["ignored_count"] == 4
    # box_check comes purely from the master and links sheets: every entry must
    # have a :57150 link and correspond to a real todo row.
    for e in result["box_check"]:
        assert e["url"].endswith(":57150"), e
        assert T.classify_box(next(m for m in master if m["id"] == e["id"]
                                   and m["row"] == e["master_row"])) == "todo"

    # jurisdiction: IDs below the cutoff are Fayette County and must not
    # reach any list, count, or deterministic verdict.
    oos_rows = {m["row"] for m in master if T.out_of_scope(m, links)}
    assert oos_rows, "no out of jurisdiction rows in this master sheet"
    below = lambda sid: sid.isdigit() and int(sid) < T.JURISDICTION_MIN_ID
    for sid in need_ids:
        assert not below(sid), ("needs_download", sid)
    for e in result["mark_timing"]:
        assert not below(e["id"]) and e["master_row"] not in oos_rows, e
    for e in result["box_check"]:
        assert not below(e["id"]) and e["master_row"] not in oos_rows, e
    for d in an["master_dup_ids"]:
        assert not below(d["id"]), d
        assert all(r["row"] not in oos_rows for r in d["rows"]), d
    for sid in result["info"]["master_not_in_links"]:
        assert not below(sid), ("master_not_in_links", sid)
    for x, d in T.det_verdicts(links, T.in_scope_rows(master, links)).items():
        assert d["row"] not in oos_rows, ("verdict on an out of scope row", x, d)
    assert result["info"]["out_of_scope"]["rows"] == len(oos_rows)

    data = pathlib.Path(__file__).parent.parent / "data"
    data.mkdir(exist_ok=True)
    (data / "mock_listing.txt").write_text("\n".join(names) + "\n")
    (data / "expected.json").write_text(json.dumps(result, indent=1))

    print("links signals: %d   master rows with id: %d" % (len(links), len(master)))
    print("mock files: %d" % len(names))
    print("needs download: %d  %s" % (len(need_ids), need_ids))
    print("duplicates: %s" % [d["id"] for d in result["duplicates"]])
    print("mark timing: %d" % len(result["mark_timing"]))
    print("box check: %d" % len(result["box_check"]))
    for k, v in an.items():
        print("anomaly %s: %d" % (k, len(v)))
    print("info master_not_in_links: %d" % len(result["info"]["master_not_in_links"]))
    oos = result["info"]["out_of_scope"]
    print("out of jurisdiction: %d rows (%d with an id), %s"
          % (oos["rows"], oos["with_id"],
             ", ".join("%s %d" % (c, n) for c, n in oos["counties"])))
    print("wrote data/mock_listing.txt and data/expected.json")


if __name__ == "__main__":
    main()
