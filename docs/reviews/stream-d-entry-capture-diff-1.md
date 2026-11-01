**Verdict: PASS.** No blocking findings. Four non-blocking ones are listed below and none of them needs fixing before merge.

I reviewed the fixed diff `6afceac..10da907`. HEAD `c4f2630` only adds the suite record and its log. I read `docs/ENGINEERING.md`, the `zoom_out` and `implementation_readiness` personas, `implementation-readiness-standard.md`, the approved design and its binding amendments. I ran nothing paid, started no subagents and edited nothing; the tree was still clean after my test run.

## Checks I made myself
- **Entry tests:** I re-ran `tests/factory/test_stream_d_entry.py`: 15 tests passed in 24.9s.
- **Suite record:** the record names head `10da907` and tree `71217ef6…`, which matches `git rev-parse 10da907^{tree}`. Exit code is 0 and it reports 167 scripts with 0 failures. The log's SHA-256 is `7b90f261…bb00ba`, as claimed.
- **Out-of-scope files:** the diff does not touch `diagnosis_dispatch.py`, the Murphy register or activation. `DIAGNOSIS_ENABLED` is still `False`.

## Each design point against the code

**Records owner** (`factory/extension_package.py:52-66`)
- Exactly one owner is enforced: `ValueError('two record owners')` otherwise.
- The ordinary owner gets a UUID4 root under `entry-records/<id>/`, `operation_id=None` (stored as a null `writer_operation_id`), and `completed=False`.
- Load and save now read `operation_id`/`round_number` instead of reaching into the row. Package roots and admitted-row behaviour are unchanged, and the package `capture` and `stress` are untouched apart from the hoisted `scientific_binding` helper, whose behaviour is identical.

**`observe_gate`** (`:229-250`)
- `invoke()` runs outside any try, so its exceptions reach `run_validity.retry` and `gate_attempt` exactly as before.
- Only the capture-side work is wrapped, and only the B1 error list is caught. The original tuple is always returned.
- `observed[stage]` is reset on every attempt.
- A pending-shaped result or a changed case hash returns without saving.
- If a save fails after the rename, the stage directory is removed. Even if that removal fails, the missing close marker blocks entry. Nothing on the capture side can raise into `retry`, so capture cannot cause a paid re-run.

**Activation** (`:356-362`, `factory/run.py:3008-3010`)
- The predicate matches B2 plus `late_gate_rehearsal`.
- The run_gates wiring is the three lines, gated on both `replay_gate` and `around_gate` being `None`.
- When excluded, nothing new runs. Serial G10 applies only on the observed path.
- `serial` and `replay_only` are ignored on that path. That is harmless: the only caller that passes them (`extension_package.py:334`) also passes hooks, so it never reaches `observe`.

**Pointer publication and cleanup** (`:394-416`)
- Job authority is checked first, then `safe_directory`, then the root is created and the pointer published atomically.
- Only other UUID-named children are removed, with a symlink check before each removal. All of this happens before any gate runs, so its errors propagate without a retry.
- The close marker is written only when the pipeline returns normally, every observed stage saved, `c.stopped` is false and there is no `infrastructure_gate`.
- Exact pointer and marker keys match the clarification.

**Stress** (`:368-391`)
- `attack-state.json` is read with `_writer_json`.
- The checks match M4/M5: positive round equal to the pointer round and `builder_rounds`, exact report name, matching scientific binding, no unfinished diagnostic, a non-`None` `gate_marker`, and freshness clearance reusing the package condition.
- The inventory baseline is the current digests, so only the explicit stress roots are attributed to stress. Missing proof leaves no stress record and does not stop the traversal.

**Entry** (`:419-453`)
- Authority and history are checked outside the try; any history gives `extension_comparison_pending`.
- It works on a shallow copy with deep-copied args, card and models.
- The pointer, close marker and case-hash equalities are validated.
- G3 is loaded first to restore workers before the version vector is pinned, which keeps snapshot's `_configuration` check stable.
- The scratch outputs are removed only after the symlink check; `extension-snapshots` is never touched.
- `comparison.snapshot` is unchanged and runs with `records.evidence`, which never evaluates. A missing record becomes pending through the malformed-result path.
- Stress must pass and no stage may be pending. `source_generation` comes from authenticated authority.
- Exceptions map exactly as the clarification says. `extension_snapshot_invalid` and non-evidence `BudgetError`s propagate, which matches the "only these labels" wording.

**Docs:** the M3 and activation obligations are recorded in `docs/designs/stream-d.md`.

## Non-blocking findings
1. **Nit/Minor: two inputs can still raise an uncaught error in stress capture** (`extension_package.py:375-385`). M4/M5 promise "no new exception from stress validation", but:
   - `scientific_binding(receipt['binding'])` runs before `gate_marker`. If `binding['bench']` or `['settings']` is a string, `.pop` raises `AttributeError`, which is not in the caught list, and that would stop an ordinary traversal that would otherwise run.
   - `r.attack_report(report)` returning `None` would raise `AttributeError` on `.get`. Only a race after `gate_marker` parsed the same file can reach this.

   Both need a corrupt or tampered `attack-state.json`, which the factory never writes. Suggested fix: add a dict-shape guard or a `result is None` return before use.
2. **Nit: two exclusions are untested.** B2 asks for tests of every exclusion independently. `test_exact_activation_and_mode_exclusions` covers the flags, the audit attributes, the disabled flag and `around_gate`. It does not cover `factory_job(c)` being false or a `replay_gate`-only call. Both are trivially correct by reading the code.
3. **Nit: a close-marker write failure propagates out of `run_gates`** (`:413`). It happens outside the retry and cannot re-run a gate, as the design accepts. It does surface as an ordinary stop instead of a silent missing marker.
4. **Nit: a UUID-named regular file in `entry-records/` stops the traversal.** `shutil.rmtree` raises `NotADirectoryError` before any gate runs. That only happens with disk tampering and there is no paid retry.

## Are the tests adequate?
Yes, for first entry only. They use real G1 contract diagnostics, real G4/G5 over saved plain checkpoint executions with a real G5 rejection, and real G16 breadth inside a real `validate_and_repair`. That G16 run shows exactly one review, no writer repair, a fail record with `review_inconclusive`, and an entry fail. The stress-pass and stage-pass controls are authored and labelled as such.

The tests also cover:
- the real freshness clearance over saved HTTP bytes, plus a tamper that leaves entry pending;
- the pointer, close-marker and G3 holds;
- missing, tampered and symlinked support files, version drift and a changed case;
- caller isolation, including `bench_workers` and the source-generation rebind;
- a history refusal with no snapshot;
- pending-shaped results and capture errors with no re-execution and an unchanged tuple;
- a failure after rename;
- old-traversal invalidation after money-wait interruptions, with cleanup down to one root;
- infrastructure exhaustion;
- a symlinked root stopping before any gate.

Normal runtime behaviour is preserved: gate verdicts, retry and interruption, the `after_gate` and budget boundaries, early reuse and the repair loop all pass through unchanged. The only new cost is serial G10 once diagnosis is enabled, and that is documented as an activation obligation.

Scope matches what was asked: first entry only, nothing activated, no Murphy rows closed. Isolated comparison, subsequent entry and version drift are correctly left to the next increment.

## Implementation disposition

Accepted PASS. No blocking finding remains. The four non-blocking findings are retained above for follow-up; this handback makes no additional production change. First-entry capture is complete as this reviewed increment; comparison, subsequent-entry reconstruction, version drift and terminal outcomes remain separate. No Murphy rows close and activation remains disabled.

