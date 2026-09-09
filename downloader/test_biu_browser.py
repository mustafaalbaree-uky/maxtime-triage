"""Offline browser integration tests; requires Playwright and Chromium.
Run: python -m unittest discover -s downloader -p test_biu_browser.py
"""
import json
from pathlib import Path
import tempfile
import unittest
from playwright.sync_api import sync_playwright

from check_biu import (navigate, inspect_modules, classify, stable_tables, diagnose,
                       choose_account_type, SCHEMA)
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
        self.assertEqual(page.evaluate('loadedRun'), '20260909T174050009501Z')
        self.assertIn('20260909T174050009501Z', page.locator('#panel').inner_text())
        page.locator('#applyAutomation').click()
        self.assertEqual(page.evaluate('state.found')[work[0]['id']]['biu'], 'yes')
        self.assertEqual(page.evaluate('loadedRun'), '')
        ctx.close()

    def test_each_reviewed_row_is_a_decision_that_can_be_changed(self):
        ctx = self.browser.new_context()
        page = ctx.new_page()
        page.goto((Path(__file__).resolve().parents[1] / 'webapp/box.html').as_uri())
        page.evaluate('loadDemo()')
        work = page.evaluate('result.check.map(e => ({id:String(e.id),maxtime_url:e.url}))')
        evidence = [['Module', 'Type'], ['1', 'SIU']]

        def review(answers):
            page.evaluate('(p) => { startReview(p); renderPanel(); }', dict(schema=SCHEMA, results=[
                dict(**w, biu=b, evidence=evidence, reason='r', checked_at='2026-09-09T12:00:00Z')
                for w, b in zip(work, answers)]))

        page.evaluate('(id) => setFound(id, {biu: "no"})', work[0]['id'])
        review(('no', 'no', 'unknown'))
        panel = page.locator('#panel')
        self.assertIn('1 already answered row is not listed', panel.inner_text())
        self.assertNotIn(work[0]['id'], panel.locator('.step table tbody').first.inner_text())
        # The script's answer is filled in; an unknown starts blank.
        self.assertEqual(page.evaluate('automationChoice'), {work[1]['id']: 'no'})

        panel.locator(f'[data-auto="{work[1]["id"]}"][data-biu="yes"]').click()
        panel.locator(f'[data-auto="{work[2]["id"]}"][data-biu="no"]').click()
        panel.locator(f'[data-auto="{work[2]["id"]}"][data-biu=""]').click()
        self.assertEqual(page.evaluate('automationChoice'), {work[1]['id']: 'yes'})
        page.locator('#applyAutomation').click()

        found = page.evaluate('state.found')
        self.assertEqual(found[work[1]['id']]['biu'], 'yes')
        self.assertIn('recorded as yes instead', found[work[1]['id']]['note'])
        self.assertNotIn(work[2]['id'], found)  # Left open records nothing.
        self.assertEqual(found[work[0]['id']]['biu'], 'no')  # The answer it already had.

        # An unknown left open stays decidable on the next run.
        review(('no', 'no', 'unknown'))
        self.assertIn('2 already answered rows are not listed', panel.inner_text())
        panel.locator(f'[data-auto="{work[2]["id"]}"][data-biu="no"]').click()
        page.locator('#applyAutomation').click()
        found = page.evaluate('state.found')
        self.assertEqual(found[work[2]['id']]['biu'], 'no')
        self.assertNotIn('instead', found[work[2]['id']]['note'])
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
            self.assertEqual(found[work[1]['id']]['evidence'][2], ['2', 'TS2 DR1 BIU'])
            page.reload()
            self.assertEqual(page.evaluate('state.found'), found)
            # The module table stays on the row that the answer came from.
            row = page.locator(f'#panel tr[data-id="{work[1]["id"]}"]')
            row.locator('summary', has_text='module table').click()
            self.assertIn('2 | TS2 DR1 BIU', row.locator('pre').inner_text())
            # Every yes still owing a download, whether answered by hand or imported.
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
            self.assertIn(work[2]['id'], text)
        page.evaluate('(id) => setFound(id, {biu: null})', work[1]['id'])  # Clearing takes the evidence with it.
        self.assertNotIn('evidence', page.evaluate('state.found')[work[1]['id']] or {})
        self.assertEqual(network, [])
        self.assertEqual(errors, [])
        ctx.close()


if __name__ == '__main__':
    unittest.main()
