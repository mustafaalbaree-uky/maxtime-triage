# MaxTime controller protocol (as used by the downloader)

The downloader talks to a controller's own API, which on a local network is
reachable directly and needs no login. These are the only two calls it makes,
both read only:

**Find the active user database name**

    GET http://<controller>:52270/maxtime/api/mibs/UsrDBName

Returns a binary MIB blob with the active user database name embedded as
ASCII, in the form `CCC_IDID_<intersection>`. The downloader extracts it with
a regular expression.

**Download that database**

    POST http://<controller>:52270/maxtime/api/db/download
    Content-Type: text/plain;charset=UTF-8
    body: {"name":"<db name>","type":"user"}

Returns the database file as a chunked `application/octet-stream`. The
downloader streams it to disk under the controller's own database name.

Both requests send `Origin` and `Referer` of the controller, matching the web
UI. Neither carries a cookie, token, or Authorization header, because the
controller API does not require one. If a particular controller ever answers
401 or 403, the downloader reports it rather than guessing at credentials.

## Re-capturing, if a firmware update changes the API

1. In the browser, open DevTools (F12), Network tab, tick **Preserve log**.
2. Do one full download by hand: sign in, Administration, Database
   Management, User Databases, the (Active) entry, Download.
3. Right click a request, **Save all as HAR**, and keep that file local only.
   It contains your password and session, so it must never be committed; the
   repo's `.gitignore` blocks `*.har` and the whole `data/` folder.
4. Compare the `db/download` and `mibs/UsrDBName` calls to the ones above.
