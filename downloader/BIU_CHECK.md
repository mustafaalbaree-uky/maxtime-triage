# Automated BIU checks on the work computer

Download **check_biu.py** and the updated **webapp/box.html**. Keep using the
same copy/location of box.html so your browser's saved progress stays available.
The checker runs on the work network and uses a separate, visible Edge window.
It logs in and opens the IO Modules page; it does not press controller Save or
Apply buttons or fetch clickbox configurations. Login itself creates a session.

The actual controller UI is not available on the development Mac. This is a
calibrated first version: the table reader is configured against one real
controller, and automatic navigation must then pass the one-item test below.
Different firmware, frames, custom grids, or different login labels can need a
small adapter. An unrecognized screen produces `unknown`, never `no`.

## Install once

In a terminal on Windows:

```
py -m pip install "playwright>=1.51,<2"
```

The script uses installed Microsoft Edge by default. If Edge cannot be controlled
on your computer, install Playwright's browser and add `--browser chromium` to
the script commands:

```
py -m playwright install chromium
```

On Mac/Linux use `python3` instead of `py`. Browser channels and installation are
documented in [Playwright's browser documentation](https://playwright.dev/python/docs/browsers).

## Export and calibrate once

1. Open the updated box.html, load your sheets and clickbox folder listing.
2. In the check list, click **Export automation worklist**. This exports rows
   with MaxTime links that have no recorded BIU answer. It includes the full
   unresolved list, regardless of the text filter. Previously completed manual
   checks and BIU rows awaiting downloads are excluded.
3. Put `biu_worklist.csv` next to `check_biu.py` and open a terminal there.
4. Choose an actual ID from your worklist (replace `4821` below):

```
py check_biu.py biu_worklist.csv --setup --only 4821
```

In the browser it opens, manually sign in and navigate to **Controller >
Advanced IO > Cabinet Configuration > IO Modules**. Return to the terminal
and press Enter. It displays readable tables. Select the IO module table and
its module number and type columns by number.

This screen carries no HTML table and no row elements. The module list is a
set of grid panes: a frozen module column beside a scrolling pane, with the
column headings in panes of their own. The reader rebuilds the rows from where
the cells sit on screen, so the table it shows you is the table you see. Check
it row by row before confirming. Only rows on screen are read, so if a
controller ever has more modules than fit the pane, scroll until all of them
are visible before pressing Enter.

Only type `COMPLETE` if it really contains every configured module: no paging,
filters, collapsed modules or virtual scrolling. The first table row must be
column headings, and each following row must represent one configured module,
numbered consecutively from 1. The reader uses selected dropdown labels rather
than all available options. Confirm the proposed answer with `AGREE` only if
you agree with your manual check. This creates `biu-profile.json`, which holds
column headings and column numbers, not credentials or controller addresses.

If it cannot read a table it says why, prints what the screen actually
contains (tabs, frames, tables, rows, and any visible text mentioning a module
type) and writes the same detail to `biu-diagnostic.json`. Press Enter to read
again once the page has settled, or type `QUIT`. A clock or a live status table
elsewhere on the screen no longer blocks the read; each table is judged on its
own contents.

If the module list still cannot be read, or setup reports `unknown`, stop
there: this firmware needs an adapter. Send `biu-diagnostic.json` and the
terminal message. There is no need to send a password, HAR file, or cookies.

## Test automatic navigation on one controller

```
py check_biu.py biu_worklist.csv --only 4821
```

It asks for your username and hidden password once, keeping them in memory,
then signs in and goes straight to the screen's own address,
`/maxtime/Controller/AdvancedIO/CabinetConfiguration/IOModules`. Firmware that
does not route by address falls back to the four menu items. Watch the browser
during this first test. Each controller gets a fresh session.

Results go in a new timestamped folder beneath `biu-results`, with
`results.json` and screenshots of successfully read module pages. Each result
includes the ID, source URL, timestamp, observed table, proposed answer and
reason. No result overwrites an older run. Completed rows are saved after each
controller, so Ctrl+C preserves progress already written.

Review the screenshot and module evidence against what you see manually.
Calibrate on one controller, then test at least one known **no BIU** and one
known **TS2 DR1 BIU in module 2** before trusting a large batch. A module type not observed during calibration, an unfamiliar
BIU type/position, missing module type, incomplete table, changed headers,
failed login or timeout stays **unknown**.

## What the unknowns are for

Calibration records the module types on the one controller you calibrated
against, and nothing else. A cabinet built from different modules comes back
`unknown` naming the type it found, for example `Module type not seen during
calibration: ts2 siu`. A BIU anywhere other than module 2 comes back `unknown`
naming where it was. That is deliberate: the script never guesses `no` from a
module it has not been shown.

So the first full run doubles as the survey. Run it, then read the unknown
reasons: between them they name every module type in the field. Bring that
list back and we decide together whether to widen `observed_non_biu_types` in
`biu-profile.json`, which is a plain list of type names. Widening it can only
turn `unknown` into `no`, and only for cabinets with no BIU in any module.

A lone module 1 means `no` only because you certified during setup that this
is the complete configured module table. Recalibrate if the firmware/layout
changes. The ID is associated with the worklist's URL; the script does not
independently prove the controller's physical intersection identity.

## Review and import

In box.html, click **Review script results** and select `results.json`. The
preview shows evidence and any skipped rows. Click **I reviewed these — apply**
to accept the eligible proposals. This is a deliberate review step; importing
alone changes nothing.

- `yes` acts like **BIU, box** and reveals the `:57150` link. Fetch and save the
  box file manually, then mark it saved as before.
- `no` acts like **no BIU**.
- `unknown` stays open for a manual check.
- Already recorded answers, settled rows, duplicate IDs and changed controller
  URLs are skipped. To replace an earlier answer deliberately, clear it first.

The existing sheet-column copy buttons work with the accepted results.

## A few, then the rest

```
py check_biu.py biu_worklist.csv --limit 3
py check_biu.py biu_worklist.csv --all
```

Without `--all` or `--limit`, it checks **one** controller. Checks are sequential
with three seconds between controllers. If a failed check is still showing the
password form, the batch stops instead of repeating the failed login. Import accepted results and export a
fresh worklist before continuing; that is how you resume without rechecking
completed rows. Unknown rows remain in the next export.

Keep results local. Screenshots contain controller details; result JSON contains
internal addresses. There are no cloud services, credential files, session
exports, or telemetry in the script. The HTML page still makes no network calls.
