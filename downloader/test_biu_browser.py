"""Offline browser integration tests; requires Playwright and Chromium.
Run: python -m unittest discover -s downloader -p test_biu_browser.py
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from playwright.sync_api import sync_playwright

from check_biu import (navigate, inspect_modules, classify, stable_tables, diagnose,
                       choose_account_type, run_batch, SCHEMA)
from test_biu import PROFILE

LOGIN = '''<!doctype html><body>
<button onclick="this.outerHTML='<button onclick=login()>Profile server</button>'">Sign into</button>
<script>
function login() { document.body.innerHTML = `<input id=user><input id=pw type=password>
<button onclick="location.search='?in=1'">Sign in</button>`; }
</script></body>'''

# Signing in leaves a session, so the menu walk starts from wherever the
# controller left the browser rather than from a fresh login page.
MENU = '''<!doctype html><body><button onclick=controller()>Controller</button>
<script>
function controller() { document.body.innerHTML='<select onchange=advanced()><option>Choose menu</option><option>Advanced IO</option></select>'; }
function advanced() { document.body.innerHTML='<button onclick=cabinet()>Cabinet Configuration</button>'; }
function cabinet() { document.body.innerHTML='<button onclick=modules()>IO Modules</button>'; }
function modules() { document.body.innerHTML=`<h1>IO Modules</h1>
<table><tr><th>Module</th><th>Type</th></tr>
<tr><td>1</td><td><select><option selected>SIU</option><option>TS2 DR1 BIU</option></select></td></tr>ROWS</table>`; }
</script></body>'''


# The IO Modules screen as one real controller draws it: no table and no row
# elements, a frozen module column and a separate header pane, four role=grid
# containers that only look like one table because of where the cells sit.
CELL = 'line-height:24px;height:24px;'
MAXTIME = '''<!doctype html><body><h1>Cabinet Configuration</h1>
<div role=grid style="position:fixed;left:0;top:0;width:130px"><div style="CELL">IO Module</div></div>
<div role=grid style="position:fixed;left:140px;top:0;display:grid;grid-template-columns:160px 140px">
<div style="CELL">Type</div><div style="CELL">Fault Response</div></div>
<div role=grid style="position:fixed;left:0;top:30px;width:130px">LEFT</div>
<div role=grid style="position:fixed;left:140px;top:30px;display:grid;grid-template-columns:160px 140px">RIGHT</div>
</body>'''.replace('CELL', CELL)

ONE_MODULE = ('<div style="CELL">1</div>',
              '<div style="CELL">Caltrans 332</div><div style="CELL">Default</div>')
TWO_MODULES = (ONE_MODULE[0] + '<div style="CELL">2</div>',
               ONE_MODULE[1] + '<div style="CELL">TS2 DR1 BIU</div><div style="CELL">Default</div>')
GRID_PROFILE = dict(headers=['IO Module', 'Type', 'Fault Response'], module_column=0,
                    type_column=1, complete_table_confirmed=True,
                    observed_non_biu_types=['caltrans 332'])


def maxtime(modules):
    return MAXTIME.replace('LEFT', modules[0]).replace('RIGHT', modules[1]).replace('CELL', CELL)



class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        cls.browser = cls.p.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def test_navigation_falls_back_to_the_menu_walk(self):
        """This firmware does not route by address, so the four menus are used."""
        for rows, expected in [('', 'no'),
            ('<tr><td>2</td><td><select><option>None</option><option selected>TS2 DR1 BIU</option></select></td></tr>', 'yes')]:
            with self.subTest(expected=expected):
                ctx = self.browser.new_context()
                page = ctx.new_page()
                ctx.route('**/*', lambda route: route.fulfill(content_type='text/html', body=(
                    '<h1>Nothing routed here</h1>' if route.request.url.endswith('IOModules')
                    else MENU.replace('ROWS', rows) if 'in=1' in route.request.url else LOGIN)))
                navigate(page, 'http://192.0.2.1/maxtime/', 'synthetic-user', 'synthetic-password')
                evidence = inspect_modules(page, PROFILE)
                self.assertEqual(classify(evidence, PROFILE)[0], expected)
                self.assertEqual(evidence[1][1], 'SIU')  # Unselected BIU option cannot cause a yes.
                ctx.close()

    def test_unreadable_and_paginated_pages_are_unknown(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        for body in (
            '<input type=password><h1>IO Modules</h1>',
            '<h1>Some other page</h1>',
            '<h1>IO Modules</h1><table><tr><th>Module</th><th>Type</th></tr>'
            '<tr><td>1</td><td>SIU</td></tr></table><button>Next page</button>',
        ):
            page.set_content(body)
            with self.assertRaises(RuntimeError):
                inspect_modules(page, PROFILE)
        ctx.close()

    def test_a_live_table_elsewhere_does_not_block_the_module_table(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.set_content("""<h1>IO Modules</h1>
          <table><tr><th>Status</th><th>Value</th></tr><tr><td>Time</td><td id=t>0</td></tr></table>
          <table><tr><th>Module</th><th>Type</th></tr><tr><td>1</td><td>SIU</td></tr></table>
          <script>setInterval(() => t.textContent = Date.now(), 100)</script>""")
        self.assertEqual(classify(inspect_modules(page, PROFILE), PROFILE)[0], 'no')
        ctx.close()

    def test_missing_and_restless_tables_name_their_reason(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.set_content('<h1>IO Modules</h1><div class=grid><div>Module 1</div><div>TS2 DR1 BIU</div></div>')
        with self.assertRaises(RuntimeError) as missing:
            stable_tables(page, hold=0.3, budget=1)
        self.assertIn('no table with more than one visible row', str(missing.exception))
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'biu-diagnostic.json'
            diagnose(page, report)
            text = report.read_text()
        self.assertIn('TS2 DR1 BIU', text)  # The structure report shows what the table reader could not.
        page.set_content("""<table><tr><th>Module</th><th>Type</th></tr>
          <tr><td>1</td><td id=v>SIU</td></tr></table>
          <script>setInterval(() => v.textContent = Date.now(), 100)</script>""")
        with self.assertRaises(RuntimeError) as restless:
            stable_tables(page, hold=0.5, budget=2)
        self.assertIn('none held still', str(restless.exception))
        ctx.close()

    def test_a_header_mismatch_names_both_sets_of_headings(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.set_content(maxtime(ONE_MODULE).replace('>Type<', '>Kind<'))
        with self.assertRaises(RuntimeError) as caught:
            inspect_modules(page, GRID_PROFILE)
        message = str(caught.exception)
        self.assertIn('No table on the page carries both calibrated headings', message)
        self.assertIn('Calibrated: IO Module | Type', message)
        self.assertIn('Found: IO Module | Kind | Fault Response', message)
        ctx.close()

    def test_a_cabinet_showing_fewer_columns_is_still_read(self):
        """Some cabinets show IO Module and Type with no Fault Response column."""
        ctx = self.browser.new_context()
        page = ctx.new_page()
        cell = lambda t: '<div style="%s">%s</div>' % (CELL, t)
        page.set_content(maxtime(TWO_MODULES)
                         .replace(cell('Fault Response'), '').replace(cell('Default'), '')
                         .replace('grid-template-columns:160px 140px', 'grid-template-columns:160px'))
        evidence = inspect_modules(page, GRID_PROFILE)
        self.assertEqual(evidence[0], ['IO Module', 'Type'])
        self.assertEqual(classify(evidence, GRID_PROFILE), ('yes', 'Module 2: TS2 DR1 BIU'))
        ctx.close()

    def test_a_grid_without_row_elements_is_read_from_cell_positions(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        for modules, expected in ((ONE_MODULE, ('no', 'Only module 1 is configured')),
                                  (TWO_MODULES, ('yes', 'Module 2: TS2 DR1 BIU'))):
            with self.subTest(expected=expected):
                page.set_content(maxtime(modules))
                evidence = inspect_modules(page, GRID_PROFILE)
                self.assertEqual(evidence[0], GRID_PROFILE['headers'])
                self.assertEqual(evidence[1], ['1', 'Caltrans 332', 'Default'])
                self.assertEqual(classify(evidence, GRID_PROFILE), expected)
        ctx.close()

    def test_the_io_modules_address_is_used_before_the_menu_walk(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        login = ("<input id=u><input type=password>"
                 "<button onclick=\"document.body.innerHTML='<h1>Home</h1>'\">Sign in</button>")
        ctx.route('**/*', lambda route: route.fulfill(
            body=maxtime(TWO_MODULES) if route.request.url.endswith('IOModules') else login,
            content_type='text/html'))
        navigate(page, 'http://192.0.2.1:52270/maxtime/', 'synthetic-user', 'synthetic-password')
        self.assertTrue(page.url.endswith('/Controller/AdvancedIO/CabinetConfiguration/IOModules'))
        self.assertEqual(classify(inspect_modules(page, GRID_PROFILE), GRID_PROFILE)[0], 'yes')
        ctx.close()

    def test_an_unfamiliar_module_type_names_itself(self):
        answer, why = classify([GRID_PROFILE['headers'], ['1', 'Model 2070 Something', 'Default']], GRID_PROFILE)
        self.assertEqual(answer, 'unknown')
        self.assertIn('model 2070 something', why)

    def test_the_account_type_is_chosen_by_position_or_by_label(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        form = ('<select><option>Local account</option><option>Profile server</option></select>'
                '<input id=u><input type=password>')
        for choice in ('2', 'profile server'):
            with self.subTest(choice=choice):
                page.set_content(form)
                self.assertEqual(choose_account_type(page, choice), 'Profile server')
                self.assertEqual(page.locator('select').input_value(), 'Profile server')
        page.set_content(form)
        with self.assertRaises(RuntimeError):
            choose_account_type(page, '9')
        # A custom dropdown is not a select, so the label is clicked instead.
        page.set_content('<div onclick="this.textContent=\'chosen\'">Profile server</div>')
        self.assertEqual(choose_account_type(page, 'Profile server'), 'Profile server')
        self.assertEqual(page.locator('div').inner_text(), 'chosen')
        ctx.close()

    def test_a_custom_account_dropdown_is_opened_before_the_option_is_picked(self):
        """MAXTIME's sign in page: no select, and the list is drawn only once opened."""
        ctx = self.browser.new_context()
        page = ctx.new_page()
        profile_server = 'Profile Server - http://KYTrafficSigOps.kytc.ky.gov:58080'
        page.set_content(
            '<div id=box><div id=now onclick="list.hidden=false">Controller</div>'
            '<div id=list hidden>'
            '<div onclick="now.textContent=this.textContent;list.hidden=true">Controller</div>'
            '<div onclick="now.textContent=this.textContent;list.hidden=true">' + profile_server + '</div>'
            '</div></div><input id=u><input type=password>')
        self.assertEqual(choose_account_type(page, 'Profile Server', 'Controller'), profile_server)
        self.assertEqual(page.locator('#now').inner_text(), profile_server)
        ctx.close()

    def test_the_newest_run_in_the_results_folder_is_the_one_loaded(self):
        """The folder picker needs a click, so the handle itself is stood in for."""
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.goto((Path(__file__).resolve().parents[1] / 'webapp/box.html').as_uri())
        page.evaluate('loadDemo()')
        work = page.evaluate('result.check.map(e => ({id:String(e.id),maxtime_url:e.url}))')
        evidence = [['Module', 'Type'], ['1', 'SIU']]

        def run(biu, extra):
            return json.dumps(dict(schema=SCHEMA, results=[dict(
                id=work[0]['id'], maxtime_url=work[0]['maxtime_url'], biu=biu,
                evidence=evidence + extra, reason='r', checked_at='2026-09-09T12:00:00Z')]))

        self.assertEqual(page.evaluate("newestRun(['20260909T000000000000Z', 'notes', '20260908T235959000000Z'])"),
                         '20260909T000000000000Z')
        page.evaluate("""(runs) => {
          const dirs = runs.map(r => ({ kind: 'directory', name: r.name,
            getFileHandle: async n => { if (n !== 'results.json') throw new Error('missing');
              return { getFile: async () => ({ text: async () => r.text }) }; } }));
          useResultsFolder({ name: 'biu-results', kind: 'directory',
            queryPermission: async () => 'granted',
            entries: async function* () { for (const d of dirs) yield [d.name, d]; },
            getDirectoryHandle: async n => dirs.find(d => d.name === n) });
        }""", [{'name': '20260908T101010000000Z', 'text': run('no', [])},
               {'name': '20260909T174050009501Z', 'text': run('yes', [['2', 'TS2 DR1 BIU']])}])
        page.evaluate('loadNewestRun()')
        self.assertEqual(page.evaluate('state.lastImport.run'), '20260909T174050009501Z')
        self.assertIn('20260909T174050009501Z', page.locator('#panel').inner_text())
        found = page.evaluate('state.found')[work[0]['id']]
        self.assertEqual(found['biu'], 'yes')
        ctx.close()

    def test_an_imported_run_lands_on_the_rows_and_flags_every_outcome(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.goto((Path(__file__).resolve().parents[1] / 'webapp/box.html').as_uri())
        page.evaluate('loadDemo()')
        work = page.evaluate('result.check.map(e => ({id:String(e.id),maxtime_url:e.url}))')
        evidence = [['Module', 'Type'], ['1', 'SIU']]
        page.evaluate('(p) => importRun(p, "run-one")', dict(schema=SCHEMA, results=[
            dict(**work[0], biu='yes', evidence=evidence + [['2', 'TS2 DR1 BIU']],
                 reason='Module 2: TS2 DR1 BIU', checked_at='2026-09-09T12:00:00Z'),
            dict(**work[1], biu='unknown', evidence=evidence,
                 reason='Module type not seen during calibration: ts2 siu', checked_at='2026-09-09T12:00:01Z'),
            dict(**work[2], biu='no', evidence=evidence,
                 reason='Only module 1 is configured', checked_at='2026-09-09T12:00:02Z'),
            dict(id='9999', maxtime_url='http://198.51.100.1/maxtime/', biu='no', evidence=evidence,
                 reason='r', checked_at='2026-09-09T12:00:03Z')]))

        found = page.evaluate('state.found')
        self.assertEqual(found[work[0]['id']]['biu'], 'yes')     # Taken as answered, no confirming.
        self.assertIsNone(found[work[1]['id']]['biu'])
        self.assertTrue(found[work[1]['id']]['undecided'])
        self.assertEqual(found[work[2]['id']]['biu'], 'no')

        panel = page.locator('#panel')
        self.assertIn('9999: Not in the current check list', panel.inner_text())  # Never dropped quietly.
        self.assertIn('1 box to export', panel.inner_text())
        self.assertIn('1 with no answer', panel.inner_text())

        # Blue owes a file, red has no answer, an answered no is neither.
        cls = lambda w: panel.locator(f'tr[data-id="{w["id"]}"]').get_attribute('class')
        self.assertEqual(cls(work[0]), 'owed')
        self.assertEqual(cls(work[1]), 'noanswer')
        self.assertEqual(cls(work[2]), 'settled')

        # The module table stands open rather than folded away.
        table = panel.locator(f'tr[data-id="{work[0]["id"]}"] .ev details')
        self.assertTrue(table.get_attribute('open') is not None)
        self.assertIn('2 | TS2 DR1 BIU', table.locator('pre').inner_text())

        self.assertEqual(page.evaluate('boxesToDownload(result.check, state.found).map(e => String(e.id))'),
                         [work[0]['id']])
        page.evaluate('(id) => setFound(id, {saved: true})', work[0]['id'])
        self.assertEqual(cls(work[0]), 'settled')

        # A later run leaves an answer alone and replaces what carries none.
        page.evaluate('(p) => importRun(p, "run-two")', dict(schema=SCHEMA, results=[
            dict(**work[0], biu='no', evidence=evidence, reason='changed', checked_at='2026-09-09T13:00:00Z'),
            dict(**work[1], biu='no', evidence=evidence, reason='read this time', checked_at='2026-09-09T13:00:01Z')]))
        after = page.evaluate('state.found')
        self.assertEqual(after[work[0]['id']]['biu'], 'yes')
        self.assertEqual(after[work[1]['id']]['biu'], 'no')
        self.assertFalse(after[work[1]['id']]['undecided'])
        self.assertIn('1 already answered', panel.inner_text())
        ctx.close()

    def test_answers_flagged_by_an_older_page_are_taken_as_given(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        url = (Path(__file__).resolve().parents[1] / 'webapp/box.html').as_uri()
        page.goto(url)
        page.evaluate("""() => localStorage.setItem('mtb.found', JSON.stringify({
          '4100': {biu: 'yes', saved: false, unconfirmed: true},
          '4101': {biu: null, unconfirmed: true, failed: true},
          '4102': {biu: null, unconfirmed: true}}))""")
        page.reload()
        found = page.evaluate('state.found')
        self.assertEqual(found['4100'], {'biu': 'yes', 'saved': False})
        self.assertTrue(found['4101']['failed'])
        self.assertTrue(found['4102']['undecided'])
        self.assertNotIn('unconfirmed', json.dumps(found))
        ctx.close()

    def test_source_lookup_and_missing_folder_ids(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.goto((Path(__file__).resolve().parents[1] / 'webapp/box.html').as_uri())
        page.evaluate("""() => { loadDemo();
          state.listing.push('4822_ELM_OAK.cbx');
          state.master.push({row:20,id:'',s1:'KY 33',s2:'HICKORY CT',county:'CEDARTON'});
          refresh(); }""")
        page.locator('#tabs [data-tab="missing"]').click()
        self.assertIn('4822', page.locator('#panel').inner_text())
        self.assertIn('absent from both sheets', page.locator('#panel').inner_text())
        page.locator('#tabs [data-tab="lookup"]').click()
        page.locator('#idLookup').fill('4102')
        self.assertIn('removed from the controller check list', page.locator('#panel').inner_text())
        page.locator('#idLookup').fill('4120')
        self.assertIn('row 20 (ID blank)', page.locator('#panel').inner_text())
        page.locator('#idLookup').fill('4822')
        self.assertIn('candidate only', page.locator('#panel').inner_text())
        self.assertIn('no matching ID', page.locator('#panel').inner_text())
        ctx.close()

    def test_html_preview_apply_persistence_and_no_network(self):
        ctx = self.browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        network = []
        errors = []
        page.on('request', lambda r: network.append(r.url) if r.url.startswith(('http:', 'https:')) else None)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto((Path(__file__).resolve().parents[1] / 'webapp/box.html').as_uri())
        page.evaluate('loadDemo()')
        work = page.evaluate('result.check.map(e => ({id:String(e.id),maxtime_url:e.url}))')
        self.assertGreaterEqual(len(work), 3)
        evidence = [['Module', 'Type'], ['1', 'SIU']]
        results = [dict(**r, biu='no', evidence=evidence, reason='Only module 1 is configured', checked_at='2026-09-08T12:00:00Z') for r in work]
        results[1]['biu'] = 'yes'
        results[1]['evidence'] = evidence + [['2','TS2 DR1 BIU']]
        results[2]['biu'] = 'unknown'
        page.evaluate('(id) => setFound(id, {biu:"yes",note:"manual note"})', work[0]['id'])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'results.json'
            f.write_text(json.dumps(dict(schema=SCHEMA, results=results)))
            page.locator('#autoResults').set_input_files(str(f))
            page.locator('#dismissImport').wait_for()
            found = page.evaluate('state.found')
            self.assertEqual(found[work[0]['id']]['note'], 'manual note')
            self.assertEqual(found[work[0]['id']]['biu'], 'yes')  # Confirmed, so left alone.
            self.assertEqual(found[work[1]['id']]['biu'], 'yes')
            self.assertEqual(found[work[1]['id']]['evidence'][2], ['2', 'TS2 DR1 BIU'])
            page.reload()
            self.assertEqual(page.evaluate('state.found'), found)
            # The module table stays on the row it came from.
            row = page.locator(f'#panel tr[data-id="{work[1]["id"]}"]')
            self.assertIn('2 | TS2 DR1 BIU', row.locator('.ev pre').text_content())
            # Every yes still owing a file, answered by hand or imported.
            listed = 'boxesToDownload(result.check, state.found).map(e => String(e.id))'
            self.assertEqual(sorted(page.evaluate(listed)), sorted([work[0]['id'], work[1]['id']]))
            page.evaluate('(id) => setFound(id, {saved: true})', work[1]['id'])
            self.assertEqual(page.evaluate(listed), [work[0]['id']])
            page.evaluate('(id) => setFound(id, {saved: false})', work[1]['id'])
            with page.expect_download() as dl:
                page.locator('#btnAutoCsv').click()
            text = Path(dl.value.path()).read_text()
            self.assertNotIn(work[0]['id'], text)
            self.assertNotIn(work[1]['id'], text)
            self.assertNotIn(work[2]['id'], text)  # Unknown, waiting on you, not re-run.
        page.evaluate('(id) => setFound(id, {biu: null})', work[1]['id'])
        self.assertNotIn(work[1]['id'], page.evaluate('state.found'))  # Clearing takes the whole record.
        self.assertEqual(network, [])
        self.assertEqual(errors, [])
        ctx.close()


if __name__ == '__main__':
    unittest.main()
