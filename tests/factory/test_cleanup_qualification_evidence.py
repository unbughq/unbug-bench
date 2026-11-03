"""Validate retained, sanitized real VM observations; grants no launch authority."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'docs/reports/stream-b-cleanup-qualification-20261031'
sys.path.insert(0, str(ROOT / 'factory'))
import deployment_inventory as inventory
# Validate the historical producer's literal schema, not today's launch environment.
PROBE_ENVIRONMENT = ast.literal_eval(next(node.value for node in
    ast.parse((BASE / 'probe.py').read_text()).body if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == 'environment' for target in node.targets)))

# The embedded scanner produced this retained observation before settlement existed.
SCANNER_SOURCE = ast.literal_eval(ast.parse((BASE / 'probe.py').read_text()).body[0].value)
PROBE_STATUSES = ast.literal_eval(next(node.value for node in ast.parse(SCANNER_SOURCE).body
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
    and target.id == 'STATUSES' for target in node.targets)))

UNITS = ('unbug-key-holder.service', 'unbug-resume-launches.timer',
         'unbug-resume-launches.service', 'unbug-model-router.service', 'unbug-batch.service')
EXIT = ('ok', 'command-failed', 'timeout', 'malformed-output', 'read-failed')
ERRORS = (*EXIT[1:], 'unsupported-file', 'units-not-inactive')


def keys(value, expected):
    assert isinstance(value, dict) and set(value) == set(expected)


def enum(value, allowed):
    assert isinstance(value, str) and value in allowed


def number(value):
    assert type(value) is int and value >= 0


def boolean(value):
    assert type(value) is bool


def pattern(value, regex):
    assert isinstance(value, str) and re.fullmatch(regex, value)


def digest(value, nullable=False, size=64):
    if nullable and value is None: return
    pattern(value, '[0-9a-f]{' + str(size) + '}')


def stamp(value, utc=False):
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    if utc: assert parsed.utcoffset() == timedelta(0)


def labels(value, allowed):
    assert isinstance(value, list) and value == sorted(set(value))
    for item in value: enum(item, allowed)


def metadata(value):
    assert isinstance(value, dict)
    enum(value['state'], ('missing', 'error', 'present'))
    if value['state'] != 'present': keys(value, ('state',)); return
    keys(value, ('state', 'type', 'size', 'mtime_ns'))
    enum(value['type'], inventory.TYPES)
    number(value['size']); number(value['mtime_ns'])


def validate_scanner(value):
    keys(value, ('schema', 'observed_at', 'activation_authorized', 'snapshot_atomic',
                 'outstanding_proofs', 'launches', 'ledger', 'sources', 'errors'))
    assert type(value['schema']) is int and value['schema'] == 1
    assert value['activation_authorized'] is False and value['snapshot_atomic'] is False
    stamp(value['observed_at'], True)
    assert value['outstanding_proofs'] == ['historical-provenance', 'controller-ownership', 'provider-creation-deletion', 'cumulative-cost']
    labels(value['errors'], ('invalid-root', 'launch-scan-error', 'ledger-invalid', 'source-scan-error'))
    keys(value['sources'], inventory.SOURCES)
    for row in value['sources'].values():
        enum(row['state'], ('ok', 'missing', 'unsupported', 'changed', 'error'))
        keys(row, ('state', 'sha256') if row['state'] == 'ok' else ('state',))
        if row['state'] == 'ok': digest(row['sha256'])
    launches = value['launches']; keys(launches, ('state', 'invalid_entries', 'items'))
    enum(launches['state'], ('ok', 'error', 'missing')); number(launches['invalid_entries'])
    assert isinstance(launches['items'], list)
    ids = []
    for row in launches['items']:
        keys(row, ('id', 'state', 'files', 'creations', 'creation_counts', 'unknown_entries', 'deleted_markers', 'parked_markers', 'keep_markers'))
        pattern(row['id'], '[0-9a-f]{32}'); ids.append(row['id'])
        enum(row['state'], ('ok', 'error')); number(row['unknown_entries'])
        keys(row['files'], inventory.FILES)
        for v in row['files'].values(): metadata(v)
        for name, allowed in [('creation_counts', inventory.LABELS), *[(n, inventory.TYPES) for n in ('deleted_markers', 'parked_markers', 'keep_markers')]]:
            keys(row[name], allowed)
            for v in row[name].values(): number(v)
        assert isinstance(row['creations'], list)
        for v in row['creations']:
            keys(v, ('serial', 'label', 'response', 'intent')); pattern(v['serial'], '[0-9]+')
            enum(v['label'], inventory.LABELS); metadata(v['response']); metadata(v['intent'])
    assert ids == sorted(set(ids))
    ledger = value['ledger']
    keys(ledger, ('state', 'counts', 'reserved_usd', 'expired_reserved', 'malformed_records', 'unknown_statuses'))
    enum(ledger['state'], ('missing', 'invalid', 'ok')); keys(ledger['counts'], PROBE_STATUSES)
    for v in ledger['counts'].values(): number(v)
    for k in ('expired_reserved', 'malformed_records', 'unknown_statuses'): number(ledger[k])
    if ledger['reserved_usd'] is not None:
        pattern(ledger['reserved_usd'], r'[0-9]+(?:\.[0-9]+)?')
        assert Decimal(ledger['reserved_usd']) >= 0


def validate(value):
    keys(value, ('schema', 'observed_at', 'activation_authorized', 'snapshot_atomic', 'scanner',
                 'scanner_sha256', 'units', 'unit_file_sha256', 'policy_sha256', 'staged_release_sha256',
                 'locks', 'legacy', 'fleet', 'cli', 'errors'))
    assert type(value['schema']) is int and value['schema'] == 1
    assert value['activation_authorized'] is False and value['snapshot_atomic'] is False
    stamp(value['observed_at'], True); validate_scanner(value['scanner']); digest(value['scanner_sha256'])
    keys(value['units'], UNITS); keys(value['unit_file_sha256'], UNITS)
    for row in value['units'].values():
        keys(row, ('active', 'enabled')); enum(row['active'], ('inactive', 'active', 'failed', 'unknown'))
        enum(row['enabled'], ('enabled', 'disabled', 'static', 'masked', 'not-found', 'unknown'))
    for v in value['unit_file_sha256'].values(): digest(v, True)
    for k in ('policy_sha256', 'staged_release_sha256'): digest(value[k], True)
    keys(value['locks'], [r['id'] for r in value['scanner']['launches']['items']])
    for v in value['locks'].values(): enum(v, ('free', 'busy', 'missing', 'error', 'skipped-units-active'))
    legacy = value['legacy']; keys(legacy, ('metadata', 'launch', 'git'))
    keys(legacy['metadata'], (*inventory.SOURCES, 'directory', 'launch.json', 'controller.lock'))
    for row in legacy['metadata'].values():
        if row is None: continue
        keys(row, ('mtime_ns', 'ctime_ns', 'btime_ns')); number(row['mtime_ns']); number(row['ctime_ns'])
        if row['btime_ns'] is not None: number(row['btime_ns'])
    row = legacy['launch']; keys(row, ('cloud', 'type', 'argv', 'environment_present', 'unknown_environment_keys'))
    enum(row['cloud'], ('boat', 'hetzner', 'absent', 'other'))
    enum(row['type'], ('small', 'default', 'large', 'xlarge', 'absent', 'other')); enum(row['argv'], ('launch', 'other'))
    keys(row['environment_present'], PROBE_ENVIRONMENT)
    for v in row['environment_present'].values(): boolean(v)
    boolean(row['unknown_environment_keys'])
    row = legacy['git']; keys(row, ('head', 'reflog', 'exit_label')); digest(row['head'], True, 40); enum(row['exit_label'], EXIT)
    assert isinstance(row['reflog'], list) and len(row['reflog']) <= 100
    for v in row['reflog']:
        keys(v, ('commit', 'committed_at')); digest(v['commit'], size=40); stamp(v['committed_at'])
    row = value['fleet']; keys(row, ('readable', 'page_complete', 'worker_ids', 'exit_label'))
    boolean(row['readable']); boolean(row['page_complete']); enum(row['exit_label'], EXIT)
    assert isinstance(row['worker_ids'], list) and row['worker_ids'] == sorted(set(row['worker_ids']))
    for v in row['worker_ids']: pattern(v, '[A-Za-z0-9_-]+')
    if not row['readable']: assert row['page_complete'] is False and row['worker_ids'] == []
    row = value['cli']; keys(row, ('version', 'sha256', 'format', 'exit_label'))
    if row['version'] is not None: pattern(row['version'], r'[0-9]+\.[0-9]+\.[0-9]+')
    digest(row['sha256'], True); enum(row['format'], ('elf', 'macho', 'source', 'other', 'missing')); enum(row['exit_label'], EXIT)
    labels(value['errors'], ERRORS)


class EvidenceTests(unittest.TestCase):
    def setUp(self): self.observed = json.loads((BASE / 'observations.json').read_text())

    def test_real_observation_contract_and_embedded_scanner(self):
        validate(self.observed)
        tree = ast.parse((BASE / 'probe.py').read_text())
        source = ast.literal_eval(tree.body[0].value).encode()
        self.assertEqual(hashlib.sha256(source).hexdigest(), self.observed['scanner_sha256'])

    def test_extra_keys_rejected_at_every_retained_object(self):
        def paths(value, trail=()):
            if isinstance(value, dict):
                yield trail
                for k, v in value.items(): yield from paths(v, (*trail, k))
            elif isinstance(value, list):
                for k, v in enumerate(value): yield from paths(v, (*trail, k))
        for trail in paths(self.observed):
            altered = deepcopy(self.observed); target = altered
            for k in trail: target = target[k]
            target['unexpected-output'] = 'must never be emitted'
            with self.subTest(path=trail), self.assertRaises(AssertionError): validate(altered)

    def test_arbitrary_enums_ids_hashes_are_rejected(self):
        for trail in [('legacy', 'launch', 'cloud'), ('cli', 'version'), ('cli', 'format'),
                      ('scanner_sha256',), ('units', UNITS[0], 'active'),
                      ('scanner', 'launches', 'items', 0, 'id')]:
            altered = deepcopy(self.observed); target = altered
            for k in trail[:-1]: target = target[k]
            target[trail[-1]] = 'unrestricted text'
            with self.subTest(path=trail), self.assertRaises(AssertionError): validate(altered)
        altered = deepcopy(self.observed); altered['fleet']['worker_ids'] = ['bad/id']
        with self.assertRaises(AssertionError): validate(altered)

    def test_provenance_refusal_matches_real_timestamps(self):
        proof = json.loads((BASE / 'provenance.json').read_text())
        keys(proof, ('sources', 'directory_timestamp_consistent', 'execution_binding',
                     'intact_history', 'cloud_known', 'verdict'))
        keys(proof['sources'], inventory.SOURCES)
        meta = self.observed['legacy']['metadata']
        for path, row in proof['sources'].items():
            keys(row, ('observed_sha256', 'matches', 'ctime_before_launch'))
            digest(row['observed_sha256'], True)
            self.assertEqual(row['observed_sha256'], self.observed['scanner']['sources'][path].get('sha256'))
            assert isinstance(row['matches'], list)
            for match in row['matches']:
                keys(match, ('commit', 'blob')); digest(match['commit'], size=40); digest(match['blob'], size=40)
            self.assertEqual(row['ctime_before_launch'], meta[path]['ctime_ns'] < meta['launch.json']['mtime_ns'])
        latest = max(meta[k][v] for k in ('launch.json', 'controller.lock') for v in ('mtime_ns', 'ctime_ns'))
        self.assertEqual(proof['directory_timestamp_consistent'],
                         all(meta['directory'][v] <= latest for v in ('mtime_ns', 'ctime_ns')))
        for k in ('execution_binding', 'intact_history', 'cloud_known'): boolean(proof[k])
        self.assertFalse(proof['execution_binding']); self.assertFalse(proof['intact_history'])
        self.assertEqual(proof['verdict'], 'unresolved')

    def test_retained_contracts_hashes(self):
        records = json.loads((BASE / 'contracts/sources.json').read_text())
        self.assertEqual(len(records), 9)
        urls = []
        for folder in ('stream-b-provider-contract-20261031', 'stream-b-cost-contract-20261031'):
            old = json.loads((ROOT / 'docs/reports' / folder / 'sources.json').read_text())
            urls += [r['url'] for r in (old['sources'] if isinstance(old, dict) else old)]
        self.assertEqual([r['url'] for r in records], urls)
        for r in records:
            self.assertEqual(hashlib.sha256((ROOT / r['old_file']).read_bytes()).hexdigest(), r['old_sha256'])
            if r['status'] != 'unavailable':
                self.assertEqual(hashlib.sha256((ROOT / r['file']).read_bytes()).hexdigest(), r['new_sha256'])


if __name__ == '__main__': unittest.main()
