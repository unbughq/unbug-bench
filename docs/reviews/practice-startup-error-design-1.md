# Fresh goldfish design review: `docs/designs/practice-startup-error.md`, round 1

**Result: FAIL.** There are 2 blockers, 3 majors and 4 nits.

I reviewed in Mode: REVIEW with the zoom_out, design_critic and implementation_readiness personas, against `heilmeier-standard.md` and `implementation-readiness-standard.md`. Everything was read-only on `t3/batch-service-control-vm` @ 860e1c0. I compared against pinned runner b75c9b4, and current `factory/run.py` is identical at the relevant lines. I made no edits, ran no Docker, network or provider calls, and used no delegates.

## Blockers

### B1. Deleting the early Compose start may only push the failure later, where it costs money
**Scope:** "Change and deletion", the exams, and new-practice-startup-1.

- **The deleted command is the same command G3 runs.** The runner's `COMPOSE + ["up","-d","--wait","postgres","redis"]` (`factory/run.py:3387`) and `bench.setup`'s `dc("up","-d","--wait","postgres","redis")` (`bin/bench.py:315`) use the same compose file. That file fixes the project name with `name: unbug-bench`, and slot 0 adds no `-p`.
- **G3's `down -v` cannot remove a container that `up` failed to adopt.** G3 runs `prepare_factory_main` (`bin/bench.py:360-368`), which only adds `dc("down","-v")` first. `compose down` removes the containers Compose recognises as belonging to the project. Those are the same containers `up` would have recreated.
  - A name conflict on `up` means Compose did **not** recognise `/unbug-bench-postgres-1` as its own. So `down` leaves it in place, and G3's `up` hits the same conflict.
  - The design's own disclaimer admits this: it "does not claim arbitrary foreign Docker containers can be safely reclaimed by the later bench owner."
- **The only reading where deletion is enough is a race, and no racing process is named.** The design hints that the problem is "outside the lock", which would mean a second process running `up` at the same moment. It names no such process. The report's local experiment shows that a container with old Compose labels is recreated cleanly, which rules out the simple stale-container explanation and points towards a container Compose does not recognise.
- **If the failure recurs, it now happens after paid model work.** G3 is the first early gate after the writer round (`EARLY_GATES`, `run.py:36`; G3 is not in `gate_state.REUSABLE`). A recurrence becomes `InvalidInfra("bench setup did not complete")` after a writer round. `ENGINEERING.md` cites up to $15.05 for one writer round, and the run may also loop on infra retries. Today the same failure costs $0. The Risk section calls this "a separate image problem". It is the same problem.
- **The planned exam cannot catch this.** After the deletion, no Docker call happens before provider preflight. So "afterwards it must reach provider-preflight" only proves the line was removed. It says nothing about whether the conflict is handled.

**Required:**
1. **Find the mechanism from evidence already retained (offline).** Decrypt in-process and quote sanitized `logs/commands.log:1–2`, the Compose progress lines before the error:
   - "Recreate" means Compose saw the container, which points at a race or recreate-path cause.
   - "Creating" means Compose did not see it.

   This needs no remote access.
2. **Then pick the matching fix:**
   - **Compose did not adopt the container:** removing the early start is still right, since it is redundant. But the fix belongs in the locked owner. Inside `prepare_factory_main`, after `down`, force-remove (`docker rm -f`) the project's fixed container names. `setup`'s `remove_seed` and `bake-image.sh` already remove fixed-name containers this way. The alternative is to fix the bake so the image ships with no stopped containers (`bake-image.sh` currently only `docker stop`s them).
   - **Race:** name the concurrent actor and show the lock excludes it.
3. **Exam:** replay the real conflict at G3's `up` as well, not only at the deleted call. Show either that the owner clears it, or that it fails before any model spend.

### B2. The proposed error record would not have shown the actionable message for this very failure
**Scope:** the runner_error record paragraph and new-practice-startup-2.

- **The record would hold nothing new.** The exception is `RuntimeError("exit 1")`, raised by `sh` at `run.py:161`. Its traceback frames are `run.py:3387` and `sh:161`. The proposed `runner-error.json` stores the exception type, message and traceback locations. For this failure that is exactly what the card and `runner.log:4–9` already held. The Docker conflict text exists only in `commands.log:3–4`.
- **The fix belongs in `sh`, where every `check=True` caller goes through.** When the check fails, include the command name and a bounded tail of that command's output in the `RuntimeError`.
  - Record `out.tell()` before the command runs and read back from that offset afterwards. Both capture modes write stderr to `commands.log`.
  - No code matches on the `"exit N"` text, so changing the message is safe.
  - The existing `log(c, traceback.format_exc())` then carries the actionable text into retained `runner.log` with no new file.
  - Known limit, worth a `ponytail:` comment: commands running in parallel can interleave lines in that tail.
- **Closing test:** feed the fixture's real conflict text as the output of a failing command into the real `sh` and the real handler. Assert that the retained `runner.log` contains it and that the public card does not.

## Majors

### M1. The `COMPOSE` constant is still used elsewhere
**Scope:** "its now-unused COMPOSE constant".

- `factory/extension_evaluator.py:235` assigns `runner.COMPOSE` for the private bench.
- `tests/factory/test_stream_d_comparison.py:399` patches `'COMPOSE'` with `patch.multiple`, which raises `AttributeError` once the attribute is gone.

The design must list both, either deleting them or keeping the constant. As written, the deletion list fails the zero-decision rule.

### M2. The secret-scrubbing work is more than needed, and its test would overclaim
**Scope:** the scrub and bounds paragraph, and the sentinel exam.

- **The test would claim something the system does not deliver.** The same encrypted evidence keeps raw content in several places that the scrub does not touch:
  - `commands.log` (all command output);
  - the `runner.log` `$` command lines;
  - `gate-details/*.crash-*.json` (raw message and traceback, `gate_pipeline.py:71-72`).

  So "sentinels absent from decrypted evidence" would only pass if the sentinel were placed where those logs never see it. That makes it a test of the expected shape rather than of real behaviour.
- **Reading the RAM secret files to build a scrub list adds new handling of secrets.** It also adds bounds, link checks and a fallback label that each need their own tests.
- **Replacing the raw traceback write drops chained-exception context.**
- **Simpler alternative:** with the B2 fix, the message only adds bytes that are already in encrypted `commands.log`, so there is no new exposure. The public card gets a constant pointer, for example `error_evidence: "logs/runner.log"`, and no message content. Test that a sentinel in the command output is absent from the card. Delete the separate JSON record, the scrubber and the fallback label.

### M3. Writers may lose a working shop before G3
**Scope:** the claim that the early start is "redundant".

- In slot 0, `bench.reset` does not start Postgres (`bin/bench.py:448-451`, which applies only when `UNBUG_FACTORY_SLOT` is set). It then runs `sql` via `dc exec postgres`.
- The builder prompt describes the G4 and G5 `bin/checkpoint` runs. Today a writer's self-check runs against the baked, seeded shop that the early `up` started.
- After the deletion, any such pre-G3 self-check fails.
- I did not confirm whether writer sandboxes have Docker access.

The design must state whether writers do this, and either accept the change explicitly or keep a locked pre-model start. This also connects to B1: a locked fresh preparation before model admission would keep the failure at $0.

## Nits

- **N1. Wording conflict between design and report.** The design says "existing image container" as fact. The report says "no stronger cause claim is made". Use the report's wording until B1's evidence settles it.
- **N2. The Objective paragraph is jargon-heavy for the Heilmeier standard.** It assumes the reader knows G3, Compose, "RAM secret files" and "authored provider edge". Add one plain-language objective sentence.
- **N3. The missing-accounting refusal is kept, correctly.** It is a consequence of the crash, not a cause. Note, though, that any runner_error before model admission still produces a card that cannot be collected. Record that as a known pit stop, outside this design's scope.
- **N4. Close new-practice-startup-1 only against B1's G3-level replay.** The pre-preflight replay alone is not enough.

## Smallest fix that would pass
1. Delete the early `up` in `run.py:3387`, along with `COMPOSE` and its two other users. This depends on M3's answer.
2. Settle the mechanism from `commands.log:1–2`. If Compose did not adopt the container, force-remove the fixed-name project containers inside the locked `prepare_factory_main` before `setup`.
3. Put a bounded output tail in `sh`'s check-failure message, and add a constant evidence pointer to the card.
4. Write two tests, both driven by the fixture's real conflict text:
   - a G3 replay;
   - an `sh`-to-handler retention test that also proves the card contains no message.

**Verdict: FAIL** (B1, B2 open).

## Writer disposition

All findings accepted. Revision 2 replaces standalone startup with existing locked fresh preparation before models; adds fixed-name cleanup to its owner; retains COMPOSE and the working shop; adds bounded sanitized command-output diagnostics and a constant public evidence pointer. The new JSON artifact and RAM scanning are deleted. Real retained Creating lines settle B1. Missing-accounting early-crash pit stop remains explicitly open.
