# How to complete the task on the work computer

Everything below runs on the work machine. The dashboard is a single HTML file
opened in Edge; the downloader is a small Python script. Nothing is uploaded.

## One time setup

1. Take `webapp/index.html` to the work computer (download it from the
   repository there) and double click it to open in Edge. Everything works
   from the dropped sheets, including the blank ID rows, the row aligned
   column pastes, and the new row layout. The generated copy with a baked in
   snapshot (`python3 tools/embed_master.py <master.xlsx>`, gitignored) is
   retired; it still builds but is only worth it if dropping the master
   sheet each time ever becomes a bother.
2. Optional, only needed for the automatic downloader: confirm Python 3 is
   present (`python3 --version` or `py --version`).

## Step 1: load the three inputs

In the dashboard:

1. Drop the signal links sheet and the district master sheet on the first card.
2. Point the second card at the timing files: pick the synced SharePoint
   folder, drop a CSV exported from the library, or paste the file names.

The summary cards fill in: need download, duplicate IDs, mark timing, box check,
anomalies, coverage. Everything is matched by the four digit signal ID, so odd
names (a stray space, a dash, a missing county code) still line up.

## Step 2: mark timing in the master sheet

Open the **sheet column** tab. It shows the master sheet's "Timing & key
updated to sharepoint" column for every row: what the people before already
wrote is locked on the left and always survives into the output. Where the
cell is blank but a timing file exists in SharePoint, the output autofills
"timing (was already in sharepoint)". Click **Copy the whole column** and
paste it over the sheet column starting at row 2; the copy is row aligned,
one line per sheet row. A cell can be force edited when you are certain, and
the edit is shown in red against the struck through original.

Sorted out ID fixes and new rows appear here too: confirmed fixes add a short
note to the row's column text and light up **Copy ID column** (paste over the
ID# column the same row aligned way; unchanged cells are copied exactly as
they are). Signals marked "not in the sheet" become prefilled rows at the
bottom, and **Copy new rows** pastes them at column A on the first empty row.
Do all three pastes on a fresh copy of the sheet the first time.

The older **mark timing** tab still lists the same signals one by one if you
would rather type them in by hand.

## Step 3: download the missing databases

Open the **need download** tab. These signals have no timing file.

For each row, either:

- Click the controller link, sign in, go Administration, Database Management,
  User Databases, the entry marked Active, Download; or
- Use the automatic downloader: click **Export CSV for the downloader**, then on
  the work computer run
  `python3 downloader/fetch_missing.py needs_download.csv --out downloaded`.
  Do one first with `--only <id>` and confirm it before running the rest.

Open each downloaded database and confirm it is the intersection you expect
before placing it in SharePoint. Only add a file if that ID is not already
there. Check the row off in the tool as you finish it; the checkmarks persist.

If a row shows an orange "found a non timing file for this ID" note, a file
with that ID already exists but is a key file or a subsystem export, not a
timing database. Open it and decide by hand before downloading a new one.

## Step 4: work the anomalies

Open the **anomalies** tab and handle each group:

- **Out of jurisdiction**: a count, not a worklist. Signal IDs below 4000 are
  Fayette County, which this district does not maintain, confirmed by the
  supervisor on 1 September 2026. The tool sets those rows aside everywhere:
  they are not in the download list, the box check, the duplicate ID rows or
  the missing signal linker, and their timing column pastes back exactly as
  the sheet has it. There is nothing to do here and nothing to type in the
  sheet for them.
- **Nonstandard names**: matched by ID but worth retitling to `CCC_IDID_name`.
- **County prefix disagrees**: blocking TODO. The task is not complete until
  each one is checked by hand and ticked off in its card. If the master is
  wrong, tell the supervisor; if the file title is wrong, retitle it; if the
  downloaded database is for a different intersection, stop and raise it.
- **Subsystem files (ICWS, AWF)**: not timing databases, left as is.
- **No recognizable ID**: rename so the ID is present, or set aside.
- **Linked signals missing from the master**: the tool guesses the sheet row
  from the street names (many rows exist with the ID left blank), and a blue
  box flags a near certain mistyped ID found deterministically: the row that
  matches the missing signal carries an ID that is either duplicated (with
  the other row matching that ID's own intersection) or unknown to MaxTime.
  Click **It's this row**, verify by hand (the sheet's Latitude and Longitude
  in a map, or the controller's own page), then click **I have sorted it
  out**. Only that click writes anything: a short note into the sheet column
  and the ID fix into the ID column copy. **Not in the sheet, needs a new
  row** creates a prefilled row in the sheet column tab instead.
- **Duplicate ID rows in the master**: shown side by side with differences
  highlighted. Pick **Keep this row** or flag for the supervisor and add a
  note; nothing is deleted, the picks are a worklist for editing the sheet.

## Step 5: box check

This is now its own page. See "The box column" at the end of this file; the
box check tab in `index.html` is the older, thinner version of the same list.

Open the **box check** tab. These signals are not yet confirmed in the box
column and are not front rack. Confirming a box means opening the controller at
port **57150** and checking Properties for sensors.

If port 57150 is blocked on the work network, this step waits. The list and your
checkmarks are saved in the tool and rebuild from the sheets every time, so
nothing is lost. Click **Export CSV** to keep a copy. When you get access, open
each link, confirm the box (loops usually mean no box, mark N A; radar or
wavetronix means there is a box to configure), and update the master column.

## Step 6: finish up

Once the rest is done, rename the master sheet's box column from "Box Verified"
to "Box Configuration Downloaded". The tool reads either name.

---

# The box column: `webapp/box.html`

A separate page for the second job. Same two sheets, a different folder, and
three columns instead of one. Open `webapp/box.html` the same way you open
`index.html`: double click it, drop the sheets on it.

## What decides the work

Confirmed by the supervisor on 8 September 2026:

* SharePoint is the source of truth. If the clickbox configuration folder
  already holds a file for a signal ID, that signal is finished and only the
  sheet needs labelling. Files carry the export's own date and time, so the
  same signal legitimately appears more than once and names cannot be
  compared; matching is by the four digit ID found anywhere in the name.
* Where there is no file, the answer comes from the controller:
  `Controller`, `Advanced IO`, `Cabinet Configuration`, `IO Modules`. A
  `TS2 DR1 BIU` in IO module 2 means the signal has a clickbox.
* A box means the detection column is Wavetronix even where the sheet still
  says Loops, and the box column becomes `BOX`. No BIU means `N/A`.
* To fetch the file, open the same IP at port `57150`, then `Properties`. Name,
  Location and Description have to be filled in first, then
  `Save Device Properties` at the bottom of the panel, then
  `Export Configuration`. The three values come out of the sheets and the row
  shows them under **properties**, with a copy button each. See
  `downloader/CLICKBOX.md`.

## Step 1: load the inputs

Drop the links sheet and the master sheet on the first card, then point the
second card at the synced SharePoint clickbox configuration folder (folder
picker, a CSV export, a txt listing, or pasted names). Without the folder
every signal counts as not yet in SharePoint, so the check list is at its
longest.

## Step 2: work the check list

Every signal that still needs the controller opened, each tagged with why it
is there:

* **never checked**: both box columns blank.
* **sheet is unsure**: the box column carries a question mark (`FD05?`,
  `170?`, `none?`).
* **waiting on someone**: the column says emailed, no comm, needs a field
  check, not yet.
* **sheet says saved, no file**: the sheet records the box as downloaded and
  the clickbox folder has nothing for that ID.
* **box, config not downloaded**: the sheet says there is a box and the file
  was never fetched.
* **box column says something else**: text that is not a recognized answer.

Press **BIU, box** or **no BIU** for each. A box reveals the `:57150` link and
a tick box for once the export is in SharePoint. What you press is saved in
the browser and survives closing the page.

A clickbox that never answers is recorded with the reason and the run carries
on; importing that run puts the reason on the row as its note and leaves the
signal in the list, and importing a later run where it went through takes the
note off again. `--auto` works through the list without stopping, except at
a device whose fields already disagree with the sheets. A signal an earlier run
already exported is skipped, so a worklist exported before that run cannot
cause a second visit, and one that failed goes to the back of the list so it
cannot fill a limited run. `--failed` works through those alone, and
`--ping` reports which addresses answer on port 57150 at all without opening a
browser, and writes the ones that do not into a run record, so importing it
puts the reason on each of those rows without a browser going near them.

A row answered **BIU, box** carries two ticks, not one: **exported off the
device** and **moved to SharePoint**. They are separate days' work, and only
the second writes `YES` into the sheet's Box Verified column.
Importing a run of `fetch_clickbox.py` ticks the first for you; nothing but you
can tick the second. See `downloader/CLICKBOX.md`.

Every cell this tool fills, in all three columns, carries who filled it:
`Wavetronix (added by intern)`, `BOX (added by intern)`,
`N/A (added by intern)`, `YES (added by intern)`,
`already in sharepoint (added by intern)`, and a note you typed the same way. A
signal whose file you exported reads `YES (added by intern)` once that file is
in the folder, even though its row has left the check list by then. A cell the
sheet already fills is copied through untouched and is never signed, and
neither is a blank one.

A row whose Detection already says Wavetronix and which you answered **no BIU**
on is counted separately in the bar, since the sheet and the cabinet disagree
about whether the box question applies to it. **Export the N Wavetronix with no
BIU** writes those rows for `fetch_clickbox.py --ping`, which says whether a
clickbox answers at any of them. Their cells still paste `N/A` until that is
settled.

Where neither answer applies, a login that failed for instance, type it in the
row's note box instead. On a row with no BIU answer, the note is what the Box
or Front rack column pastes, in place of `BOX` or `N/A`. Pressing either answer
afterwards takes the cell back; the note stays on the row as a note.

Rows the sheet already settles cleanly (front rack, `n/a`, with no question
mark and nobody waiting) are not in the list; they are on the **settled** tab.

## Step 3: paste the three columns back

The **sheet columns** tab holds one copy button per column: Detection,
Box or Front rack (FR), and Box Verified. Each copy is one line per sheet row
so it pastes straight over its column, and the tab names the exact cell to
paste at. What the sheet already says is locked and copied through unchanged.
Only a result recorded in step 2 overwrites a cell, and autofill only ever
fills a blank one.

## Step 4: file names and the missing rows

The **file names** tab flags exports whose name carries an ID but does not
name the intersection, names that match no signal, and names whose words do
not match the sheet's own streets for that ID. Retitle those in SharePoint.

The **not in the master** tab lists signals that exist in the links sheet with
no row in the master sheet. They get no box check because there is no row to
record it on. These should have been added during the timing pass; raise them
with the supervisor.

## Automating the BIU check

The check repeats once per signal, which is why it is worth testing whether
the controller will answer it directly. On the work computer, against a single
controller you know responds:

    python3 downloader/probe_iomodules.py <controller-ip>

It is read only: GET requests, no credentials, nothing written. It reads the
endpoint the downloader already uses to prove the open API works, then pulls
every MIB name out of the controller's own web UI and reads the ones that
mention cabinet, IO module, BIU, rack or TS2, reporting which response
carries `BIU`. If none do, run it again with `--all-mibs`, and failing that
open the IO Modules page with DevTools on the Network tab and send the request
URL that page fires.

## Checking the rules without a browser

    python3 tools/verify_box.py

Pulls the page's own logic out of `webapp/box.html`, runs it under node
against the real sheets plus a mock clickbox folder built to trip every file
rule, and prints the counts. `--empty-folder` runs it with no folder listing.

### Browser checker with reviewed import

For the calibrated browser automation workflow, use
[`downloader/BIU_CHECK.md`](downloader/BIU_CHECK.md). Export the automation
worklist from the updated box page, calibrate once, test one controller, then
review/import `results.json`. BIU configuration downloads remain manual.

### Finding an ID that seems to be missing

In the box page, use **find an ID** to see its master row(s), links-sheet row,
matching folder filenames, and current page status. This searches all loaded
inputs independently of the check-list filter. A saved file moves an existing
master row to **in sharepoint**, so it no longer appears in the controller check
list. When the links intersection exactly matches a master row carrying a blank
or different ID, the lookup shows that row for manual verification.

**Missing sheet records** also lists candidate four-digit IDs from folder
filenames that occur in neither sheet. These remain unverified: filename numbers
can be route numbers. They do not create master rows, controller links, or BIU
answers automatically. Compare the intersection and check spreadsheet versions
before adding or correcting a record.
