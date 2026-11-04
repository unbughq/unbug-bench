PASS — scoped delta versus c1b2106.

The retained-proof guard propagates capture/recheck failures before ordinary DELETE, preserving immutable evidence. Recovery still requires a successful recheck within the original metering window; independent deadline deletion retains its existing proof-invalidating bypass.

The added tests cover refusal without DELETE and the real Linux wrapper crash/restart seam with resumed-state rejection and valid recovery.

No blocking findings. Read-only review; no tests run.

## Implementer disposition

PASS accepted. The red regression failed before the guard; the full retirement
script passes on Mac (15 tests,2 Linux-only skips) and local Linux (15,no skips).
The c1b2106 suite attempt was canceled at206.530s (exit130) after discovery of this
new replay blocker and is NONQUALIFYING. Its log/metadata remain preserved. One
qualifying full suite follows on the corrected exact final head. No findings
rejected and no previously accepted scope re-reviewed.
