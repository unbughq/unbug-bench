# Small Claude profile full-suite record

Command: `uv run --with numpy --with scipy python -B tests/run.py`.

Exit: 0

Log: `router-small-claude-suite-20261031T135857Z-a5bc42a0.log`.
SHA-256: `66415b497b6da7fac1f4599130cd0ea5092b37f784b279ed18088195b56d248b`.

Final output:
```
.Unlock diagnostic: stage=decrypt_and_extract; archive=case-20261017T120256Z-86b100; error=RuntimeError
........
----------------------------------------------------------------------
Ran 9 tests in 6.231s

OK

159 test scripts run; 0 failed.
```

Focused maxima module: 24 tests passed (5.992s). Initial focused attempt failed
only because a new assertion looked for route in the usage receipt rather than
the existing card route receipt; corrected test, no production defect.

Scope: offline profiles, saved real usage envelopes and synthetic loopback/runtime
interruption. No live CLI/provider/TLS/account-2 acceptance. No model or
infrastructure spend. No Murphy rows closed. $5 target remains unmet.
