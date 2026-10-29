# Goldfish design review 2: `docs/designs/isolation-timeouts.md`

**Mode:** REVIEW. I read the three personas first, then `docs/reviews/isolation-timeouts-design-1.md`, the canonical `ENGINEERING.md` and `murphy-register.md`, and the code the design cites. I ran no cloud commands and decrypted nothing. I did not write a file, since you said not to edit. Save this text verbatim to `docs/reviews/isolation-timeouts-design-2.md`.

## Verdict: FAIL

All five round-1 blockers are fixed. There is one new blocking finding, N1, which is a rollout omission. Everything else is Major or nit.

## Round-1 blockers

| # | Status | Basis |
|---|---|---|
| B1 | Fixed | The design chooses explicit fingerprint migration (lines 204–218). The shared helper lives in `bin/processes.py`, so there is no reversed dependency. `run.py:117` already puts `bin/` on `sys.path`. Launch already computes the clean SHA and passes it through `--resume-bench-sha` (`launch.sh` bench-fingerprint step; `run.py:2466`). The design says no restore bundle is forged and the G11 carry-over is recertified. |
| B2 | Fixed, with caveat M-B | Every executable named `boat` is checked. That includes the production `BOAT_CMD=/usr/local/bin/boat`. Only `hcloud-boat` and test fakes skip the check. The `--version` receipt is committed as `fixtures/isolation-timeouts/boat-version.json`. Schema assertions use the real `list.json` and `billing.json` fixtures. |
| B3 | Fixed | The design now names the ledger path, schema, lock and statuses. Refused checks reserve nothing. Reservations expire at `started_at + ttl + 1800` through an explicit `reconciled_expired` step. Hetzner bypasses the ledger. The guarantee is stated as single-host and row 17 stays open. A real billing fixture exists. |
| B4 | Fixed | Status-1 retries are honestly bounded. Usage status 2 never retries. In-place and restored runs with work never retry and record `startup_failed`. The reason is a closed enum. The ready-marker ownership is defined. The three pgrep guards are named. The controller path (`STARTUP_FAILED`, prompt collect, empty-work exception in `collect.sh`) is specified. |
| B5 | Fixed | Row 44 is scoped to the two named call sites, `bin/strategy:121` and `run.py:165`. The tests drive the real `run.sh` serial branch and `silent_checkpoint` through `Environment.exec`. The diagnostic opt-out is preserved. The design lists routed sites and says Docker `up -d` daemon services intentionally outlive the client. |

## Blocking finding

### N1. The design does not mention the trusted-launcher fingerprint, and it changes it.
**Scope:** "Fingerprints and rollout" (lines 204–218), changes 2–6, `factory/launch_manifest.py`, `factory/key_holder.py`.

- The design edits `factory/launch.sh`, `bin/boat-call`, `bin/boat-spend`, `bin/boat-launch-guards.sh` and probably `factory/collect.sh`.
- Every one of those is in `launch_manifest.TRUSTED_FILES`, which is `key_holder.PINNED`. `key_holder.fingerprint(ROOT)` hashes them.
- Founder-approved policies bind that hash as `code_sha256`.
  - `policy_load` refuses with "trusted launcher code changed; unlock requires a reviewed policy" (`key_holder.py:116`).
  - The live `launch` / `resume_launches` ops refuse with "trusted launcher code changed" (`key_holder.py:479`, `:540`).
- So merging this change halts every holder-mediated launch and resume until a new founder-reviewed policy is issued. This is the biggest rollout effect of the whole design.
- The design's own fingerprint section lists only `bench_sha` and the responder `code_sha256`. It says nothing about the launcher or policy fingerprint, the re-approval step, or ordering against in-flight control-VM resumes.
- This also touches a founder-approved security binding. ENGINEERING §1 requires founder sign-off when a design changes a security property.

**Guidance:** Add a rollout paragraph that:
1. says the launcher fingerprint changes;
2. says how a reviewed policy is regenerated and approved, and by whom;
3. says what happens to restores and launches already pending when the change lands;
4. says whether the four phases merge together or fingerprint-neutral phases go first.

Also say where `bin/processes.py` is registered. It must be in `WORKER_BENCH` so workers install it. It is in `TRUSTED_FILES` only if a trusted file imports it. The design currently names only the test update (`test_launch_manifest.py`).

## Major findings (not blocking)

**M-A. Descendant-group kill needs a self-kill guard.**
- Change 1 says "kill descendant groups too".
- Under `UNBUG_DIAGNOSTIC_PROCESS_GROUP=1`, children share the caller's group, and `bin/diagnostic_budget.py:24` sets the variable.
- A literal implementation would `killpg` the caller's own group or session and kill `run.py` before seal.
- State that groups equal to the caller's pgid or sid are never signalled. Test it with the opt-out set.

**M-B. The Boat version on the control VM is asserted, not established.**
- The design says "Expected version is 1.0.85 there too" (line 102).
- `control/setup.sh:44` installs from `...download?platform=…&channel=prod`, with no version in the URL. A rebuilt VM gets whatever is current.
- The check fails closed with no silent error. But merging before the VM reports 1.0.85 makes every control-VM Boat call fail.
- Add the ordering requirement: verify `BOAT_NO_UPDATE=1 /usr/local/bin/boat --version` on the VM first. Either pin the download in `setup.sh` or state that the pin is check-only.
- Row 31 can close on the test, but the receipt must not claim the VM is pinned.

**M-C. Gate-deadline expiry has no defined outcome.**
- G13–G15 get an `agent_timeout` deadline, and its default of 4 h is confirmed (`run.py:2405`). The design does not say what happens when it expires.
- Today a raised exception inside `gate_attempt.execute` becomes `record_crash` → `terminal_stop=runner_error:*`.
- That is acceptable if intended, since it is never scored. Say so explicitly.
- Add a test, because target property 2 forbids counting this as a case failure.

**M-D. The migration cost is not enumerated.**
- `run.py:1397` embeds `bench_manifest()` in the strategy-run signature. So the G13–G15 cached evidence is invalidated for every restored case, not only G11.
- The design says only "retains evidence whose dependencies still match".
- Name the gates that rerun, so the later flow cost is known and not discovered.

**M-E. `launch.sh` loop-body variables are not partitioned.**
- The loop body mutates `args` (`--resume … --resume-bench-sha`), `identity`, `put_ckpt` and `put_final`.
- Once the body is in a subshell, none of those reach the parent.
- Say which values must persist as state files and which can be dropped. Keep `args` and the detach step consistently inside the subshell.

## Nits

- Line 104 is garbled: "BOAT_CMD it also gets BOAT_NO_UPDATE=1". Delete or rewrite it.
- The change 4 "reason" enum includes `timeout` and `cancelled`. Say which component writes each.
- `--finish` can release a reservation while a VM is held (`guard_wait` finishes spend when `UNBUG_LAUNCH_STATE` is unset). Say this is accepted, because the TTL still bounds the worker.
- `collect.sh:18–19` pgrep/pkill already matches `^python3 .*factory/run.py`, so it will also hit the supervisor. Note that the double TERM is safe because `run.py` ignores a second one (`run.py:2270`).

## Murphy row accounting

| Row | Design says | Review |
|---|---|---|
| 31, 44, 46, 52 | Target closure | Plausible given the specified real-artifact tests. 31 depends on M-B being stated honestly. |
| 17, 18, 42, 43, 49 | Partial, open | Correct. |
| 28, 29, 30, 32, 37, 45, 50 | Open with reasons | Correct. |

Resubmit after N1 is resolved. M-A through M-E should be fixed or answered in the same pass.
