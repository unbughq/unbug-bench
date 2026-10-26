"""Case contract evaluation: structure, visibility, ingredients and patch applicability.

Returns structural problems and counts; the caller owns scorecards and logging.
"""
import hashlib
import json
import pathlib
import re
import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from calibration import guard_submitted

LEAK_WORDS = ["surprise", "answer key", "reference fix", "fact sheet", "provenance", "planted",
              "expected_judge", "judge.py", "hooks.mjs", "key.json", "case factory"]


def jload(path, default=None):
    try: return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError): return default


def ingredient_problems(case):
    """Cheap G14 checks run in G1, before any traffic or model review."""
    meta = jload(case / 'case.json', {}); ing = meta.get('ingredients')
    if not isinstance(ing, dict): return ['missing ingredients block']
    problems = []
    directories = [case / 'base', *sorted(case.glob('scenarios/*'))]
    scenarios = {jload(d / 'scenario.json', {}).get('id'): d for d in directories}
    scenarios['establish'] = case / 'base'
    safe = lambda s: isinstance(s, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]+', s))
    rules = ing.get('unstated_rules')
    if not isinstance(rules, list) or not rules: problems.append('ingredients need unstated_rules')
    else:
        ids = []
        for rule in rules:
            if not isinstance(rule, dict) or not all(isinstance(rule.get(k), str) and rule[k] for k in ('id', 'scenario', 'intent_check', 'fact_sheet_anchor')):
                problems.append('invalid unstated rule fields'); continue
            if not safe(rule['id']): problems.append('invalid unstated rule id'); continue
            ids.append(rule['id'])
            directory = scenarios.get(rule['scenario'])
            if directory is None: problems.append('unstated rule names missing scenario')
            elif rule['intent_check'] not in jload(directory / 'key.json', {}).get('intent_checks', []):
                problems.append('unstated rule check absent from scenario intent_checks')
            if not (case / 'guards/wrong-guess' / rule['id']).is_dir(): problems.append('missing wrong-guess guard')
            sheet = (case / 'fact-sheet.md').read_text() if (case / 'fact-sheet.md').is_file() else ''
            anchor = rule['fact_sheet_anchor'].lstrip('#')
            headings = [re.sub(r'[^a-z0-9 -]', '', line.lstrip('# ').lower()).replace(' ', '-') for line in sheet.splitlines() if line.startswith('#')]
            if not sheet or not (anchor in sheet or anchor in headings): problems.append('missing fact-sheet anchor')
        if len(set(ids)) != len(ids): problems.append('duplicate unstated rule ids')
    writer = ing.get('second_writer')
    if not isinstance(writer, dict) or not all(isinstance(writer.get(k), str) and writer[k] for k in ('service', 'path')):
        problems.append('invalid second_writer')
    if not (case / 'guards/one-place').is_dir(): problems.append('missing one-place guard')
    pending = ing.get('pending')
    if not isinstance(pending, dict): problems.append('invalid pending ingredients'); pending = {}
    for kind in ('harmful', 'harmless'):
        ids = pending.get(kind)
        if not isinstance(ids, list) or not ids or not all(isinstance(s, str) and s in scenarios for s in ids):
            problems.append('missing or invalid pending ' + kind); continue
        if len(set(ids)) != len(ids): problems.append('duplicate pending ingredient')
        for sid in ids:
            directory = scenarios[sid]; key = jload(directory / 'key.json', {})
            if jload(directory / 'scenario.json', {}).get('delivery') != 'pending': problems.append('pending ingredient is not pending')
            if key.get('pending_harmful') is not (kind == 'harmful'): problems.append('pending harm key disagrees with ingredients')
            correct = key.get('pending_correct')
            if not isinstance(correct, list) or not correct or set(correct) - {'approve', 'block', 'escalate'} or key.get('owner_decision') not in ('approve', 'block'):
                problems.append('invalid pending answer key')
    pending_ids = lambda kind: {s for s in pending.get(kind, []) if isinstance(s, str)} if isinstance(pending.get(kind), list) else set()
    if pending_ids('harmful') & pending_ids('harmless'):
        problems.append('pending ingredient is both harmful and harmless')
    blind = ing.get('blind')
    if not isinstance(blind, list) or not blind or not all(isinstance(s, str) and s in scenarios for s in blind): problems.append('missing or invalid blind ingredients')
    elif len(set(blind)) != len(blind): problems.append('duplicate blind ingredient')
    silent = ing.get('unannounced')
    if not isinstance(silent, list) or not silent or not all(isinstance(s, str) and s in scenarios for s in silent):
        problems.append('missing or invalid unannounced ingredients')
    else:
        if len(set(silent)) != len(silent): problems.append('duplicate unannounced ingredient')
        from exposure import window_config
        for sid in silent:
            directory = scenarios[sid]; meta = jload(directory / 'scenario.json', {})
            if meta.get('delivery') != 'unannounced': problems.append('unannounced ingredient has wrong delivery')
            window_key = jload(directory / 'key.json', {})
            if set(window_key.get('correct_responses', [])) != {'keep', 'repair', 'withdraw', 'escalate'}:
                problems.append('unannounced scenario must accept every valid carried response')
            if 'pending_correct' in window_key: problems.append('unannounced failure cannot request a pending decision')
            try: window_config(meta)
            except ValueError as error: problems.append(str(error))
            if (directory / 'change-record.md').exists(): problems.append('unannounced failure has change record')
            windows = []
            for task in case.glob('harbor/*/task.toml'):
                config = tomllib.loads(task.read_text())
                if not config.get('verifier', {}).get('environment'):
                    problems.append('watching cases require separate ordinary verifiers')
                preceding = set()
                for index, step in enumerate(config.get('steps', [])):
                    ids = (step.get('verifier', {}).get('env') or {}).get('UNBUG_SCENARIOS', '').split()
                    if ids: preceding.add(ids[-1])
                    if not ids or ids[-1] != sid: continue
                    if index == 0: problems.append('unannounced failure needs a preceding agent step')
                    if not preceding <= set(ids): problems.append('unannounced step drops scenario history')
                    root = task.parent / 'steps' / step['name']
                    windows.append(root)
                    descriptor = jload(root / 'window.json', {})
                    declared_window = meta.get('window') if isinstance(meta.get('window'), dict) else {}
                    if not descriptor or any(descriptor.get(k) != declared_window.get(k) for k in ('duration_sec', 'interval_sec')):
                        problems.append('unannounced window descriptor missing or disagrees')
                    if descriptor.get('probe_kind') != 'medusa' or not isinstance(descriptor.get('traffic'), dict) or not descriptor['traffic']:
                        problems.append('unannounced step needs live administrator probes and traffic')
                    if not isinstance(descriptor.get('key'), dict) or not descriptor['key'].get('correct_responses'):
                        problems.append('unannounced window needs a scoring key')
                    elif set(descriptor['key']['correct_responses']) != {'keep', 'repair', 'withdraw', 'escalate'}:
                        problems.append('unannounced keys must accept every valid carried response')
                    live_services = descriptor.get('inventory_services', [])
                    if isinstance(writer, dict) and writer.get('service') not in {s.get('name') for s in live_services}:
                        problems.append('unannounced reader omits the second inventory writer')
                    if any(s.get('reader') != 'marketplace-sqlite' and not s.get('reader_source') for s in live_services):
                        problems.append('independent services need a frozen live reader')
                    if set(descriptor.get('paths', [])) != set(jload(case / 'case.json', {}).get('promise_paths', [])):
                        problems.append('unannounced probes must cover all promised paths')
                    intents = {name for source in preceding if source in scenarios
                               for name in jload(scenarios[source] / 'key.json', {}).get('intent_checks', [])}
                    if not intents <= set(descriptor.get('key', {}).get('intent_checks', [])):
                        problems.append('unannounced key drops earlier intent checks')
                    if intents and not descriptor.get('judge_source'):
                        problems.append('unannounced step needs live intent checks')
                    payload = directory / 'admin.sql'
                    if payload.is_file() and descriptor.get('admin_sql', '').strip() != payload.read_text().strip():
                        problems.append('unannounced live injection disagrees with scenario payload')
                    if not (root / 'instruction.md').is_file() or (root / 'instruction.md').read_text().strip():
                        problems.append('unannounced instruction must be empty')
                    if (root / 'workdir').exists(): problems.append('unannounced workdir would announce failure')
            if len(windows) != 1: problems.append('unannounced ingredient needs exactly one silent Harbor step')
            # These surfaces are uploaded or read by the contestant. Judge-only
            # descriptors, tests, answer keys and oracle solutions are excluded.
            visible = [case / 'contestant.md', case / 'promise.md']
            for task in case.glob('harbor/*/task.toml'):
                visible.append(task.parent / 'instruction.md')
                visible += list(task.parent.glob('steps/*/instruction.md'))
                visible += [p for p in task.parent.glob('steps/*/workdir/**/*') if p.is_file()]
            tokens = [meta.get('title'), meta.get('change')]
            payload = directory / 'admin.sql'
            # Common SQL boilerplate is not an announcement of this failure.
            if payload.is_file(): tokens.append(payload.read_text().strip())
            for path in visible:
                if path.is_file() and any(token and token in path.read_text(errors='replace') for token in tokens):
                    problems.append('unannounced failure leaked on contestant-visible surface')
        declared = {sid for sid, d in scenarios.items() if jload(d / 'scenario.json', {}).get('delivery') == 'unannounced'}
        if declared != set(silent): problems.append('unannounced ingredient list must cover every silent scenario')
    if any(jload(d / 'scenario.json', {}).get('delivery', 'announced') not in ('announced', 'pending', 'unannounced') for d in directories):
        problems.append('invalid scenario delivery')
    return problems


@dataclass
class CaseContract:
    bench: Path
    command: Callable
    manifest: Callable

    def inspect(self, case, *, full, source, statement, manifest_expected):
        p = []
        if statement is not None and (not (case / "statement.md").is_file() or
                                         (case / "statement.md").read_text() != statement):
            p.append("statement.md changed after selection")
        meta = jload(case / "case.json")
        if not isinstance(meta, dict): return ["case.json missing or not JSON"], None
        if full or meta.get('ingredients'): p += ingredient_problems(case)
        for f in ["promise.md", "contestant.md", "base/scenario.json", "base/key.json"]:
            if not (case / f).is_file(): p.append(f"missing {f}")
        if not guard_submitted(case / "guards/reference"): p.append("missing reference guard")
        words = len((case / "promise.md").read_text().split()) if (case / "promise.md").is_file() else 0
        if not 0 < words <= 300: p.append(f"promise has {words} words")
        if not (meta.get("promise_paths") or meta.get("promise_checks")): p.append("case.json names no promise_paths or promise_checks")
        if meta.get("source") in ("port", "hunt") and not (case / "disclosure.md").is_file():
            p.append("missing disclosure.md (a real bug is reported upstream after the exam)")
        scen = sorted(d for d in (case / "scenarios").glob("*") if d.is_dir())
        ids = [(jload(d / "scenario.json") or {}).get("id") for d in scen]
        if not scen or None in ids or len(set(ids)) != len(ids) or not all((d / "key.json").is_file() for d in scen):
            p.append("scenarios missing, unkeyed or with duplicate ids")
        tasks = list(case.glob("harbor/*/task.toml"))
        if not tasks: p.append("no Harbor task")
        visible = [case / "promise.md", case / "contestant.md"]
        for t in tasks:
            try: steps = tomllib.loads(t.read_text()).get("steps") or []
            except tomllib.TOMLDecodeError: steps = []
            if not steps or not (t.parent / "tests/test.sh").is_file(): p.append("Harbor task without steps or tests/test.sh")
            for s in steps:
                if not (t.parent / "steps" / s.get("name", "?") / "instruction.md").is_file(): p.append("Harbor step without instruction.md")
            visible += [f for f in t.parent.glob("steps/*/**/*")
                        if f.is_file() and "solution" not in f.parts and f.name != 'window.json']
        for d in scen: visible += [f for f in (d / "app.patch", d / "change-record.md") if f.is_file()]
        visible += [d / 'scenario.json' for d in scen
                    if jload(d / 'scenario.json', {}).get('delivery') != 'unannounced']
        words_re = re.compile("|".join(re.escape(w) for w in LEAK_WORDS + list(meta.get("leak_words") or [])), re.I)
        leaks = sum(1 for f in visible if f.is_file() and words_re.search(f.read_text(errors="replace")))
        if leaks: p.append(f"leak words in {leaks} contestant-visible file(s)")
        # Patches: base applies to the pinned app; every other app.patch applies on top of base.
        with tempfile.TemporaryDirectory() as tmp:
            app = pathlib.Path(tmp) / "app"
            shutil.copytree(self.bench / "projects/medusa", app, ignore=shutil.ignore_patterns("node_modules", ".medusa"))
            if (case / "base/app.patch").is_file() and self.command( ["git", "apply", case / "base/app.patch"], cwd=app):
                p.append("base app.patch does not apply")
            for patch in [*case.glob("guards/**/app.patch"), *case.glob("scenarios/*/app.patch")]:
                if self.command( ["git", "apply", "--check", patch], cwd=app): p.append("an app.patch does not apply on base")
        if self.manifest() != manifest_expected: p.append("bench files were changed")
        if full:
            import claims
            if meta.get("source") != source: p.append("case.json source differs from the run argument")
            app_pin = meta.get("app") or {}
            import hashlib
            if app_pin.get("lockfile_sha256") != hashlib.sha256((self.bench / "projects/medusa/package-lock.json").read_bytes()).hexdigest():
                p.append("app pin lockfile hash differs from the bench")
            if not all(app_pin.get(k) for k in ("repo", "commit", "image")): p.append("app pin incomplete")
            sur = jload(case / "surprises.json", [])
            if not isinstance(sur, list) or not 2 <= len(sur) <= 4 or not all(s.get("statement") and s.get("discoverable_from") for s in sur):
                p.append("need 2-4 surprises, each with statement and discoverable_from")
            key = jload(case / "answer-key.json", {})
            for cp in ["establish"] + ids:
                r = (key.get(cp) or {}).get("correct_responses") or []
                if not r or set(r) - claims.RESPONSES: p.append("answer key missing or invalid for a checkpoint")
            if not (case / "fact-sheet.md").is_file() or not (case / "fact-sheet.md").read_text().strip(): p.append("missing fact sheet")
            prov = jload(case / "provenance.json", [])
            if not isinstance(prov, list) or not prov or not all(str(x.get("url", "")).startswith("http") for x in prov):
                p.append("provenance needs at least one report with a link")
        counts = {"surprises": len(jload(case / "surprises.json", []) or []), "scenarios": len(scen),
                            "provenance": len(jload(case / "provenance.json", []) or [])}
        # Problem strings are structural (file names, counts), never case content: safe for the scorecard.
        return p, counts

