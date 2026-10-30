**PASS: 0 blockers, 0 majors, 1 optional nit.** The fix refuses a bad `binding` before any lease, reservation or history is created. The new test catches removal of the guard, and nothing else changed. I wrote nothing to the worktree; all my runs used a `git archive 9ec3a12` export in my scratchpad.

Text ready to save as `docs/reviews/stream-d-diff-30.md`:

---

# Review: stream-d diff 30. PASS (0 blockers, 0 majors, 1 nit)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`, no history. Personas: zoom_out, implementation_readiness. Standards: zoom-out, implementation-readiness.

**Scope:** `ea2e9cd..9ec3a12`, one commit, "Reject incomplete extension receipts before reservation". The change skipped step 2 under ENGINEERING's small-fix exception, so it is reviewed against the commit message and the existing passed design `docs/designs/stream-d-extension-admission.md`. `.stream-d-next/` was excluded.

**Changed lines** (`git diff --numstat`):

| File | Added | Removed |
|---|---|---|
| `factory/run.py` | 1 | 0 |
| `tests/factory/test_stream_d_admission.py` | 7 | 0 |
| `docs/designs/stream-d-extension-admission.md` | 8 | 1 |
| `docs/reviews/stream-d-diff-29.md` | 9 | 0 |

Nothing was removed from code or tests.

**Read:** `docs/ENGINEERING.md`; the persona files; review 29 verbatim, including the elephant resolution and the N1 correction note; `run.pending_call` (`run.py:323–383`); the admission test harness (`call`, `refuse`, `assert_unadmitted`) and the new test; and the binding consumers in `run.py` (`admitted()`, and the resume validation at lines 1121–1124).

## Findings

### The fix is placed correctly

`not isinstance(receipt.get('binding'), dict)` is added at `run.py:337`, inside the `if extension_proposal is not None:` receipt contract. That contract runs:
- after `resume_provider_wait` and `job_authority.for_case`;
- before `copy.deepcopy`, both calls to `verify_proposal`, `await_lease`, the UUID, `reserve_invocation`, `extensions.admit` and `admitted()`.

So a missing or non-dictionary binding is now refused as `extension_reservation_mismatch` before anything durable is created. Before this fix, `admitted()` raised `KeyError('binding')` after `admit` had published history (diff-29 N1). That root cause is now closed: `admitted()` is the only consumer of `receipt['binding']` on this path, and it can no longer be reached without a dictionary.

### Ordinary and stress callers are unchanged

- The guard sits only in the extension branch. Callers that pass no `extension_proposal` never evaluate it.
- Admission order is unchanged: guard order 1–8 from review 29, `on_admitted` placement, and the `except`/`finally` blocks.
- No other line in `factory/` changed.

### The test proves the claim

`test_missing_or_nondictionary_binding_refuses_before_admission` uses the existing `refuse` harness on five receipts: one with `binding` absent, and four with `binding` set to `None`, `[]`, `''` and `False`. For each one, `refuse` asserts:
- `await_lease` is patched to raise, so no lease is ever requested;
- the ledger bytes are unchanged, so there is no reservation;
- there is no `extension-history.json` and no `extension-snapshots/`;
- there is no `attack-state.json`;
- `builder_rounds == 0`;
- there are no callbacks and no writer calls.

### Mutation results (run by me on the export)

| Mutant | Result |
|---|---|
| Remove the new guard line | **Killed.** `AssertionError: lease before verification` on the missing-binding case. |
| Weaken the guard to `'binding' not in receipt` | **Killed.** Four subtest failures: `None`, `[]`, `''`, `False`. |

The test therefore checks the type, not just that the key is present.

### Records

- The design clarification matches the code.
- The N1 correction note in review 29 makes no new readiness or row-closure claim.
- N2 stays deferred, as review 29 allowed.

## Nits

### N1. `{}` and dictionaries of the wrong shape are admitted (optional)

- **What happens:** the guard accepts any dictionary. A `binding` of `{}`, or one whose keys differ from `attack_binding(c)`, passes admission and hashes fine in `admitted()`. Resume validation (`run.py:1121–1124`, `set(receipt["binding"]) != set(attack_binding(c))`) would reject it later, after an extension ID has been used.
- **Why it's only a nit:** there is no production caller. The writer-loop producers build `binding` from `attack_binding(c)`. Review 29 offered "dictionary (or the exact producer shape)" as acceptable.
- **Optional fix:** when the caller is wired, either compare the key set with `attack_binding(c)` before the lease, or have the wiring increment's test cover a producer-built binding.

## Validation boundary

**Ran** (Python 3.14.6, macOS, on the export of `9ec3a12`):
- `python3 -B -m unittest tests.factory.test_stream_d_admission`: 19 tests, OK, 4.7 s.
- `python3 -B -m unittest tests.factory.test_stream_d_runtime tests.factory.test_stream_d_extensions`: 37 tests, OK, 19.1 s.
- The 2 mutants above, both killed.

**Did not run:**
- The full suite. The parent's run on `9ec3a12` (`/tmp/stream-d-admission-binding-suite.log`) is pending, and no result is claimed here.
- The parent's focused log `/tmp/stream-d-admission-binding-focused.log` was not reproduced.
- The earlier 14/15 mutants from review 29 were not re-run.

**Not qualified:** active continuation (B1 remainder), B2 comparison isolation, M5 scientific receipts and M6 routing all remain open. There is no production extension caller, `DIAGNOSIS_ENABLED` is unchanged, and no Murphy row closes.

**Other:** no model, cloud or launch calls; no decryption; no secrets; no writes, commits or merges to the worktree or the parent checkout.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

Accepted PASS. Optional N1 is carried into the wiring test obligation: the
controller must use a producer-built `attack_binding(c)` and prove its receipt
survives the real continuation reader. No broader receipt-shape validator is
added to this unwired one-line fix. The tested dictionary guard and fresh-UUID
intent remain unchanged. No finding is rejected, no Murphy row closes, and
active continuation/B2/M5/M6 remain open. The full-suite result is pending.

## Elephant full-suite result

The prescribed `uv run --with numpy --with scipy python -B tests/run.py`
completed on the reviewed `9ec3a12` source: **152 scripts, 0 failed**, exit 0.
Only documentation changed during the run. Launch guards passed, so no isolated
rerun was needed. Log: `/tmp/stream-d-admission-binding-suite.log`, SHA-256
`8e92703d786f7eddefda1ee97f29e27c276771b6748a08c9d37d27f48631fb32`.
Together with fresh Claude diff review 30, this passes the binding correction.
No Murphy row closes; the unwired and live-qualification boundaries above remain.
