**PASS.** No blocking or major findings. Merge still has to wait for the full suite to go green (see the end).

**Mode: REVIEW**, using zoom_out and implementation_readiness, against `implementation-readiness-standard.md`. Scope: `873bcab..HEAD` (16c5943) in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`. I checked it against `docs/designs/batch-service.md:849-971` (Increment 2b.1) and `docs/designs/interfaces.md` §8 (`:396-480`). The review was read-only: I made no edits, saved nothing, and ran no models, cloud jobs, VMs or decryption. The only things I ran were the focused local tests.

**Checked against the design**
- **Trust import closure.** `batch_service.py` imports `batch_money`, `collection`, `launch_manifest`, `registry` and `transfer`, and all five are already in `TRUSTED_FILES`. `batch_service.py` is added to `TRUSTED_FILES` (`launch_manifest.py:16`) and to the explicit worker test list (`tests/tools/test_launch_manifest.py:83`). `diagnosis` is imported lazily, only after the `DIAGNOSIS_ENABLED = False` gate (`:19`, `:296-299`); it is a tracked constant, not an environment flag. `factory/diagnosis.py` does not exist yet. That matches the design's rule that D's module joins the trust closure only in the activation review.
- **Collection.**
  - Reading: it copies only `collection_files(case)` members, and `O_NOFOLLOW` plus `S_ISREG` stop symlinks and other non-regular files.
  - Card checks: it refuses a card bound to another case or release, a card with `checkpoint_error`, or a card with no casekey. `collection.verify` must return exactly `{case}`.
  - Archive: the bound archive is the unique one whose digest matches. The archive the card does not bind is deleted from the stage.
  - Ciphertexts: a referenced statement or search ciphertext must be present and its digest must match. Unreferenced companions are kept, and the source directory is never rewritten.
  - Publication: files are fsynced, the manifest is written by `atomic_json` with `sort_keys`, which makes it deterministic, and the stage is renamed into place with the parent directories fsynced. An existing generation is re-verified through `_snapshot`, which compares the manifest digest, the member set, each member's hash and size, the card and the archive. That covers both "same generation, different bytes refuses" and repair of a crash between rename and journal write. No `current` pointer, money directory or ACK is written, and a test asserts that.
- **Journal.**
  - Schema: the exact key sets are checked, and `next_sequence` must be a true `int` with sequences contiguous from 0 to `next_sequence-1`.
  - Entries: each entry must agree with its key, case, job, generation hex and `state:'pending'`.
  - Facts: `facts` is either null or exactly `{exhaustion, actual_model_work, pending_projection}`, with strict bools and a strict schema-1 projection.
  - Lineage: each derivation must match the parent+1 ordinal, the root, the child case and eligible facts, with no reused child. Each derived entry needs exactly one recorded parent.
  - Queue rows: each row is checked against its dedup key, its kind and reason, and its derivation or entry.
  - Replay: stored facts win on replay and D is not called again. A `None` projection replays too (the B1 regression is tested).
- **Projection wrapper and queue logic.**
  - D calls: it calls exactly the three D functions, checks that the card is not mutated after each call, and turns any exception into a `ValueError` refusal.
  - Contradiction rule: `replacement_eligible:true` with a false predicate refuses. False with both predicates true queues no child but does queue a resume (tested at case `k`).
  - Child rule: a child is queued iff both predicates are true, any present projection does not say false, and the replacement policy is enabled.
  - Resume rule: a resume is queued when a projection is present, or when the parent is exhausted and its total is unknown.
  - Ordering: settlement, then replacement, then exhaustion resume, then `sequence`.
  - Atomicity and deadline: facts, derivation and requests go into one `atomic_json` write, and a failed write leaves the journal byte-identical (tested). The deadline check comes before D is imported and uses the injected `now` or `time.time()`, like `authorize`.
- **One child per immediate parent.** The child is `root-r(ordinal+1)`, so the chain runs J → J-r1 → J-r2. The derivation is keyed by the parent case. Replay at a later generation reuses the stored row with only `eligible_generation` ignored. A claimed child or changed lineage refuses (tested). `check_manifest` now refuses root names ending in `-rN` and validates `replacement_policy` strictly. There is no ordinal cap.
- **Call caps.** I found no call-count admission rule; `max_calls` is not read. The holder, installer and fresh-only money authorizer are untouched.
- **Tests.** The module docstring says the public card and opaque ciphertext are authored transport bindings with authored API answers, and that there is no archive decryption, no real-case or D-eligibility claim, and no Murphy row closure. That matches the brief.
- **Signal-test harness fix** (`tests/bench/test-launch-guards.py:432-445`). The startup wait goes from 5s to 30s, and a `finally` block kills the process group (`start_new_session=True`, so pid equals pgid) only if the process is still alive. Production code is unchanged, and the change is under 20 lines, so skipping the design is allowed.

**Nits (non-blocking, optional)**
1. **A null field in the card is not treated as "unknown".**
   - `batch_service.py:255` uses `card.get('case_budget', {}).get(...)` and `:171` uses `card.get('public_search', {}).get(...)`.
   - A key that is present with value `null` (or any non-dict value) raises `AttributeError`, not "unknown" or a `ValueError` refusal.
   - It fails closed: in `plan` the exception comes before `atomic_json`, so nothing persists. But that entry can then never be planned.
   - No current producer writes null (`model_runtime.update_case_budget` always writes a dict, and `run.py` always writes `public_search` as a dict). `restore_sync.py:65,73` already uses the `or {}` idiom.
   - Suggest `(card.get('case_budget') or {})` and `(card.get('public_search') or {})`, so null counts as unknown in line with design N1.
2. **Small refusal and validation gaps.**
   - `_card:162` refuses only a *truthy* `checkpoint_error`, so a present-but-falsy value passes.
   - In `_load`, a resume row's `reason` is checked only against the allowed set, not against the stored facts and total.
   - The `generations/` directory itself is not checked for being a symlink (`:209-211`; only `<case>` is).
   - All three are local-control-home concerns, not trust-boundary ones.
3. **One design test item is not explicitly asserted.** "Source config shape is untouched" (design `:965`) has no assertion that the manifest or template is unchanged after `resolve_job`, collect and plan. The code returns a `deepcopy`, so this is low risk.
4. **Litter after a crash.** A crash mid-stage leaves a `.stage-*` directory under `generations/<case>/`. It is harmless because nothing iterates that directory, and it can be swept when someone touches it later.

**Evidence I ran**
- `tests/factory/test_batch_service.py`: 10 tests, OK.
- `tests/tools/test_launch_manifest.py`: 2 tests, OK.
- Both on Python 3.14.6. `hashlib.file_digest` needs 3.11 or later and is already used elsewhere in `factory/`.

**Full suite: not yet confirmed.** `/tmp/unbug-b-stream-resume-2b1-tests.log` was still on `tests/bench/test-launch-guards.py` when I last checked, and the `tests/run.py` process is still running. Per ENGINEERING step 4, merge only after that log ends green.

---

## Elephant resolution

PASS accepted; no blockers or majors, none rejected. Optional nits retained as
integration hardening obligations: null/non-dict whole card blocks fail closed,
resume reason cross-checking and generation-parent symlink checks, explicit
config immutability assertion, and stale staging cleanup. Current producers
use dictionary blocks; no activation or row closure relies on these nits.
The production adapter remains False and grants no launch or money authority.
Full-suite result is recorded in the increment report after it completes.

