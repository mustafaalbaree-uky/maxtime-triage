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

## What the script does so far

`fetch_clickbox.py --describe` opens one clickbox, waits while you bring up
Properties, and writes down what the screen contains. **It changes nothing**:
it types into no field and presses no Save, Apply or Export.

This exists because the clickbox UI is not available on the machine the tool
was written on, exactly as with `check_biu.py`. Filling, saving and exporting
are written against what this reports rather than guessed at.

```
py -m pip install "playwright>=1.51,<2"
py fetch_clickbox.py clickbox_worklist.csv --describe --only 4380
```

Add `--browser chromium` if Edge cannot be controlled on your computer, after
`py -m playwright install chromium`. On Mac or Linux use `python3` for `py`.

It prints every field on screen with its labels and what it currently holds,
every button, and then its best guess at which control is Name, Location and
Description, which button is Save Device Properties, and which is Export
Configuration. For each of the three it says whether the field is empty, agrees
with the proposal, or differs from it.

Press Enter again after moving to another tab to describe that screen too.
Type `QUIT` to finish.

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
* The Properties screen is served at `/` and the top tabs (PROPERTIES, SENSORS,
  CHANNELS, VERIFICATION, HEALTH, GRAPHS) do not change the path.
* The same screen carries the device's IP address, subnet mask, default gateway,
  Ethernet control port and the BIU and sensor port checkboxes. The fill step
  touches the three properties and nothing else.

## What to send back

`clickbox-diagnostic.json`, written next to the script. It holds the screen
structure, the field labels, and what the three properties currently say.

It does not hold a password, a controller address, or a cookie. Password and
hidden fields are named but never read, and the address is left out of the file
deliberately so it can be sent.

## What comes next

Once the screen is known, the run loop is: open each clickbox in the worklist,
read the three fields, and

* **all three already correct**: nothing to do, move on.
* **empty**: show what would go in, wait for `y`.
* **filled but different**: say so loudly, show both, wait for `y`. Approving
  records what it was and what it became.

Then `Save Device Properties`, then `Export Configuration`, with the file
landing in an output folder. Moving it into the SharePoint clickbox
configuration folder stays manual.

## The two worklists are not interchangeable

`biu_worklist.csv` carries `maxtime_url` and drives `check_biu.py`, which only
reads. `clickbox_worklist.csv` carries `clickbox_url` and drives this, which
will eventually write to the device. Each script refuses the other's file, and
refuses a URL on the wrong port.
