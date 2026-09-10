"""Synthetic-only tests: python -m unittest discover -s downloader -p test_clickbox.py."""
from pathlib import Path
import tempfile
import unittest

from fetch_clickbox import clickbox_origin, guess, read_worklist

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


if __name__ == '__main__':
    unittest.main()
