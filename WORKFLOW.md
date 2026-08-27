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

- **Master IDs outside the links sheet's range**: the links export only spans
  one block of IDs, so master rows numbered outside it cannot be judged by
  anything MaxTime based, and "unknown to maxtime" evidence (including the
  blue box mistyped ID checks) means nothing for them. The card counts them
  by county, flags any that already have a timing file in SharePoint (which
  argues the export is incomplete rather than the signals out of scope), and
  its copy button produces a ready summary with the question to put to the
  supervisor. Do not mark these rows NA on your own.
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

## Step 5: box check (on hold until port access)

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
