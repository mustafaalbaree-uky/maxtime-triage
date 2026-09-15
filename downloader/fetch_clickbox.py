#!/usr/bin/env python3
"""Fill a clickbox's Name, Location and Description, then export its configuration.

Every device asks first. The three values come from the sheets by way of
box.html, and nothing is typed until you answer y for that signal. A field
already holding something different is called out and needs its own y. No
control other than those three and Save Device Properties is ever touched.

    py fetch_clickbox.py clickbox_worklist.csv                 one clickbox
    py fetch_clickbox.py clickbox_worklist.csv --only 4030     one named signal
    py fetch_clickbox.py clickbox_worklist.csv --all           the whole worklist

--describe changes nothing at all: it opens one device and reports what its
Properties screen contains. That is how this was written, the device UI not
being available on the machine it came from. See CLICKBOX.md.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

SCHEMA = 'maxtime-clickbox-v1'
CLICKBOX_PORT = 57150
# Under --out-dir: the configurations on their own, so the folder can be
# selected whole and dragged into SharePoint without picking around the logs.
FILES_SUBDIR = 'files'
RUNS_SUBDIR = 'runs'
# The three fields, and the words their labels are found by.
WANTED = {'name': 'Name', 'location': 'Location', 'description': 'Description'}
SAVE_TEXT = re.compile(r'\bsave\b', re.I)
SAVE_EXACT = re.compile(r'save\s+device\s+properties', re.I)
EXPORT_TEXT = re.compile(r'\bexport\b', re.I)
EXPORT_EXACT = re.compile(r'export\s+configuration', re.I)

# Every visible control, its label wherever the label is hiding, and what it
# currently holds. Passwords are named and never read. The host is not included:
# this file is meant to be sendable, and the addresses are not.
DESCRIBE_JS = r"""() => {
 const cut = (s, n) => { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n) + '...' : s; };
 const visible = e => !!(e.getClientRects().length);
 const cls = e => cut(typeof e.className === 'string' ? e.className : '', 40);
 // A form field's label lives in one of five places depending on who wrote the
 // page, so collect all of them and let the reader decide which one is real.
 const labelsOf = e => {
   const out = [];
   if (e.id) for (const l of document.querySelectorAll('label[for="' + CSS.escape(e.id) + '"]')) out.push(cut(l.textContent, 60));
   const wrap = e.closest('label');
   if (wrap) out.push(cut(wrap.textContent, 60));
   for (const a of ['aria-label', 'placeholder', 'title', 'name']) {
     const v = e.getAttribute(a);
     if (v) out.push(cut(v, 60));
   }
   const by = e.getAttribute('aria-labelledby');
   if (by) for (const id of by.split(/\s+/)) {
     const t = document.getElementById(id);
     if (t) out.push(cut(t.textContent, 60));
   }
   // A table row or a flex row: the text sitting immediately before the field.
   const cell = e.closest('td,th,[role=gridcell]');
   if (cell && cell.previousElementSibling) out.push(cut(cell.previousElementSibling.textContent, 60));
   let n = e.previousElementSibling;
   while (n && !cut(n.textContent, 60)) n = n.previousElementSibling;
   if (n) out.push(cut(n.textContent, 60));
   const parentText = e.parentElement ? cut(e.parentElement.textContent, 60) : '';
   if (parentText) out.push(parentText);
   return [...new Set(out.filter(Boolean))];
 };
 const path = e => {
   const bits = [];
   for (let n = e; n && n.nodeType === 1 && bits.length < 5; n = n.parentElement)
     bits.unshift(n.tagName.toLowerCase() + (n.id ? '#' + n.id : ''));
   return bits.join('>');
 };
 const fields = Array.from(document.querySelectorAll('input,textarea,select')).filter(visible).slice(0, 60).map(e => {
   const tag = e.tagName.toLowerCase();
   const type = tag === 'input' ? (e.type || 'text').toLowerCase() : tag;
   const secret = type === 'password' || type === 'hidden';
   return {
     tag, type, id: cut(e.id, 40), name: cut(e.getAttribute('name'), 40),
     cls: cls(e), path: path(e), labels: labelsOf(e),
     readonly: !!(e.readOnly || e.disabled),
     maxlength: e.maxLength > 0 ? e.maxLength : null,
     value: secret ? null : (tag === 'select'
       ? cut(Array.from(e.selectedOptions).map(o => o.textContent).join(' '), 80)
       : cut(e.value, 120)),
     options: tag === 'select' ? Array.from(e.options).slice(0, 20).map(o => cut(o.textContent, 40)) : null,
     secret,
   };
 });
 // Plain anchors count. On the Click 656 the whole footer nav, Export
 // Configuration included, is <a> text with no role and no button styling.
 const buttons = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a,[role=button]')).filter(visible).slice(0, 60).map(e => {
   let href = '';
   try { href = e.tagName === 'A' && e.href ? new URL(e.href).pathname + new URL(e.href).hash : ''; } catch (err) { href = ''; }
   return {
     tag: e.tagName.toLowerCase(), id: cut(e.id, 40), cls: cls(e),
     text: cut(e.value || e.textContent || e.getAttribute('aria-label'), 60),
     href: cut(href, 60), disabled: !!e.disabled,
   };
 });
 const tabs = Array.from(document.querySelectorAll('[role=tab],.tab,.nav-link,li>a')).filter(visible).slice(0, 30)
   .map(e => cut(e.textContent, 40)).filter(Boolean);
 // The Click 656's top tabs are not links and carry no role, so nothing above
 // finds them. What they do have is a pointer cursor.
 const clickables = Array.from(document.querySelectorAll('body *')).filter(e => {
   if (!visible(e) || e.children.length > 1) return false;
   const t = cut(e.textContent, 40);
   if (!t || t.length > 40) return false;
   try { return getComputedStyle(e).cursor === 'pointer'; } catch (err) { return false; }
 }).slice(0, 30).map(e => ({tag: e.tagName.toLowerCase(), id: cut(e.id, 40),
   cls: cls(e), text: cut(e.textContent, 40)}));
 return {
   route: cut((location.hash || location.pathname).split('?')[0], 80),  // names the screen; the host is left out on purpose
   title: cut(document.title, 80),
   counts: {input: document.querySelectorAll('input').length,
            textarea: document.querySelectorAll('textarea').length,
            select: document.querySelectorAll('select').length,
            button: document.querySelectorAll('button').length,
            table: document.querySelectorAll('table').length,
            frame: document.querySelectorAll('iframe,frame').length},
   fields, buttons, tabs, clickables,
   text: Array.from(document.querySelectorAll('body *')).filter(e => !e.children.length && visible(e) &&
     (e.textContent || '').trim() && (e.textContent || '').trim().length <= 80).slice(0, 40).map(e => cut(e.textContent, 80)),
 };
}"""


def clickbox_origin(url):
    """The clickbox, not MaxTime. Credentials in the URL are refused."""
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Expected an HTTP(S) clickbox URL without credentials')
    if (p.port or 80) != CLICKBOX_PORT:
        raise ValueError('Expected the clickbox URL on port %d, not the MaxTime URL' % CLICKBOX_PORT)
    return (p.scheme.lower(), p.hostname.lower(), p.port)


def read_worklist(path):
    """The clickbox worklist exported from box.html."""
    want = {'id', 'clickbox_url', 'name', 'location', 'description'}
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not want.issubset(reader.fieldnames or []):
            raise ValueError('Export the clickbox worklist from box.html')
        rows = list(reader)
    seen = set()
    for r in rows:
        for k in want:
            r[k] = (r[k] or '').strip()
        if not re.fullmatch(r'[4-9]\d{3}', r['id']) or r['id'] in seen:
            raise ValueError('Worklist contains an invalid or duplicate ID')
        if not r['name'] or not r['location'] or not r['description']:
            raise ValueError('Signal %s has no proposed properties; fix the sheets first' % r['id'])
        seen.add(r['id'])
        clickbox_origin(r['clickbox_url'])
    return rows


def guess(report):
    """Which control on this screen is each of the three fields, and which
    button saves and which exports. A guess, printed so it can be judged."""
    found, used = {}, set()
    for key, word in WANTED.items():
        best = None
        for i, f in enumerate(report['fields']):
            # Only somewhere text can be typed. The Save button is an
            # input[type=button] and turns up in this list too.
            if i in used or f['secret'] or f['readonly']:
                continue
            if f['type'] not in ('text', 'search', 'textarea'):
                continue
            hits = [t for t in f['labels'] + [f['id'], f['name']] if t]
            exact = any(re.fullmatch(word, t.strip(' :*'), re.I) for t in hits)
            loose = any(re.search(r'\b%s\b' % word, t, re.I) for t in hits)
            if not exact and not loose:
                continue
            score = (2 if exact else 1, -i)
            if best is None or score > best[0]:
                best = (score, i, f)
        if best:
            used.add(best[1])
            found[key] = best[2]
    def pick(exact, loose):
        hits = [b for b in report['buttons'] if loose.search(b['text'] or '')]
        return next((b for b in hits if exact.fullmatch((b['text'] or '').strip())), None) \
            or (hits[0] if hits else None)
    buttons = {'save': pick(SAVE_EXACT, SAVE_TEXT), 'export': pick(EXPORT_EXACT, EXPORT_TEXT)}
    return found, buttons


def show(report, row):
    print('\nScreen: %s  %s' % (report['route'], report['title']))
    print('  ' + ', '.join('%s=%s' % kv for kv in report['counts'].items()))
    if report['tabs']:
        print('  tabs: ' + ' | '.join(report['tabs'][:12]))
    print('\nFields on screen:')
    for i, f in enumerate(report['fields']):
        print('  %2d %-9s %-18s labels=%s' % (i, f['type'], f['id'] or f['name'] or f['cls'],
                                              ' / '.join(f['labels'][:3]) or 'none'))
        if not f['secret']:
            print('       currently: %s' % (repr(f['value']) if f['value'] else 'empty'))
    print('\nButtons and links on screen:')
    for b in report['buttons']:
        print('  %-28s %-8s %s%s' % (b['text'] or b['id'] or b['cls'], b['tag'],
                                     b.get('href') or '', ' disabled' if b['disabled'] else ''))
    if report.get('clickables'):
        # The top tabs are here and nowhere else: no link, no role, just a
        # pointer cursor. This is what says how to reach Properties.
        print('\nOther things that can be clicked:')
        for c in report['clickables']:
            print('  %-28s %-8s %s' % (c['text'], c['tag'], c['cls']))

    found, buttons = guess(report)
    print('\nBest guess at what the fill step needs:')
    for key, word in WANTED.items():
        f = found.get(key)
        if not f:
            print('  %-12s not found on this screen' % word)
            continue
        cur = repr(f['value']) if f['value'] else 'empty'
        want = row[key] if row else None
        verdict = ''
        if want is not None:
            verdict = ' matches the proposal' if (f['value'] or '').strip() == want else (
                ' EMPTY, would be filled with %r' % want if not (f['value'] or '').strip()
                else ' DIFFERS from the proposal %r' % want)
        print('  %-12s field %s, currently %s%s'
              % (word, f['id'] or f['name'] or f['path'], cur, verdict))
    for key, label in (('save', 'Save Device Properties'), ('export', 'Export Configuration')):
        b = buttons[key]
        print('  %-12s %s' % (label, ('%s %r %s' % (b['tag'], b['text'], b.get('href') or ''))
                              if b else 'not found on this screen'))
    return found, buttons


def describe(page, row, path, timeout_ms=20000):
    frame, _, found, _, why = open_properties(page, row['clickbox_url'], timeout_ms)
    print('\nThe browser has opened %s at port %d.' % (row['id'], CLICKBOX_PORT))
    if frame and len(found) == 3:
        print('It found the Properties screen on its own.')
    else:
        print('It could not get to Properties by itself: %s.' % why)
        print('Open that tab by hand if the device is up.')
    print('This script types nothing and presses no Save, Apply or Export.')
    reports = []
    while input('\nPress Enter to describe the screen, or type QUIT: ').strip().upper() != 'QUIT':
        frames = []
        for frame in page.frames:
            try:
                frames.append(frame.evaluate(DESCRIBE_JS))
            except Exception as exc:
                frames.append(dict(error=type(exc).__name__))
        for i, report in enumerate(frames):
            if 'error' in report:
                print('  frame %d could not be read (%s)' % (i + 1, report['error']))
                continue
            if len(frames) > 1:
                print('\n--- frame %d of %d ---' % (i + 1, len(frames)))
            show(report, row)
        reports.append(frames)
        path.write_text(json.dumps({'schema': SCHEMA, 'screens': reports}, indent=2),
                        encoding='utf-8')
        print('\nWritten to %s' % path)
        print('It holds the screen structure, the field labels and what the three')
        print('properties currently say. No password, no address, no cookies.')


def selector(f):
    """A way back to a control the report found."""
    if f.get('id'):
        return '#' + re.sub(r'([^\w-])', r'\\\1', f['id'])
    if f.get('name'):                       # buttons carry no name; fields do
        return '%s[name="%s"]' % (f['tag'], f['name'])
    return ''


def read_screen(page):
    """The frame holding the three properties, and what it reported."""
    for frame in page.frames:
        try:
            report = frame.evaluate(DESCRIBE_JS)
        except Exception:
            continue
        found, buttons = guess(report)
        if len(found) == 3 and all(selector(f) for f in found.values()):
            return frame, report, found, buttons
    return None, None, {}, {}


PROPERTIES_TAB = re.compile(r'^\s*propert(y|ies)\s*$', re.I)


def nav_error(exc):
    """Why a page did not open, short enough to sit in a run record.

    A clickbox that is switched off, on a network the work computer cannot see,
    or simply slow all arrive here, and they read alike from outside. What the
    record has to carry is that nothing was reached, not which of those it was.
    """
    text = str(exc).splitlines()[0] if str(exc).strip() else type(exc).__name__
    hit = re.search(r'net::(\w+)', text)
    if hit:
        return hit.group(1)
    if 'Timeout' in text or 'timeout' in text:
        return 'timed out'
    return text[:120]


def open_properties(page, url, timeout_ms):
    """Get to the Properties screen.

    The Click 656 lands on Health, and its top tabs are neither links nor
    anything carrying a role, so there is no path to navigate to and no
    selector to rely on. The word itself is what gets clicked. `^properties$`
    is deliberately anchored: 'Device Properties' is the heading and
    'Save Device Properties' is the save control, and neither may be hit.
    """
    reached, failed = False, ''
    for path in ('', '/device.asp'):
        try:
            page.goto(url.rstrip('/') + path, wait_until='domcontentloaded',
                      timeout=timeout_ms)
        except Exception as exc:
            failed = failed or nav_error(exc)
            continue
        reached = True
        try:
            page.wait_for_load_state('networkidle', timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        got = read_screen(page)
        if got[0]:
            return got + ('',)
        for frame in page.frames:
            try:
                frame.get_by_text(PROPERTIES_TAB).first.click(timeout=4000)
            except Exception:
                continue
            frame.wait_for_timeout(1200)
            got = read_screen(page)
            if got[0]:
                return got + ('',)
    why = ('reached the device, but no Name, Location and Description on any screen'
           if reached else
           'the clickbox never answered at port %d (%s)' % (CLICKBOX_PORT, failed))
    return None, None, {}, {}, why


def plan_row(found, row):
    """Per field: leave it, fill it, or replace what is there. Replacing is
    never decided here, only proposed."""
    out = {}
    for key in WANTED:
        current = (found[key]['value'] or '').strip()
        want = row[key]
        out[key] = dict(current=current, want=want,
                        action='ok' if current == want else ('fill' if not current else 'replace'))
    return out


def confirm(row, plan):
    """Nothing is typed into a device without this returning True."""
    replacing = [k for k, p in plan.items() if p['action'] == 'replace']
    filling = [k for k, p in plan.items() if p['action'] == 'fill']
    print('\n' + '=' * 68)
    print('Signal %s' % row['id'])
    if replacing:
        print('!! %d field%s already filled in and DIFFERENT from the sheets.'
              % (len(replacing), '' if len(replacing) == 1 else 's'))
    for key, word in WANTED.items():
        p = plan[key]
        if p['action'] == 'ok':
            print('  %-12s %-34s already correct' % (word, p['current']))
        elif p['action'] == 'fill':
            print('  %-12s %-34s <- would fill in' % (word, '(empty)'))
            print('  %-12s %s' % ('', p['want']))
        else:
            print('  !!%-10s device says %r' % (word, p['current']))
            print('  %-12s sheets say  %r' % ('', p['want']))
    if not replacing and not filling:
        print('  Nothing to type. Exporting only.')
    print('=' * 68)
    prompt = 'Type y to %s, n to skip this signal, q to stop: ' % (
        'export' if not (replacing or filling) else
        'REPLACE and save, then export' if replacing else 'fill in, save, then export')
    while True:
        answer = input(prompt).strip().lower()
        if answer in ('y', 'n', 'q'):
            return answer
        print('  y, n or q.')


def fill_and_save(frame, found, plan, buttons):
    """Type the three, press Save Device Properties, then read them back.
    No other control on the screen is touched."""
    typed = {}
    for key in WANTED:
        if plan[key]['action'] == 'ok':
            continue
        frame.fill(selector(found[key]), plan[key]['want'])
        typed[key] = plan[key]['want']
    if typed:
        frame.click(selector(buttons['save']) or 'text="%s"' % buttons['save']['text'])
        frame.wait_for_timeout(1500)
    after = {}
    for key in WANTED:
        try:
            after[key] = (frame.input_value(selector(found[key])) or '').strip()
        except Exception:
            after[key] = None
    return typed, after


def export_config(page, frame, buttons, out_dir, signal_id):
    """Click Export Configuration and keep whatever it sends. The link carries
    no usable href on this firmware, so the click is the only way in."""
    b = buttons.get('export')
    if not b:
        return None, 'no Export Configuration on this screen'
    target = selector(b) or 'a:has-text("%s")' % b['text']
    try:
        with page.expect_download(timeout=45000) as caught:
            frame.click(target)
        download = caught.value
    except Exception as exc:
        return None, 'no download arrived (%s)' % type(exc).__name__
    out_dir.mkdir(parents=True, exist_ok=True)
    name = download.suggested_filename or ('%s.cbx' % signal_id)
    path = out_dir / name
    n = 1
    while path.exists():                    # the device names these, so two runs collide
        path = out_dir / ('%s (%d)%s' % (Path(name).stem, n, Path(name).suffix))
        n += 1
    download.save_as(path)
    return path, ''


def process_one(context, row, args, run):
    """One clickbox. Returns the record. Raises nothing the batch cannot survive."""
    rec = dict(id=row['id'], at=run, typed={}, before={}, after={},
               exported='', skipped='', error='', note='')
    page = context.new_page()
    try:
        frame, report, found, buttons, why = open_properties(
            page, row['clickbox_url'], int(args.timeout * 1000))
        if not frame:
            rec['error'] = why
            print('  %s' % why)
            return rec
        if not buttons.get('save'):
            rec['error'] = 'no Save Device Properties on this screen'
            return rec
        plan = plan_row(found, row)
        rec['before'] = {k: plan[k]['current'] for k in WANTED}
        answer = confirm(row, plan)
        if answer == 'q':
            rec['skipped'] = 'stopped here'
            return rec
        if answer == 'n':
            rec['skipped'] = 'skipped'
            return rec
        typed, after = fill_and_save(frame, found, plan, buttons)
        rec['typed'], rec['after'] = typed, after
        wrong = [WANTED[k] for k in typed if after.get(k) != typed[k]]
        if wrong:
            rec['error'] = 'did not save: ' + ', '.join(wrong)
            print('  The device still does not show %s. Not exporting.' % ', '.join(wrong))
            return rec
        # What the row note should say, when something was overwritten.
        changed = ['%s was %r, now %r' % (WANTED[k], plan[k]['current'], typed[k])
                   for k in typed if plan[k]['action'] == 'replace']
        rec['note'] = '; '.join(changed)
        path, why = export_config(page, frame, buttons,
                                  args.out_dir / FILES_SUBDIR, row['id'])
        if path:
            rec['exported'] = str(path)
            print('  Saved %s' % path)
        else:
            rec['error'] = why
            print('  %s' % why)
        return rec
    finally:
        page.close()


def write_results(args, run, records):
    runs = args.out_dir / RUNS_SUBDIR
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / ('clickbox-run-%s.json' % run)
    path.write_text(json.dumps({'schema': SCHEMA, 'run': run, 'results': records}, indent=2),
                    encoding='utf-8')
    return path


def summarise(records, path):
    done = [r for r in records if r['exported']]
    notes = [r for r in records if r['note']]
    print('\n' + '=' * 68)
    print('%d of %d exported.' % (len(done), len(records)))
    for r in records:
        state = ('exported' if r['exported'] else r['skipped'] or r['error'] or 'nothing happened')
        print('  %-6s %s' % (r['id'], state))
    if notes:
        print('\nOverwritten, worth putting in the row note in box.html:')
        for r in notes:
            print('  %-6s %s' % (r['id'], r['note']))
    dead = [r for r in records if 'never answered' in r['error']]
    if dead:
        print('\nNo answer at port %d. To try these again:' % CLICKBOX_PORT)
        print('  --only %s' % ','.join(r['id'] for r in dead))
    print('\nRun written to %s' % path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('csv', type=Path, help='clickbox_worklist.csv from box.html')
    ap.add_argument('--describe', action='store_true',
                    help='Open one clickbox and report what the Properties screen contains')
    ap.add_argument('--only', help='Signal IDs, comma separated')
    ap.add_argument('--out', type=Path, default=Path('clickbox-diagnostic.json'),
                    help='Where --describe writes its report')
    ap.add_argument('--out-dir', type=Path, default=Path('clickbox-exports'),
                    help='Holds %s (the configurations) and %s (what each run did)'
                         % (FILES_SUBDIR, RUNS_SUBDIR))
    ap.add_argument('--browser', choices=['msedge', 'chrome', 'chromium'], default='msedge')
    ap.add_argument('--timeout', type=float, default=20,
                    help='Seconds to wait for a clickbox to answer (default: 20)')
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--limit', type=int, default=1,
                       help='Clickboxes to work through (default: 1)')
    group.add_argument('--all', action='store_true', help='The whole worklist')
    args = ap.parse_args()

    rows = read_worklist(args.csv)
    if args.only:
        wanted = {x.strip() for x in args.only.split(',') if x.strip()}
        rows = [r for r in rows if r['id'] in wanted]
    if not rows:
        print('Nothing in the worklist matches.')
        return 2
    if not args.describe and not args.all:
        rows = rows[:max(1, args.limit)]

    from playwright.sync_api import sync_playwright
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            **({} if args.browser == 'chromium' else {'channel': args.browser}))
        # Downloads must be accepted or Export Configuration silently does nothing.
        context = browser.new_context(accept_downloads=not args.describe)
        try:
            if args.describe:
                row = rows[0]
                print('Signal %s. The proposal from the sheets is:' % row['id'])
                for key, word in WANTED.items():
                    print('  %-12s %s' % (word, row[key]))
                describe(context.new_page(), row, args.out, int(args.timeout * 1000))
                return 0
            print('%d clickbox%s. Each one asks before anything is typed.'
                  % (len(rows), '' if len(rows) == 1 else 'es'))
            print('Configurations land in %s' % (args.out_dir / FILES_SUBDIR).resolve())
            print('The record of the run goes in %s' % (args.out_dir / RUNS_SUBDIR).resolve())
            records = []
            for row in rows:
                rec = process_one(context, row, args, run)
                records.append(rec)
                if rec['skipped'] == 'stopped here':
                    break
        finally:
            context.close()
            browser.close()
    summarise(records, write_results(args, run, records))
    return 0


if __name__ == '__main__':
    sys.exit(main())
