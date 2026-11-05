"""Authored local router/context fixture for retained scientific retry checks."""
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import exam_responder
import model_router
import model_runtime
import run
from router_test_support import offline_router, synthetic_maximum
from test_stream_d import cards


class Killed(BaseException): pass

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.patch(run, 'BENCH', ROOT)
        router, self.store = offline_router(); self.addCleanup(router.close)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.case = self.work / 'case'; self.case.mkdir()
        (self.work / 'transcripts').mkdir()
        practice = json.loads(gzip.decompress((ROOT / 'tests/factory/fixtures/invalid-runs-practice.json.gz').read_bytes()))
        for name, value in practice['files'].items():
            data = value.encode()
            self.assertEqual(hashlib.sha256(data).hexdigest(), practice['sha256'][name])
            target = self.case / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        # A genuine ledger already beyond the old $5 priced-provider cap.
        self.source = next(row['card'] for row in cards() if row['card']['case'].endswith('5813be'))
        self.ledger = self.work / 'ledger.json'; self.ledger.write_text(json.dumps(self.source['continuation_budget']))
        self.channel = json.loads((ROOT / 'tests/fixtures/factory/stream-d/job-money.json').read_text())
        self.channel.update(case=self.source['case'], source_generation=self.source['sha256'])
        args = run.argument_parser().parse_args(['--source', 'hunt', '--batch-release-sha256', 'a' * 64])
        writer, stress, reviewer, strong = ('claude/claude-opus-5-5', 'opencode/minimax-m3.1-flash-free',
                                           'openrouter/deepseek/deepseek-v4.1-flash', 'codex/gpt-6.1-sol')
        self.c = c = run.Ctx()
        vars(c).update(work=self.work, case=self.case, ledger=self.ledger, args=args,
            case_id=self.source['case'], seed=7, manifest0='public-practice-control-flow', role_cancel=threading.Event(),
            card={'case': self.source['case'], 'builder_rounds': 0, 'roles': {
                role: {'model': model} for role, model in zip(('writer', 'stress_tester', 'reviewer', 'strong_calibrator'),
                                                             (writer, stress, reviewer, strong))}},
            models={'builder': [writer], 'attacker': [stress], 'reviewers': [[reviewer]], 'strong_calibrator': [strong]},
            job_money=self.channel, authenticated_job_config={'job_money': copy.deepcopy(self.channel), 'batch_release_sha256': args.batch_release_sha256},
            authenticated_batch_manifest={'id': self.channel['batch'], 'batch_deadline': self.channel['batch_deadline']},
            batch_id=self.channel['batch'], job_id=self.channel['job'], batch_deadline=self.channel['batch_deadline'],
            source_generation=self.channel['source_generation'])
        # These tests isolate writer/accounting receipt behavior. Category coverage
        # is exercised with real orchestration in test_stream_d_retries.py.
        def single_stress(c, number, report, receipt, completed):
            return run.pending_call(c, c.models['attacker'], run.stress_request(c, number, report),
                c.work, f'attacker-{number}', receipt, role='stress_tester', on_complete=completed)
        self.patch(run, 'stress_categories', single_stress)
        self.baseline = budget.case_spending(self.source['continuation_budget'])['total_spent_usd']
        self.patch(model_router, 'metadata', return_value=(c.batch_id, c.job_id, model_router.epoch(c.batch_deadline)))
        bounds = {'requests': 1, 'input_tokens': 1000, 'output_tokens': 1000, 'tool_fees_usd': '0'}
        from token_prices import invocation_maximum
        configured = {model: {**synthetic_maximum(model), 'max_usd': float(invocation_maximum(model, bounds))}
                      for model in (writer, stress, reviewer, strong)}
        # Accounting/control-flow only: these synthetic bounds do not qualify a route.
        self.bounds = patch.object(model_router, 'route_maximum', configured.get)
        self.bounds.start(); self.addCleanup(self.bounds.stop)

    def patch(self, target, name, *args, **kwargs):
        patched = patch.object(target, name, *args, **kwargs)
        value = patched.start(); self.addCleanup(patched.stop); return value
