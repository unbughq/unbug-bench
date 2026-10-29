# Goldfish review 2: docs/designs/status.md

Reviewer: fresh Claude Sonnet subagent, personas zoom_out + design_critic, Mode: REVIEW, read-only. Verbatim.

**Re-review: FAIL.** The rewrite fixes the field names and the missing-field handling. But the live-heartbeat premise does not hold, and the stuck-case rules built on it cannot work.

1. **BLOCKING: `progress.json` is not live on the control VM.**
   - `factory/run.py` writes it into the worker's own `HOME/sealed`. `COLLECTION_SUFFIXES` in `factory/launch_manifest.py` shows it reaches the control VM only when the worker's files are collected after it stops.
   - I found no periodic sync of it. All 37 real progress files I checked contain zero stages in `running` state.
   - So on the control VM "Running" can't be counted, and "Running, but updated_at older than 60 min" can't fire for a running case.
   - Either name the live read path, such as a per-case VM read or a heartbeat the batch controller already holds, or state that "running" comes from the batch controller's job state. The doc must say where the data comes from before any rule can be computed.

2. **BLOCKING: the two stuck-case rules contradict each other and cannot be computed.**
   - `public_progress.publish` writes only at stage start and stage end. There is no mid-stage heartbeat.
   - It overwrites a stage's row and keeps no history. `stages[stage].updated_at` is the last transition, not the stage start. There is no "stage and `updated_at` history" for the 4-hour rule to read.
   - A running stage's `updated_at` is its start time, so "60 min old" and "more than 4 h at one stage" measure the same quantity.
   - Writer calls legitimately run up to `agent_timeout` 14400s (4 h), and each round is a long call. The 60-minute rule would flag every normal writer stage.
   - Keep one rule, "running stage started more than N h ago", with N above the agent timeout. Fix the data description to match.
   - A worker that dies leaves its stage at `running`, so a stale `running` stage reads as running forever. It needs a liveness signal such as an alive worker or VM, or the stage-age rule becomes the only way a dead worker is caught. Say so.

3. **BLOCKING: nothing says what wins when the card and `progress.json` disagree.**
   - The card (`status: stopped`, `terminal_stop`) is replaced at each collection. A resumed case therefore has an old stopped card alongside a progress file that is newer or running.
   - The doc doesn't say which source decides "stopped" versus "running". `needs ruling` and `near limit` could fire from a stale card on a case that has already been relaunched.
   - Add a precedence rule. For example, compare `progress.json` `updated_at` with the card's collection time, and treat the card as current only if it is newer. Otherwise show the case as running or resumed.

4. **NIT: "Sealed X / 24" has no definition.**
   - The 24 is hardcoded, and "sealed" is not defined against the real fields. `terminal_stop: complete` and `admission` do not clearly mean sealed, and many cards in the checked batches have `status` unset or `paused`.
   - Name the one field that means sealed, and take the batch size from the batch manifest rather than a constant.

5. **NIT: "the card does not write `provider_wait`" is a design dependency the doc handles correctly, but the founder gets no signal today.**
   - The deferred table is a reasonable way to handle it.
   - Until stream A ships, `provider_wait` stops show up as an unknown `terminal_stop`. They are not flagged, because only `paused` and `complete` are exempt and everything else gets a plain-words reason.
   - The doc should say that an unrecognised `terminal_stop` shows as a case needing a look rather than being silently dropped. Otherwise an unknown reason is easy to miss.

6. **NIT: the test plan is sound but incomplete.**
   - The test needs a "running" fixture. No real saved progress file has a running stage, so it must be hand-edited. Say so, because the rewritten rules are exactly the ones with no real example.
   - Keep the "old cards produce no flags" check. It matters because 266 of 297 cards lack `case_budget`.

FAIL. Findings 1 to 3 need to be fixed before this design can be built.
