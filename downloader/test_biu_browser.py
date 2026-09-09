"""Offline browser integration tests; requires Playwright and Chromium.
Run: python -m unittest discover -s downloader -p test_biu_browser.py
"""
import json
from pathlib import Path
import tempfile
import unittest
from playwright.sync_api import sync_playwright

from check_biu import navigate, inspect_modules, classify, stable_tables, diagnose, SCHEMA
from test_biu import PROFILE

MOCK = '''<!doctype html><body>
<button onclick="this.outerHTML='<button onclick=login()>Profile server</button>'">Sign into</button>
<script>
function login() { document.body.innerHTML = `<input id=user><input id=pw type=password>
<button onclick="document.body.innerHTML='<button onclick=controller()>Controller</button>'">Sign in</button>`; }
function controller() { document.body.innerHTML='<select onchange=advanced()><option>Choose menu</option><option>Advanced IO</option></select>'; }
function advanced() { document.body.innerHTML='<button onclick=cabinet()>Cabinet Configuration</button>'; }
function cabinet() { document.body.innerHTML='<button onclick=modules()>IO Modules</button>'; }
function modules() { document.body.innerHTML=`<h1>IO Modules</h1>
<table><tr><th>Module</th><th>Type</th></tr>
<tr><td>1</td><td><select><option selected>SIU</option><option>TS2 DR1 BIU</option></select></td></tr>ROWS</table>`; }
</script></body>'''


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        cls.browser = cls.p.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def test_navigation_and_selected_module_types(self):
        for rows, expected in [('', 'no'),
            ('<tr><td>2</td><td><select><option>None</option><option selected>TS2 DR1 BIU</option></select></td></tr>', 'yes')]:
            with self.subTest(expected=expected):
                ctx = self.browser.new_context()
                page = ctx.new_page()
                ctx.route('**/*', lambda route: route.fulfill(body=MOCK.replace('ROWS', rows), content_type='text/html'))
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
            page.locator('#applyAutomation').wait_for()
            before = page.evaluate('JSON.stringify(state.found)')
            self.assertNotIn(work[1]['id'], json.loads(before))
            page.locator('#applyAutomation').click()
            found = page.evaluate('state.found')
            self.assertEqual(found[work[0]['id']]['note'], 'manual note')
            self.assertEqual(found[work[1]['id']]['biu'], 'yes')
            self.assertFalse(found[work[1]['id']]['saved'])
            self.assertNotIn(work[2]['id'], found)
            page.reload()
            self.assertEqual(page.evaluate('state.found'), found)
            with page.expect_download() as dl:
                page.locator('#btnAutoCsv').click()
            text = Path(dl.value.path()).read_text()
            self.assertNotIn(work[0]['id'], text)
            self.assertNotIn(work[1]['id'], text)
            self.assertIn(work[2]['id'], text)
        self.assertEqual(network, [])
        self.assertEqual(errors, [])
        ctx.close()


if __name__ == '__main__':
    unittest.main()
