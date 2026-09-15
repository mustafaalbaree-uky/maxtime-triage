"""Synthetic-only tests: python -m unittest discover -s downloader -p test_clickbox.py."""
import contextlib
import socket
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fetch_clickbox import (FILES_SUBDIR, PROPERTIES_TAB, RUNS_SUBDIR,
                            clickbox_origin, export_config, guess,
                            already_exported, confirm, nav_error, open_properties,
                            fill_and_save, fit, knock, order_rows, plan_row,
                            read_worklist, run_memory, selector, write_results)

HEAD = 'id,clickbox_url,name,location,description\n'
GOOD = HEAD + '4380,http://192.0.2.1:57150/,076-4380,US 25 at KY 52 (IRVING RD),KYTC D7\n'


def worklist(text):
    d = tempfile.mkdtemp()
    p = Path(d) / 'in.csv'
    p.write_text(text, encoding='utf-8')
    return p


def field(**kw):
    base = dict(tag='input', type='text', id='', name='', cls='', path='', labels=[],
                readonly=False, maxlength=None, value='', options=None, secret=False)
    base.update(kw)
    return base


def button(text, tag='button', href=''):
    return dict(tag=tag, id='', cls='', text=text, href=href, disabled=False)


def screen(fields, buttons=()):
    return {'fields': list(fields),
            'buttons': [b if isinstance(b, dict) else button(b) for b in buttons]}


# The Click 656 Properties screen, as one reported it on 10 Sep 2026: the three
# fields carry trailing colons, the save control is an input[type=button] that
# lands in the field list too, and Export Configuration is a plain footer link.
CLICK656_FIELDS = [
    field(id='deviceEthernetToControlPort', labels=['Ethernet/Control IP Port:'], value='10001'),
    field(id='deviceName', labels=['Name:'], value=''),
    field(id='deviceLocation', labels=['Location:'], value=''),
    field(id='deviceDescription', labels=['Description:'], value=''),
    field(id='ipAddress0', labels=['IP Address:'], value='192'),
    field(id='biu9', type='checkbox', labels=['9'], value='on'),
    field(id='btnSaveDevice', type='button', labels=['btnSaveDevice'], value='Save Device Properties'),
]
CLICK656_BUTTONS = [
    button('Save Device Properties', tag='input'),
    button('Main', tag='a', href='/'),
    button('Admin', tag='a', href='/admin'),
    button('Export Configuration', tag='a', href='/exportconfig'),
    button('Import Configuration', tag='a', href='/importconfig'),
]


class UrlTests(unittest.TestCase):
    def test_the_maxtime_url_is_refused(self):
        # The two worklists look alike; sending the wrong one somewhere that
        # types into fields is worth refusing loudly.
        for url in ('http://192.0.2.1:52270/maxtime/', 'http://192.0.2.1/',
                    'file:///tmp/a', 'http://user:secret@192.0.2.1:57150/'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    clickbox_origin(url)

    def test_the_clickbox_url_is_accepted(self):
        self.assertEqual(clickbox_origin('http://192.0.2.1:57150/'),
                         ('http', '192.0.2.1', 57150))


class WorklistTests(unittest.TestCase):
    def test_reads_a_good_worklist(self):
        r = read_worklist(worklist(GOOD))[0]
        self.assertEqual(r['name'], '076-4380')
        self.assertEqual(r['location'], 'US 25 at KY 52 (IRVING RD)')
        self.assertEqual(r['description'], 'KYTC D7')

    def test_wrong_worklist_rejected(self):
        with self.assertRaises(ValueError):
            read_worklist(worklist('id,maxtime_url,intersection\n4380,http://192.0.2.1/,A at B\n'))

    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):
            read_worklist(worklist(GOOD + GOOD.split('\n')[1] + '\n'))

    def test_a_signal_with_no_proposal_is_refused(self):
        # A blank Name means the sheets are missing a CountyID. Typing an empty
        # string into a controller is worse than stopping.
        bad = HEAD + '4380,http://192.0.2.1:57150/,,US 25 at KY 52,KYTC D7\n'
        with self.assertRaises(ValueError):
            read_worklist(worklist(bad))


class GuessTests(unittest.TestCase):
    def test_finds_the_three_fields_by_label(self):
        found, buttons = guess(screen([
            field(id='dev-name', labels=['Name']),
            field(id='dev-loc', labels=['Location']),
            field(id='dev-desc', labels=['Description']),
        ], ['Save Device Properties', 'Export Configuration']))
        self.assertEqual(found['name']['id'], 'dev-name')
        self.assertEqual(found['location']['id'], 'dev-loc')
        self.assertEqual(found['description']['id'], 'dev-desc')
        self.assertEqual(buttons['save']['text'], 'Save Device Properties')
        self.assertEqual(buttons['export']['text'], 'Export Configuration')

    def test_an_exact_label_beats_a_field_that_merely_contains_the_word(self):
        found, _ = guess(screen([
            field(id='host', labels=['Host Name']),
            field(id='real', labels=['Name']),
        ]))
        self.assertEqual(found['name']['id'], 'real')

    def test_one_field_is_never_claimed_twice(self):
        found, _ = guess(screen([field(id='only', labels=['Name', 'Location'])]))
        self.assertEqual(found['name']['id'], 'only')
        self.assertNotIn('location', found)

    def test_a_password_is_never_offered_as_a_field(self):
        found, _ = guess(screen([field(id='pw', type='password', secret=True,
                                       labels=['Name']), ]))
        self.assertNotIn('name', found)

    def test_the_real_click_656_properties_screen(self):
        found, buttons = guess(screen(CLICK656_FIELDS, CLICK656_BUTTONS))
        self.assertEqual(found['name']['id'], 'deviceName')
        self.assertEqual(found['location']['id'], 'deviceLocation')
        self.assertEqual(found['description']['id'], 'deviceDescription')
        self.assertEqual(buttons['save']['text'], 'Save Device Properties')
        self.assertEqual(buttons['export']['href'], '/exportconfig')

    def test_the_save_control_is_never_taken_for_a_text_field(self):
        # btnSaveDevice is an input[type=button], so it sits in the field list
        # beside the real fields. Nothing may ever be typed into it.
        found, _ = guess(screen([field(id='btnSaveDevice', type='button',
                                       labels=['Name'], value='Save')]))
        self.assertEqual(found, {})

    def test_a_readonly_field_is_not_offered(self):
        found, _ = guess(screen([field(id='ro', labels=['Name'], readonly=True)]))
        self.assertEqual(found, {})

    def test_export_is_found_as_a_plain_link(self):
        _, buttons = guess(screen([], [button('Export Configuration', tag='a', href='/exportconfig')]))
        self.assertEqual(buttons['export']['tag'], 'a')

    def test_the_exact_save_wins_over_another_control_saying_save(self):
        _, buttons = guess(screen([], [button('Save Sensor Settings'),
                                       button('Save Device Properties')]))
        self.assertEqual(buttons['save']['text'], 'Save Device Properties')

    def test_missing_controls_are_reported_rather_than_invented(self):
        found, buttons = guess(screen([field(id='x', labels=['Serial'])]))
        self.assertEqual(found, {})
        self.assertIsNone(buttons['save'])
        self.assertIsNone(buttons['export'])



class FakeFrame:
    """Enough of a Playwright frame to prove what does and does not get touched."""

    def __init__(self, values, saves=True):
        self.values, self.saves = dict(values), saves
        self.filled, self.clicked = [], []

    def fill(self, sel, value):
        self.filled.append((sel, value))
        if self.saves:
            self.values[sel] = value

    def click(self, sel):
        self.clicked.append(sel)

    def wait_for_timeout(self, ms):
        pass

    def input_value(self, sel):
        return self.values.get(sel, '')


class FakePage:
    def __init__(self, download=None):
        self.download = download

    @contextlib.contextmanager
    def expect_download(self, timeout=None):
        if self.download is None:
            raise TimeoutError('no download')
        yield self

    @property
    def value(self):
        return self.download


class FakeDownload:
    def __init__(self, name):
        self.suggested_filename = name

    def save_as(self, path):
        Path(path).write_bytes(b'config')


FIELDS = {'name': field(id='deviceName', value=''),
          'location': field(id='deviceLocation', value='OLD PLACE'),
          'description': field(id='deviceDescription', value='KYTC D7')}
ROW = {'id': '4030', 'name': '009-4030', 'location': 'US 68X at KY 1678',
       'description': 'KYTC D7'}


class PlanTests(unittest.TestCase):
    def test_empty_fills_wrong_replaces_same_is_left_alone(self):
        p = plan_row(FIELDS, ROW)
        self.assertEqual(p['name']['action'], 'fill')
        self.assertEqual(p['location']['action'], 'replace')
        self.assertEqual(p['description']['action'], 'ok')

    def test_surrounding_space_on_the_device_is_not_a_difference(self):
        p = plan_row({**FIELDS, 'description': field(id='d', value='  KYTC D7 ')}, ROW)
        self.assertEqual(p['description']['action'], 'ok')


class PropertiesTabTests(unittest.TestCase):
    # Getting to Properties means clicking the word, the top tabs being neither
    # links nor anything with a role. Two other things on that same screen say
    # "Properties" and clicking either would be wrong: the heading, and the
    # save control.
    def test_matches_the_tab(self):
        for text in ('PROPERTIES', 'Properties', ' properties '):
            with self.subTest(text=text):
                self.assertTrue(PROPERTIES_TAB.match(text))

    def test_never_matches_the_heading_or_the_save_control(self):
        for text in ('Device Properties', 'Save Device Properties',
                     'Properties and Settings', 'Import Configuration'):
            with self.subTest(text=text):
                self.assertIsNone(PROPERTIES_TAB.match(text))


class SelectorTests(unittest.TestCase):
    def test_a_button_carries_no_name_and_must_not_raise(self):
        self.assertEqual(selector(button('Save', tag='input')), '')
        self.assertEqual(selector({'tag': 'input', 'id': 'btnSaveDevice'}), '#btnSaveDevice')


class FillTests(unittest.TestCase):
    def setUp(self):
        self.buttons = {'save': dict(tag='input', id='btnSaveDevice', cls='',
                                     text='Save Device Properties', href='', disabled=False)}

    def test_only_the_fields_that_need_changing_are_typed_into(self):
        frame = FakeFrame({'#deviceName': '', '#deviceLocation': 'OLD PLACE',
                           '#deviceDescription': 'KYTC D7'})
        typed, after = fill_and_save(frame, FIELDS, plan_row(FIELDS, ROW), self.buttons)
        self.assertEqual([s for s, _ in frame.filled], ['#deviceName', '#deviceLocation'])
        self.assertEqual(set(typed), {'name', 'location'})
        self.assertEqual(after['name'], '009-4030')
        self.assertEqual(frame.clicked, ['#btnSaveDevice'])

    def test_nothing_to_change_means_save_is_never_pressed(self):
        same = {k: field(id='device' + k, value=ROW[k]) for k in ROW if k != 'id'}
        frame = FakeFrame({})
        typed, _ = fill_and_save(frame, same, plan_row(same, ROW), self.buttons)
        self.assertEqual(typed, {})
        self.assertEqual(frame.clicked, [])

    def test_a_device_that_does_not_keep_the_value_is_caught_by_reading_back(self):
        frame = FakeFrame({'#deviceName': '', '#deviceLocation': 'OLD PLACE',
                           '#deviceDescription': 'KYTC D7'}, saves=False)
        typed, after = fill_and_save(frame, FIELDS, plan_row(FIELDS, ROW), self.buttons)
        self.assertNotEqual(after['name'], typed['name'])


class ExportTests(unittest.TestCase):
    BUTTONS = {'export': button('Export Configuration', tag='a', href='/')}

    def test_the_download_lands_in_the_output_folder(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'exports'
            page = FakePage(FakeDownload('click_656_config.cbx'))
            path, why = export_config(page, FakeFrame({}), self.BUTTONS, out, '4030')
            self.assertEqual(why, '')
            self.assertTrue(path.exists())
            self.assertEqual(path.name, 'click_656_config.cbx')

    def test_a_second_export_of_the_same_name_does_not_overwrite_the_first(self):
        # The device names these itself, so two signals can send the same name.
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'exports'
            for _ in range(2):
                export_config(FakePage(FakeDownload('config.cbx')), FakeFrame({}),
                              self.BUTTONS, out, '4030')
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ['config (1).cbx', 'config.cbx'])

    def test_no_download_is_reported_rather_than_hanging(self):
        with tempfile.TemporaryDirectory() as d:
            path, why = export_config(FakePage(None), FakeFrame({}), self.BUTTONS,
                                      Path(d), '4030')
            self.assertIsNone(path)
            self.assertIn('no download', why)

    def test_a_missing_export_link_is_reported(self):
        path, why = export_config(FakePage(None), FakeFrame({}), {}, Path('.'), '4030')
        self.assertIsNone(path)
        self.assertIn('no Export Configuration', why)


class Args:
    def __init__(self, out_dir):
        self.out_dir = out_dir


class OutputLayoutTests(unittest.TestCase):
    def test_configurations_and_run_records_do_not_share_a_folder(self):
        # The configurations folder gets selected whole and dragged into
        # SharePoint, so nothing else may be sitting in it.
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'clickbox-exports'
            export_config(FakePage(FakeDownload('config.cbx')), FakeFrame({}),
                          ExportTests.BUTTONS, out / FILES_SUBDIR, '4030')
            written = write_results(Args(out), '20260910T190000Z',
                                    [dict(id='4030', exported='x', skipped='',
                                          error='', note='')])
            self.assertEqual([p.name for p in (out / FILES_SUBDIR).iterdir()],
                             ['config.cbx'])
            self.assertEqual([p.suffix for p in (out / RUNS_SUBDIR).iterdir()], ['.json'])
            self.assertEqual(written.parent.name, RUNS_SUBDIR)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             [FILES_SUBDIR, RUNS_SUBDIR])


class DeadPage:
    """A clickbox that is not there: every navigation raises, so no frame of it
    is ever read."""

    def __init__(self, error):
        self.error, self.tried = error, []
        self.frames = []

    def goto(self, url, **kw):
        self.tried.append(url)
        raise TimeoutError(self.error)

    def wait_for_timeout(self, ms):
        pass


class EmptyPage(DeadPage):
    """A clickbox that answers, on a screen carrying none of the three fields."""

    def goto(self, url, **kw):
        self.tried.append(url)

    def wait_for_load_state(self, state, timeout=None):
        pass


class UnreachableTests(unittest.TestCase):

    def test_a_dead_address_is_waited_on_once_not_twice(self):
        # Two paths are tried on a device that answers. On one that does not,
        # the second is the same wait for the same silence, and a list of
        # twenty pays for it twenty times.
        page = DeadPage('Timeout 20000ms exceeded.')
        open_properties(page, 'http://192.0.2.1:57150/', 20000)
        self.assertEqual(len(page.tried), 1)

    def test_a_clickbox_that_never_answers_says_so(self):
        page = DeadPage('Timeout 20000ms exceeded.')
        frame, _, found, buttons, why = open_properties(page, 'http://192.0.2.1:57150/', 20000)
        self.assertIsNone(frame)
        self.assertEqual(found, {})
        self.assertIn('never answered', why)
        self.assertIn('timed out', why)

    def test_a_refused_connection_names_the_refusal(self):
        page = DeadPage('page.goto: net::ERR_CONNECTION_REFUSED at http://192.0.2.1:57150/')
        _, _, _, _, why = open_properties(page, 'http://192.0.2.1:57150/', 20000)
        self.assertIn('ERR_CONNECTION_REFUSED', why)

    def test_a_device_that_answers_is_not_called_unreachable(self):
        # Answering on the wrong screen and not answering at all are different
        # jobs: one needs the device looked at, the other needs the network.
        page = EmptyPage('')
        _, _, _, _, why = open_properties(page, 'http://192.0.2.1:57150/', 20000)
        self.assertNotIn('never answered', why)
        self.assertIn('no Name, Location and Description', why)

    def test_the_address_is_never_folded_into_the_reason(self):
        page = DeadPage('page.goto: net::ERR_CONNECTION_REFUSED at http://10.136.1.193:57150/')
        _, _, _, _, why = open_properties(page, 'http://10.136.1.193:57150/', 20000)
        self.assertNotIn('10.136.1.193', why)

    def test_an_error_with_no_text_still_reports_something(self):
        self.assertEqual(nav_error(ValueError('')), 'ValueError')


class AutoTests(unittest.TestCase):
    """--auto answers for itself. What it may and may not answer for."""

    EMPTY = {'name': field(id='deviceName', value=''),
             'location': field(id='deviceLocation', value=''),
             'description': field(id='deviceDescription', value='')}
    DISAGREES = {'name': field(id='deviceName', value='076-4030'),
                 'location': field(id='deviceLocation', value=''),
                 'description': field(id='deviceDescription', value='')}

    def answer(self, found, **kw):
        plan = plan_row(found, ROW)
        with mock.patch('builtins.input', side_effect=AssertionError('it asked')) as asked:
            if kw.get('expect_ask'):
                asked.side_effect = ['y']
            return confirm(ROW, plan, auto=True, auto_replace=kw.get('auto_replace', False))

    def test_empty_fields_are_filled_without_asking(self):
        self.assertEqual(self.answer(self.EMPTY), 'y')

    def test_a_device_already_correct_exports_without_asking(self):
        found = {k: field(id='device' + k.title(), value=ROW[k]) for k in ROW if k != 'id'}
        self.assertEqual(self.answer(found), 'y')

    def test_a_disagreeing_value_still_stops_under_auto(self):
        # The device says one thing and the sheets say another. Which is wrong
        # is not something a flag can settle.
        self.assertEqual(self.answer(self.DISAGREES, expect_ask=True), 'y')

    def test_auto_replace_answers_for_the_disagreement_too(self):
        self.assertEqual(self.answer(self.DISAGREES, auto_replace=True), 'y')

    def test_without_auto_even_an_empty_field_asks(self):
        plan = plan_row(self.EMPTY, ROW)
        with mock.patch('builtins.input', side_effect=['n']):
            self.assertEqual(confirm(ROW, plan), 'n')


class MemoryTests(unittest.TestCase):
    """A worklist exported before the last run still carries what that run
    finished, so the run records are what stop a second visit."""

    def runs(self, d, *records):
        out = Path(d) / 'clickbox-exports'
        for i, recs in enumerate(records):
            write_results(Args(out), '2026091%dT120000Z' % i, list(recs))
        return out

    def rec(self, sid, **kw):
        base = dict(id=sid, exported='', skipped='', error='', note='')
        base.update(kw)
        return base

    def test_an_exported_signal_is_remembered(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.runs(d, [self.rec('4030', exported='files/a.cbx')])
            self.assertEqual(sorted(already_exported(out)), ['4030'])

    def test_a_failure_is_not_remembered_as_done(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.runs(d, [self.rec('4002', error='never answered'),
                                self.rec('4003', skipped='skipped')])
            self.assertEqual(already_exported(out), {})

    def test_every_run_record_counts_not_only_the_last(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.runs(d, [self.rec('4030', exported='a')],
                               [self.rec('4031', exported='b')])
            self.assertEqual(sorted(already_exported(out)), ['4030', '4031'])

    def test_a_folder_with_no_runs_remembers_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(already_exported(Path(d) / 'nothing-here'), {})

    def test_an_unreadable_record_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.runs(d, [self.rec('4030', exported='a')])
            (out / RUNS_SUBDIR / 'clickbox-run-broken.json').write_text('{ not json')
            self.assertEqual(sorted(already_exported(out)), ['4030'])

    def test_another_tools_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'clickbox-exports'
            (out / RUNS_SUBDIR).mkdir(parents=True)
            (out / RUNS_SUBDIR / 'clickbox-run-x.json').write_text(
                '{"schema": "maxtime-biu-v1", "results": [{"id": "4030", "exported": "a"}]}')
            self.assertEqual(already_exported(out), {})


class OrderTests(unittest.TestCase):
    """20 devices a session, and the ones that time out do it again every time.
    Left at the front they are the only 20 that ever get tried."""

    ROWS = [{'id': str(4000 + i)} for i in range(6)]

    def ids(self, exported, failed):
        rows, said = order_rows(self.ROWS, exported, failed)
        return [r['id'] for r in rows], said

    def test_failures_go_to_the_back_not_out(self):
        got, _ = self.ids({}, {'4000': 'timed out', '4001': 'timed out'})
        self.assertEqual(got, ['4002', '4003', '4004', '4005', '4000', '4001'])

    def test_a_limited_run_reaches_the_untried_ones(self):
        got, _ = self.ids({}, {'4000': 'timed out', '4001': 'timed out'})
        self.assertEqual(got[:2], ['4002', '4003'])

    def test_exported_ones_are_dropped_entirely(self):
        got, _ = self.ids({'4002': 'run.json'}, {})
        self.assertNotIn('4002', got)

    def test_a_signal_that_later_exported_is_no_longer_a_failure(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'clickbox-exports'
            write_results(Args(out), '20260915T120000Z',
                          [dict(id='4030', exported='', skipped='', error='timed out', note='')])
            write_results(Args(out), '20260915T130000Z',
                          [dict(id='4030', exported='files/a.cbx', skipped='', error='', note='')])
            exported, failed = run_memory(out)
            self.assertEqual(sorted(exported), ['4030'])
            self.assertEqual(failed, {})

    def test_nothing_is_said_when_nothing_moved(self):
        got, said = self.ids({}, {})
        self.assertEqual(got, [r['id'] for r in self.ROWS])
        self.assertEqual(said, [])

    def test_a_list_that_is_all_failures_keeps_its_order(self):
        # Nothing to put them behind, so the run is the retry.
        got, said = self.ids({}, {r['id']: 'timed out' for r in self.ROWS})
        self.assertEqual(got, [r['id'] for r in self.ROWS])
        self.assertEqual(said, [])


class LengthTests(unittest.TestCase):
    """The Click 656 caps Location at 32 characters and cuts the rest off as
    the browser types. Signal 4422, 15 Sep 2026: the device held
    'US 127 COLLEGE ST at US 68 MOREL' and the sheets say MORELAND."""

    LONG = 'US 127 COLLEGE ST at US 68 MORELAND'
    CUT = 'US 127 COLLEGE ST at US 68 MOREL'

    def plan(self, current):
        found = {'name': field(id='deviceName', value='084-4422'),
                 'location': field(id='deviceLocation', value=current, maxlength=32),
                 'description': field(id='deviceDescription', value='KYTC D7')}
        row = {'id': '4422', 'name': '084-4422', 'location': self.LONG,
               'description': 'KYTC D7'}
        return found, row, plan_row(found, row)

    def test_a_value_is_cut_to_what_the_field_holds(self):
        self.assertEqual(fit(self.LONG, field(maxlength=32)), self.CUT)

    def test_no_limit_leaves_the_value_alone(self):
        self.assertEqual(fit(self.LONG, field()), self.LONG)

    def test_a_device_already_holding_the_cut_value_is_correct(self):
        # It reported as a field that disagreed, then as a save the device
        # refused. It is neither: the device is full.
        _, _, plan = self.plan(self.CUT)
        self.assertEqual(plan['location']['action'], 'ok')
        self.assertTrue(plan['location']['cut'])

    def test_an_empty_field_is_filled_with_the_cut_value(self):
        _, _, plan = self.plan('')
        self.assertEqual(plan['location']['action'], 'fill')
        self.assertEqual(plan['location']['want'], self.CUT)
        self.assertEqual(plan['location']['full'], self.LONG)

    def test_the_read_back_agrees_with_what_was_typed(self):
        found, _, plan = self.plan('')
        frame = FakeFrame({'#deviceLocation': ''})
        typed, after = fill_and_save(frame, found, plan, {'save': button('Save')})
        self.assertEqual(after['location'], typed['location'])
        self.assertEqual(typed['location'], self.CUT)


class KnockTests(unittest.TestCase):

    def test_a_closed_port_is_not_called_silent(self):
        # Refused and silent are different problems: one has something there.
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        self.assertIn(knock('http://127.0.0.1:%d/' % port, 1), ('refused', 'silent'))

    def test_an_open_port_answers(self):
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        try:
            self.assertEqual(knock('http://127.0.0.1:%d/' % s.getsockname()[1], 2), 'answers')
        finally:
            s.close()


if __name__ == '__main__':
    unittest.main()
