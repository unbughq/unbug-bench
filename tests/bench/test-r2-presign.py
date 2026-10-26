#!/usr/bin/env python3
"""bin/r2-presign matches AWS's published SigV4 query-string example (S3 docs, 'Authenticating Requests: Using Query
Parameters'): GET examplebucket/test.txt, 86400 s, 2013-05-24T00:00:00Z, us-east-1."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import datetime, importlib.machinery, importlib.util, pathlib
path = (_BENCH_ROOT / "bin" / 'r2-presign')
spec = importlib.util.spec_from_loader("r2", importlib.machinery.SourceFileLoader("r2", str(path)))
r2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(r2)
url = r2.presign("GET", "test.txt", 86400, None, "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "",
                 now=datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc), host="examplebucket.s3.amazonaws.com", region="us-east-1")
assert url.endswith("X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"), url
assert "X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request" in url
print("PASS r2-presign signs exactly like AWS's published SigV4 example")
