# How to complete the task on the work computer

Everything below runs on the work machine. The dashboard is a single HTML file
opened in Edge; the downloader is a small Python script. Nothing is uploaded.

## One time setup

1. From the repository, save `webapp/index.html` to the work computer (open the
   file, use the raw view, save keeping the `.html` extension), or email it to
   yourself and save the attachment. Double click it to open in Edge.
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

Open the **mark timing** tab. Each row is a signal whose timing file is already
in SharePoint but whose master row does not say so yet. For each one, put the
timing note in the master sheet's timing column at the row shown. Use **Copy ID
and row list** to paste them in quickly.

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

- **Nonstandard names**: matched by ID but worth retitling to `CCC_IDID_name`.
- **County prefix disagrees**: the three digit prefix does not match the master.
- **Subsystem files (ICWS, AWF)**: not timing databases, left as is.
- **No recognizable ID**: rename so the ID is present, or set aside.
- **Linked signals missing from the master**: before adding a row, search the
  master for that intersection in case the row exists with the ID left blank.
- **Duplicate ID rows in the master**: compare the two rows (shown side by side)
  and keep the correct one; flag rather than delete unless you are sure.

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
