"""Synthetic-only tests: python -m unittest discover -s downloader -p test_biu.py."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from check_biu import classify, origin, read_worklist

PROFILE = dict(headers=['Module', 'Type'], module_column=0, type_column=1,
               complete_table_confirmed=True, observed_non_biu_types=['siu', 'none'])


class ClassificationTests(unittest.TestCase):
    def check(self, body, expected, profile=None):
        answer, _ = classify([['Module', 'Type']] + body, profile or PROFILE)
        self.assertEqual(answer, expected)

    def test_positive(self):
        self.check([['1', 'SIU'], ['2', 'TS2 DR1 BIU']], 'yes')

    def test_one_module(self):
        self.check([['1', 'SIU']], 'no')

    def test_no_biu(self):
        self.check([['1', 'SIU'], ['2', 'None']], 'no')

    def test_uncertainty(self):
        for rows in ([], [['1', '']], [['2', 'None']], [['1', 'SIU'], ['1', 'SIU']],
                     [['1', 'TS2 DR1 BIU']], [['1', 'SIU'], ['2', 'Other BIU']],
                     [['1', 'SIU'], ['3', 'None']], [['1', 'SIU'], ['Loading...']],
                     [['1', 'SIU'], ['2', '']], [['1', 'Loading...']], [['1', 'Unfamiliar']]):
            with self.subTest(rows=rows):
                self.check(rows, 'unknown')

    def test_unconfirmed(self):
        self.check([['1', 'SIU']], 'unknown', {**PROFILE, 'complete_table_confirmed': False})

    def test_changed_headers(self):
        self.assertEqual(classify([['ID', 'Type'], ['1', 'SIU']], PROFILE)[0], 'unknown')

    def test_url_validation(self):
        for url in ('file:///tmp/a', 'http://user:secret@192.0.2.1/', 'http://192.0.2.1:57150/'):
            with self.assertRaises(ValueError):
                origin(url)

    def test_duplicate_worklist_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'in.csv'
            p.write_text('id,maxtime_url\n4821,http://192.0.2.1\n4821,http://192.0.2.2\n')
            with self.assertRaises(ValueError):
                read_worklist(p)

    def test_import_rules(self):
        html = (Path(__file__).resolve().parents[1] / 'webapp/box.html').read_text()
        logic = html.split('const S =', 1)[1].split('/* ================= LOGIC-END', 1)[0]
        js = 'const S =' + logic + r'''
const assert = require('node:assert/strict');
const check = [{id:'4821',url:'http://192.0.2.1'}, {id:'4822',url:'http://192.0.2.2'}];
const row = {id:'4821',maxtime_url:check[0].url,biu:'no',evidence:[['Module','Type'],['1','SIU']]};
const run = (rows, found={}) => automationProposals({schema:'maxtime-biu-v1',results:rows},check,found);
assert.equal(run([row])[0].skip, '');
assert.ok(run([row],{'4821':{biu:'yes'}})[0].skip);
assert.ok(run([row],{'4821':{saved:true}})[0].skip);
assert.ok(run([{...row,biu:'unknown'}])[0].skip);
assert.ok(run([{...row,id:'4999'}])[0].skip);
assert.ok(run([{...row,maxtime_url:check[1].url}])[0].skip);
assert.ok(run([{...row,evidence:[]}])[0].skip);
assert.ok(run([row,row]).every(r => r.skip));
assert.equal(run([row])[0].kind, 'ready');
assert.equal(run([row],{'4821':{biu:'yes'}})[0].kind, 'answered');
assert.equal(run([{...row,biu:'unknown'}])[0].kind, 'open');
assert.equal(run([{...row,biu:'unknown',evidence:[]}])[0].kind, 'blocked');
assert.equal(run([{...row,id:'4999'}])[0].kind, 'blocked');
assert.throws(() => automationProposals({},check,{}));
const links = {'4821': {row:2,main:'MAIN',side:'OAK',ip:'192.0.2.1',url:'http://192.0.2.1'}};
const master = [{id:'4821',row:2,county:'ALDER',s1:'MAIN',s2:'OAK'}];
const audit = analyzeBox(links,master,['4821_MAIN_OAK.cbx','4822_OTHER.cbx','4822_OTHER_copy.cbx','export_20260908.cbx','4823_sheet.xlsx']);
assert.deepEqual(audit.folderOnly.map(e=>e.id),['4822']);
assert.equal(audit.folderOnly[0].files.length,2);
assert.equal(audit.have.length,1);
assert.equal(audit.check.length,0);
assert.equal(audit.byId['4822'],undefined); // Candidate files cannot create automatic sheet answers.

'''
        subprocess.run(['node', '-e', js], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
