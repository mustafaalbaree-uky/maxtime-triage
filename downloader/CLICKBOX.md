# Clickbox properties and export

The clickbox at port 57150 needs three Properties fields filled in before its
configuration is exported. Two of the three come out of sheets you already
have and the third is the same everywhere, so the tool works them out and you
approve them. Nothing is typed from memory.

| field | value | where it comes from |
|---|---|---|
| Name | `076-4380` | master sheet: `CountyID` padded to three digits, then `ID#` |
| Location | `US 25 at KY 52 (IRVING RD)` | links sheet: `Main` at `Side` |
| Description | `KYTC D7` | the same on every device |

Location comes from the links sheet rather than the master sheet on purpose.
The master sheet carries the GIS wording for the same intersection
(`52-IRVING RD`), and the links sheet carries what MaxTime itself shows
(`KY 52 (IRVING RD)`).

## Where the values are, before any script runs

In `box.html`, a row you have marked **BIU, box** and not yet ticked as saved
carries a **properties** toggle in the Open column. It shows the three values
for that signal with a copy button each. That is enough to do the job by hand:
copy, paste, press **Save Device Properties**, then **Export Configuration**.

The **Export clickbox worklist** button in the same bar writes
`clickbox_worklist.csv`, one line per box still owed:

```
id,clickbox_url,name,location,description
4380,http://10.136.1.193:57150/,076-4380,US 25 at KY 52 (IRVING RD),KYTC D7
```

A signal whose sheets cannot produce a Name or a Location is not put in that
file, and the row says which of the two is missing instead.

## Running it

```
py -m pip install "playwright>=1.51,<2"
py fetch_clickbox.py clickbox_worklist.csv              one clickbox
py fetch_clickbox.py clickbox_worklist.csv --only 4030  one named signal
py fetch_clickbox.py clickbox_worklist.csv --all        the whole worklist
```

Add `--browser chromium` if Edge cannot be controlled on your computer, after
`py -m playwright install chromium`. On Mac or Linux use `python3` for `py`.

## Without stopping at every device

```
py fetch_clickbox.py clickbox_worklist.csv --all --auto
```

`--auto` answers `y` for you wherever the field is empty. Those values are
derived from the sheets by the same rule every time, and the row prints before
it is typed, so the run still shows what went in.

It does not answer for a field that already holds something the sheets
disagree with. The device is saying something the sheets are not, and which of
the two is right is not something a flag can settle, so those stop and wait as
before. `--auto-replace` answers for those too and is the only way to have a
run overwrite a value nobody looked at.

The run record says which it was, `"confirmed": "auto"` or `"by hand"`, per
signal.

## Asking at every device

Without `--auto`, every device asks before anything is typed:

```
====================================================================
Signal 4030
  Name         (empty)                            <- would fill in
               009-4030
  Location     (empty)                            <- would fill in
               US 68X at KY 1678 CLINTONVILLE
  Description  (empty)                            <- would fill in
               KYTC D7
====================================================================
Type y to fill in, save, then export, n to skip this signal, q to stop:
```

A field already holding something different is called out on its own:

```
!! 2 fields already filled in and DIFFERENT from the sheets.
  !!Name       device says '076-4030'
               sheets say  '009-4030'
  !!Location   device says 'US 68 AT 1678'
               sheets say  'US 68X at KY 1678 CLINTONVILLE'
  Description  KYTC D7                            already correct
====================================================================
Type y to REPLACE and save, then export, n to skip this signal, q to stop:
```

Answering `y` types the three fields, presses **Save Device Properties**, reads
the three back to prove the device kept them, then presses **Export
Configuration** and saves whatever it sends. The file keeps the name the device
gives it; a second file of the same name is numbered rather than overwritten.
Moving them into SharePoint stays manual.

```
clickbox-exports/
  files/    the configurations, and nothing else
  runs/     clickbox-run-<stamp>.json, what each run did
```

The configurations sit on their own so that folder can be selected whole and
dragged into the SharePoint clickbox configuration folder. `--out-dir` moves
the pair.

Nothing else on that screen is touched. The IP address, subnet mask, default
gateway, Ethernet control port and the BIU and sensor checkboxes sit on the
same form and are never typed into.

If the device does not show a value back after saving, it is reported and the
export is not attempted, because an export of a device that did not take the
change is a file that says the wrong thing.

At the end the run lists what happened per signal, names anything it overwrote,
and writes the run record.

## Putting the run back into box.html

**Import a clickbox run** in the check list bar takes
`runs/clickbox-run-<stamp>.json` and ticks **exported off the device** for every
signal that produced a file. Anything the device overwrote lands on that row as
its note, so what the field used to say is not lost.

A signal that did not export lands on its row as a note saying why, `the
clickbox never answered at port 57150 (timed out)` for instance, and ticks
nothing. It stays in the check list and in the next worklist.

Import a later run in which that signal went through and the note comes off
again, so no row is left saying a device timed out after it did not. A note you
typed yourself is neither written over nor removed: the report says the row
kept it.

It never ticks **moved to SharePoint**. Nothing but you moving the file can say
that, and only that tick writes YES into the sheet's Box Verified column. A
record that was skipped by hand, or an ID that is not in the current check
list, is listed in the report rather than applied.

Export a fresh `clickbox_worklist.csv` after importing and the finished
signals are gone from it.

## A worklist that is out of date

The page cannot see the script running, so a worklist exported before a run
still carries what that run finished. The script reads its own previous run
records and skips those signals rather than visiting them twice:

```
1 already exported by an earlier run, skipping 4380.
```

`--again` works through them anyway, and `--only` names a signal whatever the
records say. Both read `clickbox-exports/runs/`, so `--out-dir` moves the
memory with the files.

## The ones that keep timing out

A device that times out does it again on the next run, so with `--limit 20` the
same twenty failures would fill every run and the signals nobody has tried yet
would never be reached. They go to the back of the list instead of out of it:

```
5 failed in an earlier run, moved to the back of the list. --failed works through those alone.
```

So a run of twenty takes twenty fresh signals first. When the fresh ones run
out, the failures come round again on their own.

```
py fetch_clickbox.py clickbox_worklist.csv --failed --all --auto
```

works through only the ones that failed before, which is what to run when the
network problem behind them is fixed.

A device that never answers is waited on once rather than twice, so a dead
address costs one `--timeout` and not two. `--timeout 8` cuts it further on a
list where many are down.

## Sorting the timeouts out without a browser

```
py fetch_clickbox.py clickbox_worklist.csv --failed --ping
```

`--ping` opens a socket to each address and reports, several at a time, in a
fraction of a second each. It opens no browser, types nothing and presses
nothing.

```
  4002   silent     10.136.1.44
  4041   answers    10.136.1.51
  4118   refused    10.136.1.77

1 of 3 answered on port 57150.
To work through those:
  --only 4041
```

* **answers**: the clickbox is there. Run it.
* **silent**: nothing at that address, or nothing this computer can reach. The
  device is off, the address is wrong, or the network does not carry you there.
* **refused**: something is at that address and nothing is listening on 57150.
  That is a live controller with no clickbox answering, which is worth knowing
  before anybody drives out to it.

Run it on the whole worklist, or on the failures alone with `--failed`.

The ones that did not answer are written into a run record like any other run,
so importing it in box.html puts the reason on each of those rows at once:

```
11 written to clickbox-exports/runs/clickbox-run-20260915T170139Z.json
```

Nothing that answered is in that record, and a ping never says anything
exported, since it opened no browser. Those rows keep their place in the check
list, carry the reason as their note, and go to the back of the next run's
list.

## A field the device cannot hold

The Click 656 caps Location at 32 characters and cuts the rest off as the
browser types, so a long intersection is never stored whole:

```
  Location     US 127 COLLEGE ST at US 68 MOREL
               the field holds 32 characters, so 'US 127 COLLEGE ST at US 68 MORELAND' is cut to fit
```

The proposal is cut to what the field holds before anything is compared, so a
device already carrying the cut value reads as correct rather than as a
disagreement, and the read back after saving agrees with what was typed. Before
this, signal 4422 reported a field that disagreed, then a save the device had
refused, and exported nothing.

`--limit` defaults to 1, so the first run of a session is one device unless you
ask for more. `--timeout` is how long a clickbox gets to answer, 20 seconds by
default.

## A clickbox that never answers

Some of them time out. That is a result like any other, so it is written into
the run record with the reason, either `timed out` or whatever the browser
said (`ERR_CONNECTION_REFUSED`, `ERR_ADDRESS_UNREACHABLE`), and the run carries
on to the next signal:

```json
{ "id": "4002", "exported": "", "error":
  "the clickbox never answered at port 57150 (timed out)" }
```

Answering on a screen that does not carry the three properties is reported
separately, since that one needs the device looked at rather than the network.

The end of the run groups the ones that never answered and prints the `--only`
line to try them again. Importing the run into `box.html` leaves those rows
exactly as they were and lists them in the report with the reason.

## Looking without touching

`fetch_clickbox.py --describe` opens one clickbox and reports what its
Properties screen contains. **It changes nothing**: it types into no field and
presses no Save, Apply or Export. It is how the run loop above was written,
the device UI not being available on the machine it came from.

```
py fetch_clickbox.py clickbox_worklist.csv --describe --only 4030
```

It prints every field with its labels and current contents, every button and
link with its path, and its best guess at which control is which. Press Enter
again after moving to another tab to describe that screen too, or `QUIT` to
finish. It writes `clickbox-diagnostic.json`, which holds the screen structure
and the field labels, and no password, address or cookie.

## What one Click 656 reported, 10 Sep 2026

The first real read, on a Wavetronix Click 656 running firmware 1.2.0:

* The three fields are `deviceName`, `deviceLocation` and `deviceDescription`,
  labelled `Name:`, `Location:` and `Description:`.
* Saving is `btnSaveDevice`, an `input[type=button]` reading
  `Save Device Properties`. It sits in the field list as well as the button
  list, so the fill step must never treat it as somewhere to type.
* **Export Configuration is a plain footer link**, not a button:
  `Main | Admin | Export Configuration | Import Configuration | Upgrade | About`.
  The first version of this tool looked only for buttons and missed it.
* **The device lands on Health, not Properties, and the top tabs are not
  links.** PROPERTIES, SENSORS, CHANNELS, VERIFICATION, HEALTH and GRAPHS carry
  no href, no role and no id, so they appear in no list of links and there is
  no path to navigate to. The only handle on them is their text, so the script
  clicks the word `Properties`, anchored so that neither the `Device Properties`
  heading nor the `Save Device Properties` control can be hit instead.
* The first version assumed whatever screen the device opened on was the right
  one, because during the describe pass a person had already clicked
  PROPERTIES by hand. It reported "no Name, Location and Description on any
  screen" on every device.
* The same screen carries the device's IP address, subnet mask, default gateway,
  Ethernet control port and the BIU and sensor port checkboxes. The fill step
  touches the three properties and nothing else.

## If a device does not look like the Click 656

Run `--describe` on it and send `clickbox-diagnostic.json`. It holds the screen
structure, the field labels, and what the three properties currently say, and
no password, controller address or cookie. Password and hidden fields are named
but never read, and the address is left out of the file deliberately so it can
be sent.

The run refuses to touch a device whose screen does not carry all three fields
and a Save Device Properties control. It says so and moves on.

## The two worklists are not interchangeable

`biu_worklist.csv` carries `maxtime_url` and drives `check_biu.py`, which only
reads. `clickbox_worklist.csv` carries `clickbox_url` and drives this, which
types into the device. Each script refuses the other's file, and
refuses a URL on the wrong port.
