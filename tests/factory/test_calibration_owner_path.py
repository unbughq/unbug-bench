"""new-calibration-owner-path-1: a plumbing release installs the factory under a new
/home/user/releases/<hash>/, and calibration_identity keys the exam owner's files by that path. Finished
strong tries must survive it (f46dac-h9 G11, 2026-11-21: all three quarantined, G11 found no pass)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import calibration


def ident(release, slot=0, responder='bbada7'):
    return {'version': 4, 'slot': slot, 'bench': {'runner': {}, 'files': {}}, 'owner': {'model': ['m'], 'effort': 'default', 'files': {
        f'/home/user/releases/{release}/factory/exam_responder.py': responder,
        '/home/user/unbug-bench/harbor/responder/responder.py': 'd159', '/home/user/unbug-bench/harbor/responder/ask-human': 'dca7'}}}


a = ident('147a717c')
assert calibration.compatible_identity(a, ident('70b673f3')), 'a release path alone must not break identity'
assert calibration.compatible_identity(a, ident('70b673f3', slot=1)), 'slot rule still applies'
assert not calibration.compatible_identity(a, ident('70b673f3', responder='other')), 'changed bytes still break it'
twins = ident('x'); twins['owner']['files']['/elsewhere/exam_responder.py'] = 'zz'
assert not calibration.compatible_identity(twins, ident('y')), 'two files of one name keep strict paths'
blind = {'version': 4, 'slot': 0, 'bench': {'runner': {}, 'files': {}}}
assert calibration.compatible_identity(blind, dict(blind)) and not calibration.compatible_identity(blind, {**blind, 'version': 5})
print('PASS calibration identity survives a release path change, not a byte change')
