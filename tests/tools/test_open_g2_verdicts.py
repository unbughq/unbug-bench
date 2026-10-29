"""Run the founder diagnosis on synthetic tar streams; no real keys or network."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT/'tools/open-g2-verdicts.py'


class DiagnosisTests(unittest.TestCase):
    def test_one_prompt_streaming_extraction_and_unresolved_projection(self):
        api = runpy.run_path(str(SCRIPT))
        main = api['main']; globals_ = main.__globals__
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); output = home/'private'/'g2-open'; output.parent.mkdir()
            fake_age = home/'fake-age'
            # Simulate age's streaming interface. Identity is consumed from stdin
            # and discarded; stdout contains only our synthetic tar fixture.
            fake_age.write_text('#!/usr/bin/env python3\nimport sys,shutil\n'
                "assert sys.argv[1:4] == ['-d','-i','/dev/stdin']\n"
                'assert sys.stdin.buffer.read()\n'
                "with open(sys.argv[4],'rb') as source: shutil.copyfileobj(source,sys.stdout.buffer)\n")
            fake_age.chmod(0o700)
            cases = []
            for short in ('e15450', '873d7f'):
                case = 'case-synthetic-'+short
                bundle = home/('unbug-bench-'+short+'-restore-14-20261029')
                (bundle/'sealed').mkdir(parents=True)
                rows = [dict(who='builder', query='synthetic query '+str(i),
                    url='https://example.test/duplicate', hit=True, app_version='2.19.0') for i in range(3)]
                answers = [dict(url=r['url'], resolved=True, same_bug=False,
                    retrieved=True, app_version='2.19.0', version_scope='synthetic applicability',
                    retrieved_from='live', why='synthetic exclusion') for r in rows]
                answers[1].update(resolved=False, same_bug=None, retrieved=False,
                    archive_checked=True, archive_available=None, why='synthetic archive timeout')
                # A superficially resolved answer with the wrong pinned version
                # is unresolved by the factory validator too.
                answers[2]['app_version'] = '9.9.9'
                review = 'g2-confirm-123'
                files = {'case/case.json':json.dumps({'app':{'version':'2.19.0', 'commit':'a'*40}}),
                    'case/statement.md':'# Synthetic bug\n\nSynthetic reservation race breaks the promise.\n',
                    'case/freshness.jsonl':'\n'.join(map(json.dumps, rows)),
                    review+'/verdict.json':json.dumps({'hits':answers}),
                    review+'/review-completed.json':'{}', '.casekey':'fixture-key-material-omitted'}
                for name in ('case.json', 'statement.md', 'freshness.jsonl'):
                    files[review+'/case/'+name] = files['case/'+name]
                archive = bundle/'sealed'/(case+'.checkpoint.tar.gz.age')
                with tarfile.open(archive, 'w:gz') as tar:
                    for name, content in files.items():
                        data = content.encode(); member = tarfile.TarInfo(case+'/'+name); member.size=len(data)
                        tar.addfile(member, io.BytesIO(data))
                digest = hashlib.sha256(archive.read_bytes()).hexdigest(); cases.append((case, digest))
                card = dict(sha256=digest, admission_freshness={'unresolved_hits':2})
                if short == '873d7f': card['loop_freshness']={'verdict_path':review+'/verdict.json'}
                (bundle/'sealed'/(case+'.scorecard.json')).write_text(json.dumps(card))
            with patch.dict(globals_, ROOT=home/'factory-checkout', OUT=output, CASES=cases), \
                 patch.object(api['shutil'], 'which', return_value=str(fake_age)), \
                 patch.object(api['getpass'], 'getpass', return_value='AGE-SECRET-KEY-1SYNTHETIC') as prompt, \
                 patch.object(api['sys'], 'stdin', types.SimpleNamespace(isatty=lambda:True)), \
                 contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(main(), 0)
                self.assertEqual(prompt.call_count, 1)
                # Rerun refuses to replace private evidence, before prompting.
                with contextlib.redirect_stderr(io.StringIO()): self.assertEqual(main(), 1)
                self.assertEqual(prompt.call_count, 1)
            text = (output/'summary.md').read_text()
            self.assertEqual(text.count('Unresolved rows: 2'), 2)
            self.assertIn('synthetic query 1', text)
            self.assertIn('synthetic query 2', text)
            self.assertNotIn('synthetic query 0', text)
            self.assertIn('Synthetic reservation race', text)
            self.assertIn('2.19.0', text)
            self.assertNotIn('synthetic archive timeout', stdout.getvalue())
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output/'summary.md').stat().st_mode & 0o777, 0o600)
            for case, _ in cases:
                self.assertEqual((output/case).stat().st_mode & 0o777, 0o700)
                self.assertFalse((output/case/'.casekey').exists())


if __name__ == '__main__': unittest.main()
