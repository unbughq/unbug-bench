# Stream D ordinary retries: design review 3

Reviewer: Claude Opus 5.5. Final report follows verbatim.

**FAIL: 4 blockers.**

I reviewed `docs/designs/stream-d.md:2150-2319`, which is the fourth increment plus its "design review 2 resolutions", in Mode: REVIEW. I used the zoom_out, design_critic and implementation_readiness personas with the Heilmeier and implementation-readiness standards, and checked the design against the code it references. I edited and saved nothing.

The four blockers from review 2 were each answered. Those answers hold for the narrow cases they target. But the amended design still leaves four seams where an implementer has to make a design choice, and the likely choice either holds a case on a transient failure or lets a repair produce a pass.

## Blockers

1. **The stress categories are not connected to the existing schema-v2 stress operation receipt** (`:2190`, `:2277`).
   - Today one stress round is one `pending_call`. Its receipt, `attack-state.json`, holds one `report` (it must match `round-\d+\.json`), one `operation_id`, the phases pending → completed → validated, and `review_completed.report_sha256` (`run.py:1225-1240`, `:1403-1440`).
   - Resume treats a non-authenticating receipt as `interrupted_review`. It treats a saved report with unfinished validation and no findings as `attack_unresolved` (`run.py:1241`, `:1253`).
   - `review_admitted` renames the old report to superseded and writes a fresh placeholder.
   - The design adds `round-N-categories/<binding>/state.json`, but it does not say:
     - whether all four category calls share one `operation_id`, or each gets its own;
     - what the receipt phase means while some categories are still unfinished;
     - which file `report` and `report_sha256` authenticate (an aggregate `round-N.json`? who writes it, and when?);
     - how the resume branch at `:1253-1290` sends a validated category to the next category instead of treating it as a re-review or a pass.
   - This seam is where the design's own "principal risk" lives: accidentally reusing incomplete coverage. "Joining it at write_and_attack" is not enough. Specify the receipt's state machine for category mode.

2. **Retained-answer repair can produce an approval, and its new "unresolved" state leads nowhere** (`:2179`, `:2258-2275`).
   - The section says "the schema permits unresolved/incomplete output". The dedup schema (`duplicate_of`/`reason`), the idea-realism schema (`approve: bool`) and the G8/G9 votes have no unresolved state today. The design does not say what dedup, idea, G8 or G9 should do when they get one: stop under some label, re-ask, or reject.
   - The only thing stopping a different model's "schema-only repair" from manufacturing a passing value is a prompt instruction. Examples of passing values: `approve: true`, `duplicate_of: null`, `same_bug: false`, a stress `complete`.
   - If that happens on G2 confirmation, a public match gets cleared. That is a wrong result, not a stop.
   - **Needed:**
     - a mechanical rule. For example: a repaired output may carry a pass-granting value only if that value appears in the retained raw answer; otherwise force the fail-closed value.
     - what each caller does on unresolved;
     - how a missing or empty output file is classified (malformed vs transport). Missing output is the commonest case, and "repair of nothing" has no defined result.

3. **A broad network or archive outage still ends in `freshness_evidence_unavailable`** (`:2247-2256` with `:2239-2245`).
   - The 120-second window per URL, per G2 invocation, is much shorter than a typical outage.
   - When every unflagged URL fails, they are all marked unfetched. The counts fall short, and `ensure_freshness` runs a defect top-up.
   - The new rows are also unfetchable, so after two completed "unsuccessful" repairs the case stops (`run.py:658-666`).
   - That is exactly row 12's "search and archive outages become stops", and the design claims to close row 12.
   - **Needed:** a rule that a top-up caused only by runner-unfetched rows does not charge a defect attempt while transport failures persist. Alternatively, detect an outage (for example, all of the invocation's retrievals failing transport) and wait under batch authority instead of excluding.

4. **`checkpoint_pending` is a new stop with no automatic re-entry** (`:2205`, `:2309`).
   - Batch only queues a resume for `pending_projection` or exhaustion (`batch_service.py:280-282`). `recovery.RETRY` does not match the new label.
   - So an R2 blip during stress becomes a held case that needs the founder. That is a pit stop caused by transport, contrary to row 11 and to this increment's premise.
   - **Needed:** retry publication in place with the same capped-backoff transport helper, under job authority and the batch deadline. Or name the component that resumes this label automatically.

## Major (not blocking)

- **The freshness repair state file isn't specified.** Charging only completed attempts needs a pending/completed marker. The design does not say:
  - where that marker lives;
  - the new `freshness-repair.json` version and fields;
  - how saved v1 files migrate (`recovery.expiry_freshness_stop` requires `version == 1`).

  It also leaves mixed cases open: are expired-plus-defect rows a refresh or a defect repair? Does a refresh that fixes expiry but introduces a defect count as successful?
- **A flagged URL that fails permanently holds its worker slot until the batch deadline.** Fail-closed is right, but name the stop label at the deadline. Also say whether the held slot blocks replacement launches, since the throughput goal is 24 cases in parallel.
- **The Heilmeier cost answer omits the model cost of four stress calls per round.** It covers uploads only, but each category call repeats the case read-in. Estimate the per-round cost against the shared batch money bound.
  - A simpler alternative: one call that marks each category complete as it goes, with continuation dispatched only for categories left unfinished.
- **The identity tuple for each caller is not listed.** Dedup needs the contents of the earlier statements, not its timestamped `result_path`. G8/G9 need the reviewer index plus the case including `freshness.jsonl`. G2 confirmation needs its `confirmation_contract` binding. Reusing a completed output under a too-loose identity grants a stale verdict.

## Nits

1. Exclusions "scoped to the helper call" must not drop the lane exclusions that `model_runtime.py:429` adds for outages during that call.
2. No timeline is given (Heilmeier).
3. Say how B's exhaustion facts classify `malformed_output_exhausted` and `freshness_evidence_unavailable`. This stays within the lane boundary; it is not asking for item 7 work.
4. Name the exact HTTP fixture and saved stress-report paths the tests will use.
5. Serial 120-second windows across many dead unflagged URLs can add tens of minutes to each G2 invocation. Say whether that is acceptable.

## Author response

All findings accepted. Added the category-mode attack-state state machine, a mechanical decision-projection equality check for schema repair, uniform unresolved handling, broad-outage accounting, and in-place publication retry. Also specified freshness v2 migration, caller identities, deadline labels, cost limits and fixture provenance. No implementation has started.

