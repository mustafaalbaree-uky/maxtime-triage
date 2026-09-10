#!/usr/bin/env python3
"""Look at a clickbox Properties screen and write down what is on it.

This run changes nothing on the device. It presses no Save, no Apply and no
Export, and it types into no field. It is the calibration half of the clickbox
tool: the device UI does not exist on the machine this was written on, so the
fill and export step is written against what this reports rather than guessed.

See CLICKBOX.md.

    py fetch_clickbox.py clickbox_worklist.csv --describe --only 4380
"""
import argparse
import csv
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

SCHEMA = 'maxtime-clickbox-v1'
CLICKBOX_PORT = 57150
# What the fill step will be looking for, once it exists.
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
 return {
   route: cut((location.hash || location.pathname).split('?')[0], 80),  // names the screen; the host is left out on purpose
   title: cut(document.title, 80),
   counts: {input: document.querySelectorAll('input').length,
            textarea: document.querySelectorAll('textarea').length,
            select: document.querySelectorAll('select').length,
            button: document.querySelectorAll('button').length,
            table: document.querySelectorAll('table').length,
            frame: document.querySelectorAll('iframe,frame').length},
   fields, buttons, tabs,
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


def describe(page, row, path):
    page.goto(row['clickbox_url'], wait_until='domcontentloaded')
    print('\nThe browser has opened %s at port %d.' % (row['id'], CLICKBOX_PORT))
    print('Sign in if it asks, then open the Properties tab. Change nothing.')
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('csv', type=Path, help='clickbox_worklist.csv from box.html')
    ap.add_argument('--describe', action='store_true',
                    help='Open one clickbox and report what the Properties screen contains')
    ap.add_argument('--only', help='Signal ID to open')
    ap.add_argument('--out', type=Path, default=Path('clickbox-diagnostic.json'))
    ap.add_argument('--browser', choices=['msedge', 'chrome', 'chromium'], default='msedge')
    args = ap.parse_args()

    rows = read_worklist(args.csv)
    if not args.describe:
        print('Only --describe exists so far. Filling, saving and exporting are')
        print('written once this has reported what the Properties screen looks like.')
        print('%d %s in the worklist. Try:'
              % (len(rows), 'signal' if len(rows) == 1 else 'signals'))
        print('  py %s %s --describe --only %s' % (Path(sys.argv[0]).name, args.csv, rows[0]['id']))
        return 2
    if args.only:
        rows = [r for r in rows if r['id'] == args.only.strip()]
    if not rows:
        print('That ID is not in the worklist.')
        return 2
    row = rows[0]
    print('Signal %s. The proposal from the sheets is:' % row['id'])
    for key, word in WANTED.items():
        print('  %-12s %s' % (word, row[key]))

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            **({} if args.browser == 'chromium' else {'channel': args.browser}))
        context = browser.new_context(accept_downloads=False)
        try:
            describe(context.new_page(), row, args.out)
        finally:
            context.close()
            browser.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
