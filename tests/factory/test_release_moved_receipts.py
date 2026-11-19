"""8acb5c: exam receipts recorded under an earlier release folder are relabelled, never otherwise changed."""
import copy, hashlib, json, pathlib, sys, tempfile, types, unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import run
from calibration import completed_attempts, tree_digest

OLD = '/home/user/releases/' + 'b' * 64 + '/factory/exam_responder.py'
MINE = str(pathlib.Path(run.__file__).with_name('exam_responder.py'))
SHA = hashlib.sha256(pathlib.Path(MINE).read_bytes()).hexdigest()


class RelabelTests(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp())
        (self.work / 'logs').mkdir()
        self.c = types.SimpleNamespace(work=self.work)
        self.identity = {'version': 4, 'seed': 7, 'owner': {'files': {MINE: SHA, '/home/user/unbug-bench/x': 'aa'}}}

    def receipt(self, name, key, sha, quarantined=False):
        ws = self.work / name / 'try-1'
        (ws / 'out').mkdir(parents=True)
        (ws / 'out' / 'note.txt').write_text('done')
        identity = copy.deepcopy(self.identity)
        identity['owner']['files'] = {key: sha, '/home/user/unbug-bench/x': 'aa'}
        row = {'try': 1, 'identity': identity, 'workspace': str(ws), 'artifacts': tree_digest(ws),
               'guard_submitted': False, 'guard': None, 'solved': False, 'stop_reason': 'completed'}
        path = self.work / name / ('results-unverified-5.json' if quarantined else 'results.json')
        path.write_text(json.dumps([row]))
        return self.work / name / 'results.json'

    def kept(self, path):
        return completed_attempts(path, self.identity, self.work)

    def test_quarantined_receipt_from_an_earlier_release_verifies_after_relabel(self):
        path = self.receipt('strong_calibrator', OLD, SHA, quarantined=True)
        (path.parent / 'results-unverified-3.json').write_text('[]')   # an older quarantine is not the one restored
        run.adopt_release_moved_receipts(self.c)
        rows = json.loads(path.read_text())
        self.assertEqual(rows[0]['identity']['owner']['files'], self.identity['owner']['files'])
        self.assertEqual(len(self.kept(path)), 1)

    def test_without_relabel_the_same_receipt_is_quarantined(self):
        path = self.receipt('early_probe', OLD, SHA)
        self.assertEqual(self.kept(path), [])

    def test_a_changed_file_or_another_path_is_left_alone_and_still_rejected(self):
        for key, sha in ((OLD, 'c' * 64), ('/tmp/factory/exam_responder.py', SHA)):
            with self.subTest(key=key):
                self.setUp()
                path = self.receipt('early_probe', key, sha)
                before = path.read_text()
                run.adopt_release_moved_receipts(self.c)
                self.assertEqual(path.read_text(), before)
                self.assertEqual(self.kept(path), [])

    def test_a_try_moved_aside_by_a_probe_rerun_is_found_by_its_content(self):
        path = self.receipt('strong_calibrator', OLD, SHA, quarantined=True)
        ws = self.work / 'strong_calibrator' / 'try-1'
        aside = ws.with_name('try-1-interrupted-9')
        ws.rename(aside)
        (ws / 'out').mkdir(parents=True); (ws / 'out' / 'note.txt').write_text('a later rerun')
        (ws.with_name('try-1-interrupted-8') / 'out').mkdir(parents=True)   # a different tree is not taken
        run.adopt_release_moved_receipts(self.c)
        self.assertEqual(json.loads(path.read_text())[0]['workspace'], str(aside))
        self.assertEqual(len(self.kept(path)), 1)


if __name__ == '__main__': unittest.main()
