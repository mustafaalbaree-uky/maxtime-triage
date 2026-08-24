# Capturing the MaxTime HTTP flow (one time, on the work computer)

The downloader needs to know the exact HTTP calls behind "sign in" and
"Download". One capture against a single controller is enough.

1. Open Edge and press F12 to open DevTools. Go to the **Network** tab and
   tick **Preserve log**.
2. Navigate to one controller, e.g. `http://10.x.x.x:52270/maxtime/`.
3. Do the full flow once, exactly as usual: sign in to Controller,
   Administration, Database Management, User Databases, the entry marked
   (Active), Download.
4. In the Network tab, right click any request and choose
   **Save all as HAR (with sensitive data)**. Save it as `maxtime.har`.
5. Bring `maxtime.har` back to the Mac and put it in this repo's `data/`
   folder (which git ignores), then ask Claude to fill in `MaxTimeClient`
   from it.

Important: the HAR contains the password you typed and the session cookie.
It must never leave `data/`, never be emailed anywhere but to yourself, and
should be deleted as soon as the client methods are written.

After the client is filled in, the first live run should be a single signal
with your supervisor aware:

    python3 fetch_missing.py needs_download.csv --only 4070

Only after that looks right, run the full list.
