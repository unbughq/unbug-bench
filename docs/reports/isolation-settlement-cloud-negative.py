"""Negative control: in-memory socket-shutdown deletion, never edits production."""
import importlib.util
import inspect
from pathlib import Path
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('qualification', ROOT / 'tests/factory/test_model_call_maxima.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
gate = module.gate
source = textwrap.dedent(inspect.getsource(gate.Allowance.close))
needle = 'if connected_socket: connected_socket.shutdown(socket.SHUT_RDWR)'
assert source.count(needle) == 1
scope = dict(vars(gate))
exec(source.replace(needle, 'pass  # negative control: omit retained socket shutdown'), scope)
gate.Allowance.close = scope['close']
original = module.ProtocolTests._runtime_close_mid_response_retains_hold_once

def one_variant(self, close_header, **kwargs):
    if close_header:
        return original(self, close_header, **kwargs)

module.ProtocolTests._runtime_close_mid_response_retains_hold_once = one_variant
suite = unittest.TestSuite([module.ProtocolTests('test_real_process_tls_cancellation_settles_unknown_once')])
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
