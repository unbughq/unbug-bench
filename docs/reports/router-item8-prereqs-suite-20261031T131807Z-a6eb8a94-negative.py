"""Offline negative control: intentionally restore the broken shutdown lookup."""
import importlib.util
import inspect
from pathlib import Path
import textwrap
import unittest

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('maxima', root/'tests/factory/test_model_call_maxima.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
source = textwrap.dedent(inspect.getsource(m.gate.Allowance.close))
old = 'if connected_socket: connected_socket.shutdown(socket.SHUT_RDWR)'
assert old in source
source = source.replace(old, 'if connection.sock: connection.sock.shutdown(socket.SHUT_RDWR)')
namespace = dict(m.gate.__dict__)
exec(compile(source, '<negative-control-close>', 'exec'), namespace)
m.gate.Allowance.close = namespace['close']

class NegativeControl(m.ProtocolTests):
    def test_detached_response(self):
        self.upstream.RequestHandlerClass.protocol_version = 'HTTP/1.1'
        self._runtime_close_mid_response_retains_hold_once(True)

result = unittest.TextTestRunner(verbosity=2).run(NegativeControl('test_detached_response'))
raise SystemExit(0 if result.wasSuccessful() else 1)
