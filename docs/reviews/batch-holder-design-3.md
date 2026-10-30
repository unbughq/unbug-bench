**FAIL.** Round 2 fixed most of what it set out to fix: the lock-held helpers, the single source writer, PRE/POST, the known-spend floor, accounting before the pointer, and the ACK amendment rule are all sound now. One blocker and three major gaps remain. Each needs only a short edit, but as written two of them can strand money or capacity and one reopens a spend path that bypasses the ACK chain.

Mode: REVIEW. Reviewed with the zoom-out, design-critic and implementation-readiness roles against `heilmeier-standard.md` and `implementation-readiness-standard.md`. I wrote nothing.

## Round-2 findings

| ID | Status |
|---|---|
| B1 lock scope | Resolved (lines 275–289, 291–295) |
| B2 source owner / PRE–POST | Resolved (279–281, 305–319) |
| B3 child refusal | **Partly open**: see M2 |
| B4 known floor | Resolved (177–178, 187, 348–353) |
| M1 overrun | Resolved (348–353) |
| M2 pointer before accounting | Resolved (211–216) |
| M3 ACK mutability | Resolved (355–357) |
| M4 dispatch exit | Resolved (130–132) |
| N1–N3 | Resolved |

## Blocker

**B1. Turning off same-worker restart fails open on the one path where that restart runs.** Lines 128 and 381–385.
- The restart branch in `launch.sh` only runs when `UNBUG_RESUME_LAUNCH=1` (lines 487–613; the check is at 490).
- On resume, `control_resume.py:58-63` rebuilds the environment from `launch.json`. When `launch.json` is first written (`control_resume.py:66-67`), it keeps only the keys in `ENVIRONMENT`.
- Line 128 says the frozen launch environment holds `ENVIRONMENT` keys plus "the public batch operation ID". But `control_resume.py` isn't modified (line 43: "continues owning shell controller locks"), and the variable isn't named. So after an orphan resume the operation ID is gone. `launch.sh` can't tell it is a new batch controller, and `restart.py` grants a same-worker restart under the old cumulative cap, outside the source/ACK chain.
- Fix:
  - name the variable;
  - add it to `control_resume.ENVIRONMENT`;
  - specify the exact `launch.sh` check: when the variable is present, refuse the restart branch and run monitoring only;
  - add a matrix test that starts an orphan controller with `--resume-launch` and asserts no restart plan is produced.

## Major

**M1. The legacy `authorize` changes behaviour while the gate is off.** Lines 37, 62–65, 275–278.
- `load_locked` returns schema2, and the public `authorize` now wraps `authorize_locked`.
- Production `key_holder.py:638-639` still calls the public `authorize` with `HOLDER_ENABLED=False`.
- If the public wrapper now reads and writes schema2, then gate-off production changes the money file format, and any existing schema1 `money.json` starts refusing fresh launches. That contradicts "Production routes retain the existing fresh-only behavior while false". The holder is active on the VM (`batch-service.md:488`).
- State one of these:
  - the gate-off public `authorize` stays schema1, byte for byte; or
  - the release switches it to schema2, and you have checked that no `money.json` exists on the control VM.
- Add a gate-off regression test.

**M2. A dispatch child that crashes before `dispatch_started` is either stuck forever or retried, depending on whether the holder restarted.** Lines 331–340.
- **Holder alive:** the child dies without writing `failed`. The holder reaps it, so `dispatch_exit` is not null. The scan won't respawn it and no failed path matches, so it stays pending forever and holds a concurrency slot and its hold.
- **Holder restarted:** `dispatch_exit` is null, so the scan respawns the child. That is an implicit retry.
- `dispatch_started=false` is written under the lock before `Popen`, so it is positive proof the creator never ran.
- Fix: when the holder reaps a child, and under the lock the record still shows `dispatch_started=false` and state pending, write `failed`/`preflight_refused`. Also state whether a restart respawn of a never-started child is intended. Add tests for both paths.

**M3. Retirement has no named writer and no write order, and retirement without output has nowhere to store its proof.** Lines 136–137, 161–168, 291–293, 355–356.
- Two stores change: `operation.retired` in `reservations.json` (and the journal projection) and `ACK.retirement` in `money.json`. Neither the writer (presumably the periodic scan, under the batch lock) nor the order between the stores nor crash repair is stated.
- PRE requires "predecessor retired". It doesn't say which store it reads.
- A launched operation with no output can still retire (line 137), and that is what frees its concurrency slot. But there is no ACK to hold the receipt hashes, and the operation schema has only a boolean.
- Specify:
  - the writer and the order: money ACK retirement, then `operation.retired`, then the journal;
  - which store PRE reads;
  - where the receipt hashes live for an operation with no output. Adding a `retirement` object to the operation schema in place of the bare `retired` flag is probably simplest.

## Nits

- **N1.** `check_manifest` (`batch_money.py:54`) still requires `max_calls`. Line 263 names only `policy_load`, so add `check_manifest` too.
- **N2.** Line 246 doesn't give `committed_total_usd` for a known-total advance. It is presumably unchanged and equal to `held_usd`, since there are no top-ups. Say so; `job_config` checks that commitment never decreases.
- **N3.** These are acceptable as fail-closed choices, but the activation task must not proceed until the later dispatcher adds the per-reason retries and an incident path. List them as activation prerequisites:
  - A transient Boat inventory or policy preflight failure permanently uses up that case's fresh operation ID for the release (the UUID5 has no attempt component).
  - An accounting incident on an already-retired operation freezes batch admission until the deadline, because clearing it requires later output from the same operation.
- **N4.** The pointer's path and schema (`current/<case>.json` = `{generation, manifest_sha256}`) are inherited from `batch-service.md:190` without being restated. Fine, but say so.

## Heilmeier and scope

- **Heilmeier:** adequate. The doc has a plain objective, no cost, one increment, and its mid-term and final exams.
- **Scope:**
  - Increment 1 only, `HOLDER_ENABLED` defaults to false as a code constant, and `DIAGNOSIS_ENABLED` stays false.
  - There's no live activation, no D dispatcher dependency, no legacy booking, and no Murphy row is closed.
  - There's no cumulative call cap; dollar limits are paid-route only and owned by the router.
  - Legacy cases retire by default, schema1 money refuses, and cb5e2 and 14d35 remain set aside.
- **Security:**
  - The scoped-key predicate is gated, pinned through `TRUSTED_FILES`, and bound to `restore_recipient`.
  - Both resolver modes are read-only, and identity is passed only on stdin.

Close B1 and M1–M3, then send it for a fresh review.

## Elephant response
All B1, M1–M3 and nits accepted. Named/persisted the batch environment marker and orphan no-restart test; kept gate-off authorize unchanged; specified preflight child crash recovery; replaced bare retirement flag with a receipt object and named ordered retirement writer. Listed activation blockers. Fresh review pending.
