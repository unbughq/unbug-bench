**PASS.** The three earlier blocking findings (1–3) are fixed, and I found no new blocking problem. The scope can be built as written: one helper in `factory/extensions.py`, an intent write inside `pending_call`, and the existing admission tests. Only nits are left.

I reviewed the revised `docs/designs/stream-d-extension-receipt-routing.md` (uncommitted) against `factory/extensions.py`, `factory/run.py` (`pending_call`, `complete_writer`, the receipt changes in the writer loop at 1325–1473, `resume_provider_wait`, `provider_continuation`), `factory/diagnosis.py` (`_input_bytes`, `require_model_work`), `factory/model_runtime.py` (`dispatch`), `factory/budget.py` (`release_uninvoked`, `reconcile_reservations`) and `tests/factory/test_stream_d_admission.py`. Mode: REVIEW, with personas `zoom_out`, `design_critic` and `implementation_readiness`, and standards `heilmeier-standard.md` and `implementation-readiness-standard.md`.

## Earlier blocking findings
- **Finding 1 (`next_phase` frozen): fixed.** Lines 50–52 now list every field that may change. I checked that list against every place the code changes a writer receipt:
  - `admitted()` sets `schema_version`, `operation_id`, `phase`, `lease_id`, `invocation_id` and `binding_sha256` (`run.py:401-406`). `schema_version` and `operation_id` never change after the first write.
  - A provider wait sets `lease_id`, `invocation_id` and `resumed_from_wait` (`run.py:294`).
  - `complete_writer` (`run.py:331-334`) and the validated updates (`run.py:1372/1378/1382/1390`) change only fields on the list.
  - Running out of rounds sets `stop_reason` and `exhausted` (`run.py:1470`).

  No field that changes is missing from the list.
- **Finding 2 (binding hash ambiguous): fixed.** Line 53 says the hash always means the SHA256 of the receipt's own `binding`. Lines 57–58 say only a pending receipt still on its original lease must match the intent's binding. One gap is stated openly: the producer at `run.py:1382` changes `binding` without updating its hash. The design refuses such receipts, keeps the producer unchanged, and requires package wiring to fix it before this helper is used. That is acceptable because the helper has no production caller in this increment. In the tested flow, validation leaves the binding unchanged, so `complete_writer` followed by a validated update keeps the hash consistent.
- **Finding 3 (stress-tester receipt undefined): fixed.** Lines 69–77 fix the result. A same-round `stress_tester` receipt returns `None`, changes nothing, and does not authorise the stress round. It needs verified active history but not an intent file. Tests cover all three stress phases, plus wrong-round and boolean-round controls.

## Independent checks that hold
- **The intent can be built before `admit`.** The lease and reservation exist after `reserve_invocation` (`run.py:395`). The extension ID and round come from the verified proposal. If writing the intent fails, the existing `except BaseException` path settles the uninvoked lease, and no history is created (`budget.py:393-400`).
- **A crash between history and attack-state is recoverable.** `release_uninvoked` marks the reservation settled but keeps its row, so `extensions.read` (`extensions.py:116-122`) still validates. `writer_continuation` checks the reservation's operation, call and invocation, not its state (`extensions.py:250-253`). So the claim that "a settled first reservation still binds" is true in the code. After recovery publishes the pending intent, the existing continuation path reserves a fresh lease under the same operation, and no extension is allocated.
- **A crash after the intent but before history is safe.** `active()` returns `None`, so the helper returns `None`. The orphan intent has a fresh UUID (`run.py:380`), so it can never match a later history entry.
- **The predecessor round rule matches the code.** `propose` sets the round to `builder_rounds + 1`. The final-repair, stress and writer receipts left from the last ordinary round all carry a round of `builder_rounds` or lower. So "previous round < active round" does not reject a real predecessor.
- **The lock is reentrant.** `model_dispatch_lock` is a `threading.RLock` (`model_runtime.py:48`), so taking it again inside `pending_call` is safe.
- **The design adds no new module, dependency or authority path, and it reuses `_input_bytes`, `atomic_json`, `writer_intent_valid` and `writer_continuation`.** No Murphy row is claimed. Diagnosis stays off (`test_stream_d_admission.py:446`).

## Nits (optional)
1. **Order of the predecessor-equality and foreign-stress rules** (lines 37–40 vs 74). The last receipt before an extension can be a stress receipt from round N−1. Line 74 says "foreign-round stress receipts still refuse". Read too broadly, that would refuse the crash state where current equals previous, and that state must be recovered.
   - **Fix:** state that the equality rule wins over the foreign-receipt refusal.
   - **Test:** add a crash test whose prior receipt is a stress receipt.
2. **`builder_rounds` on the preserve path** (lines 43 vs 45). Line 43 says a replay "repairs the public count". That replay only reaches the preserve path, and line 45 says "preserve byte-for-byte". **Fix:** state that the preserve path sets `builder_rounds` to the active round and leaves the file unchanged. `read()` already accepts round−1 or round, so this is safe.
3. **Arguments for `model_runtime.dispatch`** (line 82). `dispatch` needs a call name, and it runs `require_model_work`, so a held case refuses. Outside a factory job it takes no lock at all.
   - **Fix:** name the argument, e.g. `builder-<active round>`.
   - **Fix:** say that a refusal for a held case is intended.
4. **Ordinary resume merge (future router).** The merge `{**resume_unit, **writer_receipt}` at `run.py:1350` overwrites `round_limit` and the `release_*` lists with current loop values. If those differ on resume, the preserved receipt will fail the frozen-field check after the router hands off. This is out of scope here, but worth one sentence in "Remaining item 7".
5. **Heilmeier gaps.** The Problem section still uses shorthand ("seam", "lane 1", "row 9"). The timeline is only "one increment". The completion criterion at line 119 now covers the success test.

## Earlier nits
- **Finding 4 (equality check never fires):** answered with a reason (deterministic replay of the helper under the lock). Accepted.
- **Finding 5 (directory fsync):** fixed (line 79).
- **Finding 6 (router ordering):** fixed (lines 66–67).

No blocking finding remains, so the design may move to implementation.

## Implementation response

PASS accepted. Incorporate nits 1–4: predecessor equality wins, preserve path repairs only the public count, dispatch uses extension-writer-receipt/extension-writer-intent names and intentionally refuses held work, and future integration must preserve frozen round-limit/release fields. No blockers remain.
