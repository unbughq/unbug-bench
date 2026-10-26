"""Synthetic metadata only; never queries a worker."""

# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import factory_dashboard as dashboard


class DashboardTest(unittest.TestCase):
    def test_projection_and_missing_data(self):
        hidden = 'SYNTHETIC_PROMPT_MUST_NOT_BE_SERVED'
        data = dashboard.public_remote({
            'prompt': hidden, 'observed_at': 100, 'runner_present': True,
            'usage': {'calls': 12, 'cost': .5, 'configured_model': 'openrouter/xiaomi/mimo-v2.6-pro', 'events': [hidden]},
            'progress': {'stages': {'role:stress_tester': {'status': 'running', 'updated_at': '2026-10-22T08:00:00Z', 'prompt': hidden}, hidden: {}}, 'completed': {}},
            'timing': {'reasoning_seconds': 120, 'reasoning_tokens': 500, 'tools': [
                {'tool': 'bash', 'status': 'completed', 'count': 2, 'seconds': 3, 'input': hidden},
                {'tool': hidden, 'status': 'completed', 'count': 1, 'seconds': 3}]},
            'durability': {'at': 10, 'local_durable': True, 'key': hidden}})
        self.assertNotIn(hidden, json.dumps(data))
        self.assertEqual(data['usage']['calls'], 12)
        self.assertEqual(data['timing']['tools'], [{'tool': 'bash', 'status': 'completed', 'count': 2, 'seconds': 3}])
        self.assertIsNone(dashboard.public_remote({})['usage']['calls'])
        with tempfile.TemporaryDirectory() as directory, patch.object(dashboard, 'ROOT', Path(directory)), patch.object(dashboard, 'run_json', side_effect=RuntimeError('SYNTHETIC_SECRET')):
            result = dashboard.collect({'case': 'case-synthetic', 'worker_id': 'bx_synthetic', 'controller_pid': 1, 'job': 'fixture', 'launched_at': '2026-10-22T08:00:00Z', 'calls': 10, 'cost': .2})
        self.assertIsNone(result['provider'])
        self.assertIsNone(result['controller_running'])
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
