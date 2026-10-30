**Verdict: BLOCKED.** Three blockers, each with a one- or two-sentence fix. Everything else in the addendum holds. The scope is the "Increment 2 addendum" of `docs/designs/batch-service.md` plus interfaces §8, including "Worker installation and D's context".

I checked the claims against code: `factory/batch.py` `bind`, the holder's `factory/key_holder.py` (`policy_load`, `current_generation`, the launch and `resume_launches` paths), `factory/launch.sh` (the restore and in-place restart paths), `factory/run.py` startup at lines 2650–2775, `factory/launch_manifest.py`, `factory/r2_upload.py`, and D's actual `job_authority.py` in t3-21bef30c. Standards used: zoom-out, Heilmeier/design critic, implementation readiness, and ENGINEERING.

### Blockers

**B1. The tracked batch manifest never reaches the worker (Blocker; readiness).** "Installer and resume" has `job_config.install` read `BENCH/factory/batches/<batch_id>.json`.
- `batch.build` only ships `WORKER_BENCH + WORKER_CONFIG` plus `WORKER_GLOBS` (`factory/*.py`, `factory/*.sh`, `factory/prompts/*.md`) into `worker-release-manifest.json`. `factory/batches/*.json` is not in any of them.
- The addendum adds `control-recipient.txt` to `WORKER_CONFIG` but says nothing about the manifest. As written, every batch install would refuse.
- **Minimal fix:** state that increment 2 adds `factory/batches/*.json` to `WORKER_GLOBS`. The manifest and router config are public and token-free. The installer then relies on the existing worker-release hash verification for that file.
- In the same edit, either define "source commit's public source manifest binding" as `worker-release-manifest files[path] == config.manifest_sha256`, or delete it. As written it is a check nobody can implement unambiguously.

**B2. Nobody actually checks `source_generation` and `case_id` against the launch (Blocker; exact trust binding).** The installer requires "root source_generation must equal the launcher-verified collected checkpoint".
- `run.py` receives no checkpoint digest. `--checkpoint-sha256` is consumed by `launch.sh` at line 37 and never forwarded.
- In "Host configuration and delivery", `launch.sh` only checks "config bytes/hash and release binding". So no component compares the config's source and case with the generation it actually restores.
- **Minimal fix:** before VM creation, `launch.sh` requires:
  - `config.case_id == --case-id`;
  - `config.source_generation == --checkpoint-sha256`, with null meaning no checkpoint;
  - `config.batch_release_sha256 == --batch-sha256`.

  The installer then treats the RAM `source_generation` as that launcher-verified value. `c.source_generation` is what D's `for_case` compares, so this check is the binding, not decoration.

**B3. The proof input for source-generation changes is undefined (Blocker; readiness and contract risk).** The signature is `batch_money.authorize(policy, job, source_generation)`.
- The design says source changes need the acknowledged pointer plus a retirement proof from the 2b module, and that pure tests "author the proof inputs". No parameter or shape for that proof exists, so the implementer must invent an interface that 2b then has to honour or rewrite.
- Because every batch resume refuses in this increment anyway, the revision-advance branch in `batch_money` is unreachable in production. That is YAGNI.
- **Minimal fix:** in increment 2, `authorize` refuses any `source_generation` that differs from the stored one (or any non-null value for a new job) with `money_wait`. The advance branch and its proof type are specified and built in 2b.
- The installer's old+1 resume logic and the D `for_case` revision tests stay. Those tests feed an authored old/new channel pair (labelled) directly as RAM config and checkpoint copy. That keeps "no boolean grants" true by construction.

### Major (non-blocking, fix recommended)

**M1. "Before durable launch reservation" is ambiguous about where `authorize` is called.** In the holder, refusals ("case worker already exists", `CheckpointUsed`, "previous recovery outcome requires reconciliation", `admit_attempt`) happen between `bind` (key_holder.py:568) and `consumed.add(stamp)`.
- If `authorize` runs right after `bind`, refused launches still leave committed money in `money.json`. It is idempotent per job, so this is a headroom hold, not a leak.
- **Fix:** name the call site as immediately after `attest_launch` and before `consumed.add(stamp)`.

### Nits

- **N1. The run.py placement forces a reorder nobody needs.** "before record_founder_decisions" requires moving `authenticate_gates` ahead of `record_founder_decisions`. `founder_decisions.record` only writes card rulings and checks the call cap; it makes no model call. Simpler: call `install` right after the existing `authenticate_gates` (resume) or at that same point (fresh), before `raised_limits`, `restore_gate_crash` and any model call. Then nothing moves.
- **N2. "Matching … bounds" against the manifest is vague.** Say `committed_total_usd <= money_limit_usd` and `batch_deadline == manifest.batch_deadline`. Not `== requested_total_usd`: later serialized grants may exceed the initial request.
- **N3. Scope the founder+VM wrap.** `r2_upload.case_recipient` is called for every flow (run_artifacts.py:101). State that the VM recipient is added only when `args.batch_release_sha256` is set, and that non-batch and audit flows keep founder-only.
- **N4. run.py's default cost cap still applies.** Once `bind` stops emitting `--max-cost`, run.py's default of 5.0 still feeds `budget.py`. That is acceptable only because D's branch passes `max_cost=None` for authenticated jobs and nothing is enabled. One sentence saying so prevents a "sole monetary bound" contradiction.
- **N5. Say the in-place restart path re-sends nothing.** `launch.sh` restart-in-place (around line 585) reuses `$args` and the existing `/dev/shm/secrets` contents. Note that the RAM config and flags persist with it, so a restart is a same-revision, byte-equivalent replay.

### Verified, no finding

- **Reuse:** `registry.atomic_json` exists; there is no new service or dependency.
- **Frozen launch state:** the receipt's `launch.argv` plus `launch.json` equality in `resume_launches` already freezes argv, which carries the config SHA flag.
- **Pure `bind`:** `bind` stays pure, and the scoped max_cost ignore covers both the `policy_load` and `current_generation` `job['max_cost']` uses.
- **D's channel read:** D's `read` requires `c.job_money == authenticated_job_config['job_money']` exactly. That is consistent with "advance the checkpoint copy, then admit".
- **D's context:** the four context attributes match D's `for_case` names.
- **Refusals:** legacy absence refuses; the 22 historical cases stay read-only; decreasing totals refuse pending 2b; unknown waits keep the existing commitment.
- **Later increments:** nothing in the addendum contradicts gated increments 2b, 3, 4 or 5, apart from B3's proof-interface risk.

**Re-review condition:** PASS once B1–B3 are folded into the addendum text.


## Elephant response

B1 adds factory/batches/*.json to worker selection and exact verified worker-
release-manifest file binding. B2 spells out host precreation case/source/release
comparisons, null only for fresh. B3 removes unreachable authorize revision
advance/proof interface entirely in this increment; all changed/non-null new
sources refuse until reviewed2b. Installer old/new fixture tests remain.
M1 places authorize immediately after attest_launch/before consumed.add.
Nits: startup insert after existing authenticate_gates without reordering
record_founder_decisions; explicit manifest bounds/deadline comparisons;
VM wrapping only batch; D max_cost=None required before enablement; in-place
restart same RAM/config flags. No findings rejected.
