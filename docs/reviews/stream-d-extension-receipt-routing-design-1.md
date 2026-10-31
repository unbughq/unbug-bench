**BLOCK.** The design is narrow and sound, and the order of admission writes is correct. Two contradictions in the rules for checking a receipt the helper keeps leave the implementer to decide things. Followed as written, the helper would refuse a legitimate validated receipt.

Reviewed in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-4ac6b632`: `docs/designs/stream-d-extension-receipt-routing.md` (uncommitted), against `factory/run.py`, `factory/extensions.py`, `factory/diagnosis.py`, `factory/registry.py`, `factory/run_artifacts.py` and `tests/factory/test_stream_d_admission.py`. Mode: REVIEW, with personas `zoom_out`, `design_critic` and `implementation_readiness`, and standards `heilmeier-standard.md` and `implementation-readiness-standard.md`.

## What holds
- **Write order.** The writer intent can be built before `extensions.admit`. The operation UUID is chosen at `run.py:377`. The extension ID and round come from the proposal. The first lease and invocation come from `reserve_invocation` (`run.py:390`), which runs before `admit` (`run.py:392`). So "intent, then history, then attack-state through `admitted()`" fits the current code.
- **Interrupted admissions.** Every extension admission gets a new UUID (`run.py:377`), so an intent file with no matching history entry can never be matched to one later. `extensions.read` (`extensions.py:126-133`) also requires a ledger reservation for each history row's operation. So an orphan intent authorises nothing.
- **The crash window is real.** A crash after history is written but before attack-state leaves no way forward. On rerun, `admit` refuses because of the new UUID (`extensions.py:358-363`). `writer_continuation` refuses because the receipt is not pending (`extensions.py:241-247`). The new helper fills exactly this gap, and recovery then hands off to the existing `writer_continuation` path.
- **Writes are durable.** `atomic_json` fsyncs both the file and its parent directory (`registry.py:18-32`).
- **Checkpoints keep the intent files.** The seal step tars the whole work directory (`run_artifacts.py:121`). The fixed name list at `diagnosis.py:522` is only the diagnosis input bundle, which does not need these files.
- **Scope is respected.** No Murphy row closes. No production caller exists for `extension_proposal` (test at `test_stream_d_admission.py:446`), and the new helper gets none either, so diagnosis stays off and no live path changes.

## Findings

**1. Blocker: `next_phase` cannot be a frozen field.** (Change section, lines 50-52; `run.py:1356`, `run.py:1372`, `run.py:1378`, `run.py:1382`, `run.py:1390`)
- The intent is built from the writer receipt, which sets `next_phase='G1'` (`run.py:1356`). `complete_writer` keeps `'G1'` (`run.py:335`).
- Every validated writer receipt then rewrites it to `'stress'` or `'writer'`.
- The design also requires that "completed/validated" receipts be preserved, and its tests say the same.
- So the helper would refuse every validated receipt, or the implementer has to choose which rule wins.
- **Fix:** take `next_phase` off the frozen list. Write down the full list of fields that may change. From current code these are:
  - `phase`, `lease_id`, `invocation_id`, `resumed_from_wait`;
  - `binding`, `binding_sha256`, `output_sha256`, `repair_pending`, `next_phase`;
  - `validation_problems`, `awaiting_stress`;
  - `stop_reason`, `exhausted`, added at `run.py:1466-1469`.

  State that every other field must equal the stored intent.

**2. Major: "matching binding hash" is ambiguous.** (Lines 30 and 47 against line 52)
- Line 47 requires a "matching … binding hash" for a current receipt. Line 52 says "binding may change".
- `complete_writer` and the validated update both replace `binding` with `attack_binding(c)` (`run.py:333-334`, `run.py:1382`). So `binding_sha256` will differ from the intent's value.
- **Fix:** say exactly which check applies to which receipt:
  - a current receipt must have `binding_sha256 == sha256(json.dumps(binding, sort_keys=True))`, with `binding` a dict whose keys equal `set(attack_binding(c))`;
  - only a pending receipt that has never been continued must also match the intent's hash.

**3. Major: the helper's answer to a stress-tester receipt is undefined.** (Lines 37-40 and 55; `run.py:1405-1449`)
- An extension is one writer round, then its stress round, then a gate re-run.
- Once stress starts, `attack-state.json` holds a stress-tester receipt for the same round. It carries a different operation ID, and its phase runs pending → completed → validated.
- Under this design that receipt counts as "foreign", so the helper refuses. The router that will use this helper needs it to answer during the stress and gate part of a live extension. A refusal there would stop a valid case.
- **Fix:** pin the result now, since the router will depend on it. One option: when the current receipt is `actor == 'stress_tester'`, has the active round, and history is active, return the stored writer intent or `None`, not a refusal. Add one test for it.

**4. Nit: the same-file equality check can never fire.** (Lines 21-22)
- Intent files are named by an operation UUID that is new on every call, so an existing file with the same name never occurs in practice.
- **Fix:** create the file exclusively and refuse if it already exists, or say why the comparison is kept.

**5. Nit: the new directory needs its parent fsynced.** (Line 18)
- `work/extension-writers/` is created on first use. `atomic_json` fsyncs only the file's own directory, so the new directory entry in `work` could be lost in a crash.
- **Fix:** fsync `work` after `mkdir`, as `_sync_tree` does (`extensions.py:203-214`).

**6. Nit: ordering for the future router.** (Line 55)
- The ordinary resume code in `run.py:1128-1250` can rewrite attack-state before anything else runs.
- **Fix:** add one line saying the router must call `writer_receipt` before any of that code. Otherwise a fixable state gets refused, or flagged as an invalid recovery receipt.

**7. Nit: Heilmeier gaps.** The objective is mostly internal shorthand ("seam", "lane 1", "row 9"). There is no timeline. The success test is only implied by the test list.

## To clear the BLOCK
Revise the Change section so that:
- every receipt field is either frozen or allowed to change, with findings 1 and 2 resolved;
- the stress-tester case from finding 3 has a fixed result and a test.

No further structural change is needed.

## Implementation response

Accepted findings 1–3: explicit mutable-field allowlist, own-binding hash semantics, and same-round stress returns None without writer authorization. Binding keys remain a package integration check, consistent with the existing admission contract. Accepted directory fsync and future-router ordering nits. Retained equality for deterministic helper replay under the reentrant lock. Added target files and completion criterion. No finding rejected; a fresh second design review is required before implementation.
