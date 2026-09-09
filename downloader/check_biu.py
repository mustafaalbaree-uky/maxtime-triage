#!/usr/bin/env python3
"""Read IO Modules using a visible browser. See BIU_CHECK.md. No controller saves."""
import argparse
import csv
from datetime import datetime, timezone
from getpass import getpass
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit

SCHEMA = 'maxtime-biu-v1'
# The IO Modules screen has its own address, so the menu walk is only a fallback.
IO_PATH = 'Controller/AdvancedIO/CabinetConfiguration/IOModules'
IO_MARKER = re.compile(r'^IO Modules?$', re.I)
TABLES_JS = r"""() => {
 const visible = e => !!(e.getClientRects().length);
 const text = e => {
   const s = e.matches('select') ? e : e.querySelector('select');
   if (s) return Array.from(s.selectedOptions).map(o => o.textContent.trim()).join(' ');
   const i = e.matches('input') ? e : e.querySelector('input:not([type=password]):not([type=hidden])');
   if (i && i.type !== 'password' && i.type !== 'hidden') return i.value.trim();
   return e.innerText.trim();
 };
 const containers = Array.from(document.querySelectorAll('table,[role=grid],[role=treegrid]')).filter(visible);
 const tables = [];
 containers.forEach((t, index) => {
   const rows = Array.from(t.querySelectorAll('tr,[role=row]')).filter(visible).map(r =>
     Array.from(r.querySelectorAll('th,td,[role=columnheader],[role=gridcell]')).map(text)
   ).filter(r => r.length);
   if (rows.length > 1) tables.push({index, source: 'rows', rows});
 });
 // MaxTime draws the IO module list as grids that carry no row elements: a
 // frozen first column and a separate header pane are several containers on
 // screen but one table to the eye. Rebuild the rows from where cells sit.
 const cells = [], seen = new Set();
 for (const t of containers) {
   let found = Array.from(t.querySelectorAll('[role=gridcell],[role=columnheader],[role=rowheader],th,td'));
   if (!found.length) found = Array.from(t.querySelectorAll('*')).filter(e => e.matches('select,input') || !e.querySelector('*'));
   for (const c of found) if (!seen.has(c) && visible(c)) { seen.add(c); cells.push(c); }
 }
 const placed = cells.map(e => { const r = e.getBoundingClientRect(); return {x: r.left, y: r.top, t: text(e)}; })
                     .filter(c => c.t !== '');
 placed.sort((a, b) => a.y - b.y || a.x - b.x);
 const banded = [];
 for (const c of placed) {
   const row = banded[banded.length - 1];
   if (row && c.y - row.y <= 8) row.cells.push(c); else banded.push({y: c.y, cells: [c]});
 }
 const rows = banded.map(r => r.cells.sort((a, b) => a.x - b.x).map(c => c.t));
 if (rows.length > 1) tables.push({index: -1, source: 'position', rows});
 return tables;
}"""

DIAGNOSE_JS = r"""() => {
 const cut = (s, n) => { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n) + '...' : s; };
 const visible = e => !!(e.getClientRects().length);
 const cls = e => cut(typeof e.className === 'string' ? e.className : '', 40);
 const rows = e => Array.from(e.querySelectorAll('tr,[role=row]'));
 const leaves = Array.from(document.querySelectorAll('body *')).filter(e =>
   !e.children.length && visible(e) && /\b(BIU|TS2|DR1|SIU|module)\b/i.test(e.textContent || ''));
 return {
   url: location.href.split('?')[0],  // The hash route names the screen; the query can carry a token.
   title: cut(document.title, 80),
   counts: {table: document.querySelectorAll('table').length,
            grid: document.querySelectorAll('[role=grid]').length,
            row: document.querySelectorAll('tr,[role=row]').length,
            select: document.querySelectorAll('select').length,
            input: document.querySelectorAll('input').length,
            canvas: document.querySelectorAll('canvas').length,
            frame: document.querySelectorAll('iframe,frame').length},
   grids: Array.from(document.querySelectorAll('table,[role=grid]')).map((t, index) => ({
     index, tag: t.tagName.toLowerCase(), cls: cls(t), visible: visible(t),
     rows: rows(t).length, visibleRows: rows(t).filter(visible).length,
     text: cut(t.innerText, 200)})),
   hits: leaves.slice(0, 12).map(e => e.tagName.toLowerCase() + ' .' + cls(e) + ' :: ' + cut(e.textContent, 70)),
   controls: Array.from(document.querySelectorAll('select,input,button,[role=combobox],[role=listbox]')).filter(visible).slice(0, 25).map(e => {
     const tag = e.tagName.toLowerCase();
     const role = e.getAttribute('role') ? '[' + e.getAttribute('role') + ']' : '';
     const name = [e.id, e.name, e.getAttribute('aria-label'), e.getAttribute('placeholder')].filter(Boolean).map(v => cut(v, 30)).join(' ');
     // Option labels and which one is selected. Never any entered value.
     if (tag === 'select') return 'select ' + name + ' :: ' + Array.from(e.options).map((o, i) => (o.selected ? '*' : '') + (i + 1) + ' ' + cut(o.textContent, 40)).join(' | ');
     if (tag === 'input') return 'input[' + e.type + '] ' + name;
     return tag + role + ' ' + name + ' :: ' + cut(e.textContent, 40);
   }),
   labels: Array.from(document.querySelectorAll('body *')).filter(e => !e.children.length && visible(e) &&
     (e.textContent || '').trim() && (e.textContent || '').trim().length <= 120).slice(0, 24).map(e => cut(e.textContent, 120))
 };
}"""


def norm_space(value):
    return re.sub(r'\s+', ' ', str(value)).strip()


def norm(value):
    return norm_space(value).casefold()


def origin(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Expected an HTTP(S) controller URL without credentials')
    if p.port == 57150:
        raise ValueError('Use the MaxTime URL, not the clickbox URL')
    return (p.scheme.lower(), p.hostname.lower(), p.port or (443 if p.scheme == 'https' else 80))


def read_worklist(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not {'id', 'maxtime_url'}.issubset(reader.fieldnames or []):
            raise ValueError('Export the automation worklist from the updated box.html')
        rows = list(reader)
    seen = set()
    for r in rows:
        r['id'] = r['id'].strip()
        r['maxtime_url'] = r['maxtime_url'].strip()
        if not re.fullmatch(r'[4-9]\d{3}', r['id']) or r['id'] in seen:
            raise ValueError('Worklist contains an invalid or duplicate ID')
        seen.add(r['id'])
        origin(r['maxtime_url'])
    return rows


def column_headings(profile):
    headers = profile['headers']
    return (profile.get('module_header') or headers[profile['module_column']],
            profile.get('type_header') or headers[profile['type_column']])


def resolve_columns(header, profile):
    """The two columns this rule needs, found by their headings. Cabinets differ
    in how many columns they show, and a column we never read is not a reason to
    refuse the two we do. Each heading must appear exactly once."""
    found = []
    for want in column_headings(profile):
        hits = [i for i, cell in enumerate(header) if norm(cell) == norm(want)]
        if len(hits) != 1:
            return None
        found.append(hits[0])
    return None if found[0] == found[1] else tuple(found)


def classify(rows, profile):
    """Never infer absence from a missing page/table, blank type or malformed row."""
    columns = resolve_columns(rows[0], profile) if rows else None
    if not columns:
        return 'unknown', 'Module number or type column heading is missing; recalibrate'
    module_column, type_column = columns
    modules = {}
    for row in rows[1:]:
        if len(row) != len(rows[0]):
            return 'unknown', 'Incomplete or unexpected table row'
        raw = norm(row[module_column])
        match = re.fullmatch(r'(?:(?:io\s*)?module\s*)?#?\s*(\d+)', raw)
        kind = norm(row[type_column])
        if not match or not kind or kind in ('loading', 'loading...', '(select)', 'select', 'unknown', 'error', '-'):
            return 'unknown', 'Module number or selected type was unreadable'
        number = int(match[1])
        if number in modules or number < 1:
            return 'unknown', 'Duplicate or invalid module number'
        modules[number] = kind
    if not modules or sorted(modules) != list(range(1, len(modules) + 1)):
        return 'unknown', 'Module list is empty or has gaps'
    target = modules.get(2)
    if target == 'ts2 dr1 biu':
        return 'yes', 'Module 2: TS2 DR1 BIU'
    biu = ['module %d: %s' % (n, t) for n, t in sorted(modules.items()) if 'biu' in t]
    if biu:
        return 'unknown', 'BIU outside the agreed module 2 rule (' + '; '.join(biu) + ')'
    unseen = sorted({t for t in modules.values() if t not in profile.get('observed_non_biu_types', [])})
    if unseen:
        return 'unknown', 'Module type not seen during calibration: ' + ', '.join(unseen)
    if not profile.get('complete_table_confirmed'):
        return 'unknown', 'Table completeness has not been confirmed'
    return 'no', ('Only module 1 is configured' if target is None else 'Module 2: ' + target)


def click_text(page, pattern, timeout=8000):
    # Exact names, unique visible match. Never use coordinates or arbitrary first match.
    rx = re.compile(pattern, re.I)
    until = time.monotonic() + timeout / 1000
    while time.monotonic() < until:
        for role in ('button', 'link', 'menuitem', 'tab'):
            loc = page.get_by_role(role, name=rx).filter(visible=True)
            if loc.count() == 1:
                loc.click()
                return
        loc = page.get_by_text(rx).filter(visible=True)
        if loc.count() == 1:
            loc.click()
            return
        # Native dropdown menus use selected option text, not a click on <option>.
        choices = []
        for select in page.locator('select:visible').all():
            for opt in select.locator('option').all():
                if rx.fullmatch(opt.inner_text().strip()):
                    choices.append((select, opt.get_attribute('value'), opt.inner_text()))
        if len(choices) == 1:
            select, value, label = choices[0]
            select.select_option(value=value) if value is not None else select.select_option(label=label)
            return
        page.wait_for_timeout(200)
    raise RuntimeError('Could not uniquely locate navigation: ' + pattern)


CHOICE_JS = r"""(want) => {
 const norm = s => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
 const visible = e => !!(e.getClientRects().length);
 const target = norm(want);
 const found = Array.from(document.querySelectorAll('body *'))
   .filter(e => visible(e) && norm(e.innerText).includes(target));
 // The smallest element still carrying the text is the choice, not its panel,
 // and the innermost of equals is the option rather than its wrapper.
 const depth = e => { let d = 0; for (let p = e; p; p = p.parentElement) d++; return d; };
 found.sort((a, b) => norm(a.innerText).length - norm(b.innerText).length || depth(b) - depth(a));
 return found[0] || null;
}"""


def click_choice(page, text, timeout=8000):
    """Click the smallest visible element whose text contains this."""
    until = time.monotonic() + timeout / 1000
    while True:
        element = page.evaluate_handle(CHOICE_JS, text).as_element()
        if element:
            label = norm_space(element.inner_text())
            element.click()
            return label
        if time.monotonic() >= until:
            raise RuntimeError('Nothing visible to click matching: ' + text)
        page.wait_for_timeout(200)


def choose_account_type(page, choice, opener=None):
    """Some firmware asks which kind of account before the credentials. The
    choice is part of an option label, or a position such as 2."""
    for select in page.locator('select:visible').all():
        labels = [o.inner_text().strip() for o in select.locator('option').all()]
        if choice.isdigit() and 1 <= int(choice) <= len(labels):
            select.select_option(index=int(choice) - 1)
            return labels[int(choice) - 1]
        hits = [i for i, label in enumerate(labels) if norm(choice) in norm(label)]
        if len(hits) == 1:
            select.select_option(index=hits[0])
            return labels[hits[0]]
    if choice.isdigit():
        raise RuntimeError('No login dropdown with a choice number ' + choice)
    # A custom dropdown is not a select. The option is only there once the list
    # is open, and the list may already be open, so try the option first.
    try:
        return click_choice(page, choice, 1500)
    except RuntimeError:
        if not opener:
            raise
    click_choice(page, opener)
    return click_choice(page, choice)


def navigate(page, url, username, password, account_type=None, account_open=None):
    page.goto(url, wait_until='domcontentloaded')
    try:
        click_text(page, r'^Sign\s*in(?:\s*to)?$', 3000)
    except RuntimeError:
        pass  # Some firmware opens the login form directly, or has an open session.
    if not page.locator('input[type=password]:visible').count() and not account_type:
        try:
            click_text(page, r'^Profile\s*server$', 3000)
        except RuntimeError:
            pass
    if account_type:
        # Chosen before the fields are read, since it can redraw the form.
        chosen = choose_account_type(page, account_type, account_open)
        # Printed only when it changes, so a controller pointing at a different
        # profile server stands out instead of scrolling past with the rest.
        if chosen != navigate.last_account_type:
            print('Account type:', chosen)
            navigate.last_account_type = chosen
    pw = page.locator('input[type=password]:visible')
    if pw.count():
        user = page.locator('input:visible:not([type=password]):not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio])')
        if pw.count() != 1 or user.count() != 1:
            raise RuntimeError('Login fields are ambiguous; use --setup to inspect this firmware')
        if origin(page.url) != origin(url):
            raise RuntimeError('Login redirected to a different origin; credentials were not entered')
        user.fill(username)
        pw.fill(password)
        click_text(page, r'^(?:Sign\s*in|Log\s*in|Login)$')
        pw.wait_for(state='hidden', timeout=15000)
    home = page.url
    page.goto(urljoin(url if url.endswith('/') else url + '/', IO_PATH), wait_until='domcontentloaded')
    if not showing_io_modules(page):
        # Firmware that does not route by address still walks the menus, from
        # wherever the session was after signing in rather than from the login.
        page.goto(home, wait_until='domcontentloaded')
        for label in ('Controller', 'Advanced IO', 'Cabinet Configuration', 'IO Modules'):
            click_text(page, '^' + re.escape(label) + '$')


navigate.last_account_type = ''


def showing_io_modules(page, timeout=6000):
    until = time.monotonic() + timeout / 1000
    while time.monotonic() < until:
        if any(frame.get_by_text(IO_MARKER).filter(visible=True).count() for frame in page.frames):
            return True
        page.wait_for_timeout(200)
    return False


def snapshot(page):
    """Every readable table in this browser session, keyed by position so one
    table can be followed between polls. Some firmware renders the IO screen
    inside an iframe, and manual navigation can land it in a second tab."""
    tables, unreadable = {}, 0
    for tab, other in enumerate(page.context.pages):
        if other.is_closed():
            continue
        for index, frame in enumerate(other.frames):
            try:
                found = frame.evaluate(TABLES_JS)
            except Exception:
                # A frame can disappear during navigation; retry on the next poll.
                unreadable += 1
                continue
            for table in found:
                tables[(tab, index, table['index'])] = table['rows']
    return tables, unreadable


def changed_cell(before, after):
    if len(before) != len(after):
        return 'row count went %d to %d' % (len(before), len(after))
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b:
            return 'row %d went %r to %r' % (i + 1, ' | '.join(a)[:60], ' | '.join(b)[:60])
    return 'contents changed'


def stable_tables(page, hold=2.0, budget=15.0):
    """Tables whose own rows stopped changing. Judging each table separately
    keeps a clock or a live status table elsewhere on the screen from blocking
    the module list, which no amount of waiting would have fixed."""
    seen, since, churn, unreadable = {}, {}, {}, 0
    until = time.monotonic() + budget
    while True:
        now = time.monotonic()
        tables, unreadable = snapshot(page)
        for key, rows in tables.items():
            if seen.get(key) != rows:
                if key in seen:
                    churn[key] = changed_cell(seen[key], rows)
                since[key] = now
        seen = tables
        ready = []  # The same list read two ways is one table, not an ambiguous pair.
        for key, rows in tables.items():
            if now - since[key] >= hold and all(rows != t['rows'] for t in ready):
                ready.append(dict(rows=rows))
        if ready:
            return ready
        if now >= until:
            if not tables:
                detail = 'no table with more than one visible row was found'
                if unreadable:
                    detail += '; %d frame(s) could not be read' % unreadable
            else:
                detail = '%d table(s) found, none held still for %gs (%s)' % (
                    len(tables), hold, next(iter(churn.values()), 'rows appeared or disappeared'))
            raise RuntimeError('No stable, readable IO module table: ' + detail)
        page.wait_for_timeout(250)


def diagnose(page, path):
    """Say what the screen actually contains when no table can be read."""
    report = []
    for other in page.context.pages:
        if other.is_closed():
            continue
        frames = []
        for frame in other.frames:
            try:
                frames.append(frame.evaluate(DIAGNOSE_JS))
            except Exception as exc:
                frames.append(dict(error=type(exc).__name__))
        report.append(frames)
    print('\nWhat this browser session contains right now:')
    for tab, frames in enumerate(report):
        print('Tab %d' % (tab + 1))
        for i, frame in enumerate(frames):
            if 'error' in frame:
                print('  frame %d could not be read (%s)' % (i + 1, frame['error']))
                continue
            print('  frame %d %s  %s' % (i + 1, frame['url'], frame['title']))
            print('    ' + ', '.join('%s=%s' % kv for kv in frame['counts'].items()))
            for grid in frame['grids']:
                print('    %s %d: visible=%s rows=%d visible_rows=%d :: %s'
                      % (grid['tag'], grid['index'], grid['visible'], grid['rows'],
                         grid['visibleRows'], grid['text']))
            for hit in frame['hits']:
                print('    text: ' + hit)
            for control in frame['controls']:
                print('    ' + control)
            if not frame['grids']:
                print('    labels: ' + ' | '.join(frame['labels']))
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Full report:', path)
    print('It holds page structure and visible text from this screen, no password.')


def describe(page, row, path):
    """Open a controller and say what is on whatever screen you put up."""
    page.goto(row['maxtime_url'], wait_until='domcontentloaded')
    print('\nIn the opened browser, bring up the screen you want described.')
    while input('Press Enter to describe it, or type QUIT: ').strip().upper() != 'QUIT':
        diagnose(page, path)


def setup(page, row, path):
    page.goto(row['maxtime_url'], wait_until='domcontentloaded')
    print('\nIn the opened browser, sign in and open Controller > Advanced IO >')
    print('Cabinet Configuration > IO Modules. Do not change configuration.')
    tables = None
    while tables is None:
        input('When the complete module list is visible, press Enter here: ')
        try:
            tables = stable_tables(page)
        except RuntimeError as exc:
            print(str(exc))
            diagnose(page, path.with_name('biu-diagnostic.json'))
            if input('Press Enter to read the page again, or type QUIT: ').strip().upper() == 'QUIT':
                raise ValueError('Setup stopped; no profile saved')
    for i, table in enumerate(tables):
        print('\nTable', i + 1)
        for cells in table['rows']:
            print(' | '.join(cells))
    choice = int(input('\nWhich table is the IO module list? Number: ')) - 1
    if not 0 <= choice < len(tables):
        raise ValueError('Invalid table number')
    table = tables[choice]
    headers = table['rows'][0]
    for i, header in enumerate(headers):
        print(i + 1, header)
    module_col = int(input('Module NUMBER column number: ')) - 1
    type_col = int(input('Module TYPE column number: ')) - 1
    if not (0 <= module_col < len(headers) and 0 <= type_col < len(headers)) or module_col == type_col:
        raise ValueError('Invalid columns')
    print('Confirm this table includes ALL configured modules, with no pagination,')
    print('collapsed rows, filters, or virtual scrolling hiding other modules.')
    if input('Type COMPLETE to confirm, otherwise press Enter to cancel: ') != 'COMPLETE':
        raise ValueError('Setup cancelled; no profile saved')
    profile = dict(headers=headers, module_column=module_col, type_column=type_col,
                   module_header=headers[module_col], type_header=headers[type_col],
                   complete_table_confirmed=True, schema=SCHEMA,
                   observed_non_biu_types=sorted({norm(r[type_col]) for r in table['rows'][1:]
                                                 if len(r) == len(headers) and 'biu' not in norm(r[type_col])}))
    answer, reason = classify(table['rows'], profile)
    print('Proposed result:', answer, '-', reason)
    if answer == 'unknown':
        raise ValueError('This layout needs an adapter. Keep the displayed table details for follow-up.')
    if input('Does that match your manual check? Type AGREE to save: ') != 'AGREE':
        raise ValueError('Setup cancelled; no profile saved')
    path.write_text(json.dumps(profile, indent=2), encoding='utf-8')
    print('Profile saved. Next, run without --setup to test automatic login/navigation.')


def inspect_modules(page, profile):
    if page.locator('input[type=password]:visible').count():
        raise RuntimeError('Still on login page')
    if not any(frame.get_by_text(IO_MARKER).filter(visible=True).count() for frame in page.frames):
        raise RuntimeError('IO Modules page marker missing')
    tables = stable_tables(page)
    matches = [t for t in tables if resolve_columns(t['rows'][0], profile)]
    if len(matches) != 1:
        # Name what was on screen. "Missing or ambiguous" alone says nothing
        # about which of the two happened, or what the headers actually were.
        want = ' | '.join(column_headings(profile))
        seen = '; '.join(' | '.join(t['rows'][0])[:80] for t in tables) or 'no table at all'
        raise RuntimeError(
            (f'{len(matches)} tables carry both calibrated headings' if matches
             else 'No table on the page carries both calibrated headings')
            + f'. Calibrated: {want}. Found: {seen}')
    # Any visible pagination control makes an absence result unsafe.
    if any(frame.get_by_role('button', name=re.compile(r'^(?:next|next page|load more)$', re.I)).filter(visible=True).count()
           for frame in page.frames):
        raise RuntimeError('Pagination present; table may be incomplete')
    return matches[0]['rows']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('csv', type=Path)
    ap.add_argument('--setup', action='store_true', help='Calibrate the full module table once, manually')
    ap.add_argument('--describe', action='store_true', help='Open one controller and report what is on screen')
    ap.add_argument('--account-type', help='Login dropdown choice: part of an option label, or a position such as 2')
    ap.add_argument('--account-open', help='Text of the closed dropdown, clicked first to open the list')
    ap.add_argument('--profile', type=Path, default=Path('biu-profile.json'))
    ap.add_argument('--out', type=Path, default=Path('biu-results'))
    ap.add_argument('--only', help='Signal IDs, comma separated')
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--limit', type=int, default=1, help='Controllers to check (default: 1)')
    group.add_argument('--all', action='store_true', help='Process the whole exported worklist')
    ap.add_argument('--browser', choices=['msedge', 'chrome', 'chromium'], default='msedge')
    ap.add_argument('--delay', type=float, default=3, help='Seconds between controllers')
    ap.add_argument('--stop-after', type=int, default=3,
                    help='Stop after this many login failures in a row (default: 3)')
    args = ap.parse_args()
    if args.limit < 1 or args.delay < 0 or args.stop_after < 1:
        ap.error('limit and stop-after must be positive and delay nonnegative')
    worklist = read_worklist(args.csv)
    rows = worklist
    if args.only:
        wanted = [i.strip() for i in args.only.split(',') if i.strip()]
        rows = [r for r in rows if r['id'] in wanted]
    if not args.all and not args.only:
        rows = rows[:args.limit]
    if not rows:
        available = ', '.join(r['id'] for r in worklist)
        ap.error(f"No matching controller ID {args.only!r} in the exported worklist. "
                 f"Available IDs: {available}")
    from playwright.sync_api import sync_playwright
    manual = args.setup or args.describe
    profile = None
    if not manual:
        profile = json.loads(args.profile.read_text(encoding='utf-8'))
        if profile.get('schema') != SCHEMA:
            raise ValueError('Unsupported profile; run --setup')
    username = '' if manual else input('Username (kept in memory): ')
    password = '' if manual else getpass('Password (hidden, never saved): ')
    args.out.mkdir(parents=True, exist_ok=True)
    run = args.out / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run.mkdir()
    results = []
    refused = 0          # Consecutive login failures, not the total.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, **({} if args.browser == 'chromium' else {'channel': args.browser}))
        try:
            for i, row in enumerate(rows):
                context = browser.new_context(accept_downloads=False)
                page = context.new_page()
                page.set_default_timeout(15000)
                if args.describe:
                    describe(page, row, args.profile.with_name('biu-diagnostic.json'))
                    return 0
                if args.setup:
                    setup(page, row, args.profile)
                    return 0
                record = dict(id=row['id'], maxtime_url=row['maxtime_url'], biu='unknown',
                              checked_at=datetime.now(timezone.utc).isoformat(), evidence=[], reason='')
                login_failed = False
                try:
                    navigate(page, row['maxtime_url'], username, password, args.account_type, args.account_open)
                    if origin(page.url) != origin(row['maxtime_url']):
                        raise RuntimeError('Controller redirected to a different origin')
                    evidence = inspect_modules(page, profile)
                    record['evidence'] = evidence
                    record['biu'], record['reason'] = classify(evidence, profile)
                    # Capture only after successful navigation; never screenshot a login form.
                    page.screenshot(path=str(run / (row['id'] + '.png')), full_page=True)
                except Exception as exc:
                    # No exception bodies, DOM dumps, cookies, URLs with tokens, or credentials in logs.
                    try:
                        login_failed = not page.is_closed() and bool(page.locator('input[type=password]:visible').count())
                    except Exception:
                        login_failed = True  # A lost browser session should also stop the batch.
                    if not login_failed:
                        # Past the login and still failed, so the screen itself is
                        # the evidence. Same rule: never capture a login form.
                        try:
                            page.screenshot(path=str(run / (row['id'] + '-failed.png')), full_page=True)
                        except Exception:
                            pass
                    record['biu'] = 'unknown'
                    record['reason'] = str(exc) if type(exc) is RuntimeError else type(exc).__name__ + ': login, navigation or read failed'
                finally:
                    context.close()
                results.append(record)
                payload = dict(schema=SCHEMA, results=results)
                temp = run / 'results.tmp'
                temp.write_text(json.dumps(payload, indent=2), encoding='utf-8')
                temp.replace(run / 'results.json')
                print(f"{i+1}/{len(rows)} {row['id']}: {record['biu']} — {record['reason']}")
                refused = refused + 1 if login_failed else 0
                if refused >= args.stop_after:
                    print(f'Login did not complete on {refused} controllers in a row. '
                          'Stopping; verify the login before trying again.')
                    break
                if login_failed:
                    print('  Login did not complete here. Carrying on; this ID stays in the '
                          'next worklist.')
                if i + 1 < len(rows):
                    time.sleep(args.delay)
        finally:
            browser.close()
    print('Import into box.html:', run / 'results.json')
    print('Review the evidence and screenshots before applying results. Box downloads stay manual.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nStopped. Results already written remain available.')
        raise SystemExit(130)
    except (ValueError, FileNotFoundError, ImportError) as exc:
        print(str(exc))
        print('See BIU_CHECK.md for setup and installation.')
        raise SystemExit(2)
