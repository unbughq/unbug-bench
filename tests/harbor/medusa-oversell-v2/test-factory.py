#!/usr/bin/env python3
"""Every phase-2 case needs an unannounced ingredient, including public fixtures."""
import importlib.util, json, os, pathlib, sys
from types import SimpleNamespace
from unittest.mock import patch
ROOT = pathlib.Path(__file__).resolve().parents[3]
os.environ['BENCH'] = str(ROOT)
sys.path.insert(0, str(ROOT / 'factory'))
spec = importlib.util.spec_from_file_location('practice_factory', ROOT / 'factory/run.py')
factory = importlib.util.module_from_spec(spec); spec.loader.exec_module(factory)
c = SimpleNamespace(case=ROOT / 'cases/medusa-oversell-v2', args=SimpleNamespace(source='fixture'))
import case_contract
assert case_contract.ingredient_problems(c.case) == []
original = case_contract.jload
path = c.case / 'case.json'
empty = original(path); empty['ingredients']['unannounced'] = []
for source in ['fixture', 'plant']:
    c.args.source = source
    with patch.object(case_contract, 'jload', lambda p, *args: empty if p == path else original(p, *args)):
        assert 'missing or invalid unannounced ingredients' in case_contract.ingredient_problems(c.case)
print('factory: nonempty unannounced list required for public fixtures and scored cases')
