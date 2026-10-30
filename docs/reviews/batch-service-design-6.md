**PASS.** No blockers are left in the "Increment 2 addendum" (`docs/designs/batch-service.md:570-729`) when read with interfaces §8. All three blockers and M1 from design review 5 are fixed in the text, and each fix holds up against the code it depends on. I made no edits and ran no compilers or tests.

### Prior findings, checked against code

- **B1 (manifest reaches the worker): fixed.**
  - The addendum adds `factory/batches/*.json` to `WORKER_GLOBS` (`:667-670`). `launch_manifest.worker_files` and `batch.build` already select files by `WORKER_GLOBS`, so the manifest enters `worker-release-manifest.json`.
  - `worker_release.verify` then checks it at `factory_root`, after the existing verification step.
  - The trust chain is complete: `worker-release-manifest.json` is one of the `batch.INPUTS` files pinned by `batch-release.json`, and `run.py:2657-2661` already checks that file's SHA against `--batch-release-sha256`.
- **B2 (case and source checked against the launch): fixed.**
  - Before creating a worker, `launch.sh` compares the config's `case_id` with `--case-id`, its `source_generation` with `--checkpoint-sha256` (null only when fresh), and its release SHA with `--batch-sha256` (`:645-650`).
  - `--case-id` is in the argv that `bind` builds (`batch.py:173`), so `launch.sh` can read it there. That gives D's `for_case` tuple comparison (`job_authority.py:68-71`) a source that was checked independently.
- **B3 (undefined proof input for source changes): fixed.**
  - `authorize` now refuses any non-null source for a new job and any change to a stored source (`:614-622`). There is no proof parameter and no advancement branch.
  - The installer's old+1 revision tests use channel pairs written by the tests themselves, which matches D's `read(channel, binding)` equality check.
- **M1 (where `authorize` is called): fixed.** It now runs immediately after `attest_launch` and before `consumed.add(stamp)` (`key_holder.py:635-636`). Every earlier refusal happens before any money is reserved, and `attest_launch` has no side effects.
- **Nits N1–N5: all included.**
  - `install` goes after the existing `authenticate_gates`, with no reordering.
  - Bounds are explicit: `committed_total_usd <= money_limit_usd`, with an exact deadline match.
  - The VM recipient is added only for batch flows.
  - `max_cost=None` is a stated prerequisite.
  - An in-place restart is a same-revision, byte-equivalent replay.

### Double-spend concern ruled out

I checked whether a fresh batch job could be relaunched under the same commitment and spend it twice. It cannot:
- `policy_load` rejects `retry_failed_launches` for any batch policy (`key_holder.py:127`).
- Line 622 then refuses a second `(case, 'new')` stamp for a batch job.

So one fresh reservation can never fund two workers in sequence.

### New nits (optional, none blocking)

1. **The fresh-job value is `'new'`, not `None`.** For `mode == 'new'`, the holder's `generation` is the string `'new'` (`key_holder.py:611`), but `authorize` and §8 expect `source_generation=None`. One sentence ("map `'new'` to `None`") would stop an implementer storing `'new'` and having D's 64-hex check refuse it.
2. **"Request identity" in money.json is undefined (`:603`).** Since replays are keyed by job and source and return the stored authority unchanged, either define the field (for example, the request's `batch`, `job` and `checkpoint`) or drop it. Otherwise a retry with a different request might be refused.
3. **Two copies of the manifest exist on the worker.** The installer reads `BENCH/factory/batches/<id>.json` (`~/unbug-bench`, checked by `deploy.py`), while `worker_release` verifies `~/factory/batches/<id>.json`. Both are tied to `config.manifest_sha256`, so the design is sound, but naming one path (`~/factory`, where `run.py` lives) removes the ambiguity.


## Elephant response

Optional nits clarified: holder 'new' maps to null; job+source is the only
idempotency key (dropped vague request identity field); installer reads the
worker-release-verified ~/factory/batches manifest beside run.py. No blockers.
