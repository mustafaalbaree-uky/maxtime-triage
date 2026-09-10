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


def screen(fields, buttons=()):
    return {'fields': list(fields),
            'buttons': [dict(tag='button', id='', cls='', text=t, disabled=False) for t in buttons]}


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

    def test_missing_controls_are_reported_rather_than_invented(self):
        found, buttons = guess(screen([field(id='x', labels=['Serial'])]))
        self.assertEqual(found, {})
        self.assertIsNone(buttons['save'])
        self.assertIsNone(buttons['export'])


if __name__ == '__main__':
    unittest.main()
