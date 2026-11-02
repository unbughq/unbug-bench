**Verdict: FAIL.** Round 2 has one blocker. Under your speed rule, the writer stops here and sends the 3-line note below to the parent; there is no round 3.

I only read files: no edits, workers, network, paid calls or secrets.

## Blocker

**The cleanup watchdog always deletes the worker before the normal collection can run, so the run can never publish.**
- **Where:** `practice-readiness.md:136-137` and `practice-run.md:21,23`.
- **What the plan says:** the watchdog deletes the worker at `pending_since + 1800 s` (reservation + 30 min).
- **What the code does:** with a 1-hour TTL, `bin/boat-launch-guards.sh:35-45` sets the default margin to 1800 s, so `retire_at = 3600 - 1800 = 1800` counted from `$state/$id.started`. That timestamp is the worker's creation (`factory/launch.sh:428`). The controller only starts collecting at `started + 1800` (`boat-launch-guards.sh:387-389`).
- **The clash:** `started` always comes after `pending_since`. Waits for arming, the TEMPFAIL retries, Boat creation and readiness all push it later. So the watchdog always deletes the worker first.
- **Why publication then can't happen:** `unpublished()` needs both `complete` and `collected/<case>.scorecard.json` (`factory/batch_holder.py:518-519`). After an early delete there is no collected scorecard. That means:
  - the hook inside `collect()` never runs, so the publication fault is never exercised;
  - the success line "consistent publication records" (`practice-run.md:4-5`) can't be met.
- **The plan contradicts itself:** it says "normal collect-before-delete first" (`practice-run.md:23`), but the deadline it sets prevents exactly that.
- **Fix (one value, both docs):** set the deadline after the controller's collection window and still strictly before the provider TTL. For example, `pending_since + 3300 s`, plus a refusal if dispatch hasn't started within a bound that keeps `started + 1800` plus collection time below that deadline. Or tie the deadline to the recorded `started`, keeping it under `started + 3600`. Add a test that `deadline > started + retire_at` and `deadline < started + ttl`.

## Checked against source and fine
- **Roles:** the manifest flags exist (`run.py:3176-3183`). `--ttl-hours` and `--max-spend` are read by `launch.sh:50-54`. All five routes have a real `route_maximum` with these maxima:

  | Role | Max per call |
  |---|---|
  | MiniMax | $0.690001 |
  | DeepSeek | $1.17440612 |
  | MiMo | $1.7104906 |
  | Claude Opus 4.5 compact | $3.0 |

  The four families differ, nothing routes to Codex, and slot 1 in the default `rotation-3writers.json` validates while every role is overridden. `bind` still requires `args[:1]=='1'` and `--rotation-slot`, which the manifest satisfies.
- **Activation call sites:** the three named sites in `batch.py` (lines 149/168/178) and the three in `key_holder.py` (443/475/492) match the code.
- **Fault hook and retries:** the fault point (outbox pending, before transport) and the `record_child` and `RETRY_LIMIT=5` behaviour match `batch_holder.py:321-346` and `:708-716`.
- **Commands:** `tools/qualify-batch-inputs.py` exists.
- **Round-1 findings B1–B3 and M1–M6** are resolved as the disposition describes.

## Optional nits
1. "Before BOTH dispatch preflights" (`practice-readiness.md:176`): name the two places, i.e. before `boat-call list` and again inside the second `money.locked` before `dispatch_started=True`.
2. `batch_holder.main()` (line 832) calls `enabled()` before the policy is loaded. Under the new `enabled(policy, root)` it has to load the policy first; say so.
3. The watchdog never ends if dispatch never happens (for example `preflight_refused`). Step 7 should state that the operator stops the unit after a verified completion, or after a terminal state with no dispatch.

**3-line note to the parent:**
1. FAIL, round 2: the watchdog deadline (`pending_since + 1800 s`) falls before launch.sh's collection point (`started + 1800 s`, from TTL 3600 minus the default 1800 margin).
2. So the worker is always deleted uncollected: no publication, the fault is never exercised, and the success line can't be met.
3. Fix: move the deadline to after `started + retire_at` plus collection time and before `started + 3600`, test that inequality, and update both docs.

## Disposition

Accepted. Parent approved the worker-start-based timing fix after round 2, without a third design review. Implement start + run cap + collection grace strictly below start + provider TTL, refusing incompatible timings. Optional nits accepted.

