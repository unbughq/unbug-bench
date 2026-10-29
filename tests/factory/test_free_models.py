"""Synthetic transition checks: no credentials, case archives, prompts or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import ast
import copy
import datetime
import json
import pathlib
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import mock

import free_models
import restart
import run
import model_runtime


def rejected(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('unsafe transition accepted')


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    args = SimpleNamespace(max_cost=5, max_total_calls=2000, max_role_calls=400)
    before = {
        'writer': {'model': 'claude/claude-opus-5-5', 'effort': 'high'},
        'stress_tester': {'model': 'opencode-go/mimo-v2.6-pro', 'effort': 'default'},
        'reviewer': {'model': 'opencode-go/muse-spark-1.3-contributor', 'effort': 'xhigh'},
        'strong_calibrator': {'model': 'codex/gpt-6.1-sol', 'effort': 'high'},
        'easy_calibrator': {'model': 'opencode/glm-5.3-flash-free', 'effort': 'default'},
    }
    after = copy.deepcopy(before)
    after['stress_tester'] = {'model': 'opencode/deepseek-v4.1-flash-free', 'effort': 'default'}
    after['reviewer'] = {'model': 'opencode/minimax-m3.1-flash-free', 'effort': 'default'}
    row = {'before': before, 'after': after, 'caps': {'--max-cost': 5, '--max-total-calls': 2000, '--max-role-calls': 400}, 'paused_generation': None, 'opencode_account': 2}
    config = {'expires_utc': '2099-01-01T00:00:00Z', 'cases': {'case-fixture': row}}
    path = root / 'config.json'
    def save(): path.write_text(json.dumps(config))
    save()
    with mock.patch.object(free_models, 'CONFIG', path):
        c = SimpleNamespace(case_id='case-fixture', args=args, card={})
        assert free_models.apply(c, before) == after
        mini = free_models.provider_config('case-fixture', 'opencode/minimax-m3.1-flash-free')
        assert mini['options']['baseURL'] == 'https://opencode.ai/inference/go/openai/v1'
        assert mini['options']['apiKey'] == '{env:OPENCODE_API_KEY}'
        assert mini['whitelist'] == ['minimax-m3.1-flash-free']
        deep = free_models.provider_config('case-fixture', 'opencode/deepseek-v4.1-flash-free')
        assert deep['options'] == {'baseURL': 'https://opencode.ai/inference/openai/v1'}
        # 2026-10-20 founder: new cases use the free models too, on the run's own OpenCode key
        assert free_models.provider_config('case-unrelated', 'opencode/minimax-m3.1-flash-free')['options']['apiKey'] == '{env:OPENCODE_API_KEY}'
        config_paths = []
        try:
            for model in free_models.FREE:
                generated = model_runtime.opencode_config(model, case='case-fixture')
                config_paths.append(generated)
                actual = json.loads(generated.read_text())
                target = model_runtime.PROVIDER_ROUTES.get(model, model)
                assert actual['small_model'] == target
                assert actual['provider']['opencode']['options']['baseURL'] == 'https://opencode.ai/zen/v1'
            assert len(set(config_paths)) == 2  # parallel free roles cannot overwrite each other's route
        finally:
            for generated in config_paths:
                generated.unlink(missing_ok=True)
        assert len({run.family(after[r]['model']) for r in ('writer', 'stress_tester', 'reviewer', 'strong_calibrator')}) == 4
        assert free_models.first_resume('case-fixture', {'roles': before}, args)
        assert not free_models.first_resume('case-fixture', {'roles': after}, args)
        assert free_models.apply(SimpleNamespace(case_id='case-unrelated', args=args), before) == before
        args.max_total_calls = 2400
        rejected(lambda: free_models.selected('case-fixture', args))
        args.max_total_calls = 2000
        after['writer']['model'] = 'opencode/minimax-m3.1-flash-free'; save()
        rejected(lambda: free_models.selected('case-fixture', args))
        after['writer'] = copy.deepcopy(before['writer']); save()
        card = {'case': 'case-fixture', 'status': 'stopped', 'terminal_stop': 'paused', 'roles': before, 'seed': 1,
                'continuation_budget': {'calls': 10, 'cost': .1, 'active': {}, 'events': [], 'terminal_stop': 'PauseRequested'}}
        archive = root / 'case-fixture.checkpoint.tar.gz.age'; archive.write_bytes(b'synthetic ciphertext')
        card['sha256'] = __import__('hashlib').sha256(archive.read_bytes()).hexdigest()
        card_path = root / 'case-fixture.scorecard.json'; card_path.write_text(json.dumps(card))
        flags = '--max-cost 5 --max-total-calls 2000 --max-role-calls 400'
        rejected(lambda: restart.plan(card_path, 0, 600, flags))
        row['paused_generation'] = card['sha256']; save()
        assert restart.plan(card_path, 0, 600, flags) == ('case-fixture', 60, 1)
        rejected(lambda: restart.plan(card_path, 3, 600, flags))
        rejected(lambda: restart.plan(card_path, 0, 600, flags.replace('2000', '2400')))
        rejected(lambda: restart.plan(card_path, 0, 600, flags + ' --max-total-calls=2400'))
        rejected(lambda: restart.plan(card_path, 0, 600, flags + ' --max-cost 50'))
        config['expires_utc'] = '2000-01-01T00:00:00Z'; save()
        rejected(lambda: free_models.selected('case-fixture', args))
    # The deployment patch targets its historical source seams. Current run.py
    # has since gained durable calibration receipts, so use an explicit legacy
    # fixture rather than reverse-patching unrelated modern lifecycle code.
    from free_model_patch import patch
    previous = '''
def pick_models(c):
    families = [family(roles[r]['model']) for r in flags]
def family(model):
    if 'mimo' in model.lower(): return 'xiaomi'
def opencode_config():
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name, delete=False) as staged:
        pass
def opencode(c, model):
    if model:
        alt = FREE_FALLBACK.get(model)
    env = {
"OPENCODE_CONFIG": str(opencode_config()),
    }
def main():
    kept.discard("G3")
    if True:
        for old in []:
                finished = old.name in ('strong_calibrator', 'easy_calibrator') and isinstance(jload(old / 'results.json'), list)
def g1(c):
    return True, {"sentinel": "unchanged"}
'''
    def gates(source):
        return {n.name: ast.dump(n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and __import__('re').fullmatch(r'g\d+', n.name)}
    current = patch(previous)
    assert current != previous and patch(current) == current
    assert gates(previous) == gates(current)
    c = SimpleNamespace(card={'model_transition': {'kind': 'approved-paid-to-free'}})
    with mock.patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=run.BudgetError('provider_limit')) as call:
        try:
            run.opencode(c, ['opencode/glm-5.3-flash-free'], 'synthetic', '.', 'fixture')
        except run.BudgetError:
            pass
        else:
            raise AssertionError('free model failure unexpectedly bypassed')
        assert call.call_count == 1 and not c.card.get('free_model_fallback')
print('PASS bounded role changes, protected Claude/Codex/GLM, distinct families, exact caps, expired/refused pauses, unchanged retry cap and unchanged gate implementations; synthetic only')
