# Fresh goldfish diff review 1

Mode REVIEW; no conversation history; reviewed a7e5fb4 against a9c568e.
Verbatim response:

BLOCKER — `factory/launch.sh:400`: `$ckpt` was rebound to `$UNBUG_LAUNCH_STATE/restore-input.tar.gz.age` at lines 292–293. `prepare_restore()` still requires an archive path inside `source_sealed` (`factory/statement_round.py:54–56`), so every waiting candidate restore fails before allocation.

Preserve and pass the authenticated selected archive path while retaining the frozen transfer archive. Add a candidate launcher-boundary regression that includes the real archive-freezing step; current boundary tests use non-candidate cards and provide the source archive directly.

The frozen rejection/search metadata and authoritative-history changes otherwise resolve the accepted design findings.

## Disposition

Accepted and fixed using the reviewer's specified direction: preserve
admission_archive before freezing ckpt, pass the selected path only to admission,
and keep the frozen ckpt for worker transfer. The new candidate launcher test
executes the real freeze and admission blocks: it failed with the observed
archive-membership refusal before this correction and passes afterward. All
seven restore-context regressions and legacy statement tests are rerun below.
No finding rejected, no validation weakened, no live source changed or replay
made. Recovery of the preserved failed operation remains separate work.

Verification after accepted correction: 7 new context regressions passed; 18
legacy statement-round tests passed. Adjacent batch-launch integration passed
8 tests and freshness-restore checks passed 21 tests before the archive-path
correction. Full exact-head suite follows this commit; no live qualification.
