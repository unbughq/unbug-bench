# Stream D ordinary retries: design review 2

Reviewer: Claude Opus 5.5. Final report follows verbatim.

**FAIL**: 4 blockers.

I reviewed `docs/designs/stream-d.md:2150-2232` in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, in Mode: REVIEW. I used the zoom_out, design_critic and implementation_readiness personas, plus the Heilmeier and implementation-readiness standards. Every referenced item is on disk; nothing was missing. I edited and saved nothing.

The overall shape is sound. Keeping it batch-only, reusing `job_authority`, `durable_checkpoint`, `attack_binding` and the router's lane exclusion, and keeping the stress diagnostic allowance shared are all right calls. The blockers are places where the design leaves a choice to the implementer, and the likely choice either holds a case until the batch deadline or loops paid calls.

## Blockers

1. **Change item 2: a completed refresh that fixes nothing has no bound.**
   - The section moves expiry refresh from once per restore to every entry, and keeps it separate from the two defect repairs.
   - It does not say what happens when a completed `freshness_topup` call still leaves rows `evidence_expired`. For example, the model did not rerun the queries.
   - Today the `while True` loop in `ensure_freshness` (`factory/run.py:621-666`) is bounded only by `freshness_reverify_statement`. The no-progress guard at `run.py:665` covers defect repairs only.
   - With that bound deleted, an implementer must decide whether an ineffective completed refresh counts as a defect attempt, stops, or calls again. The last option is a paid loop limited only by money and the deadline.
   - **Needed:** an explicit rule. For example: "a completed refresh that leaves any refreshed row expired spends one defect attempt", or "no-progress refresh raises X".

2. **Change items 1–2: permanent failures on unflagged rows now hold the case until the deadline.**
   - Today an unflagged row that raises `InvalidInfra` is excluded and marked unfetched (`run.py:1971-1976`). The top-up can then add other rows, so this path recovers on its own.
   - The design sends flagged and unflagged HTTP failures through transport retry, says no retry count retires a case, and bounds it only by the batch deadline.
   - Some failures are permanent, not transient:
     - a site that always resets or times out the connection (`fetch` raises `InvalidInfra`);
     - an archive.org reply that never parses (`freshness_retrieval.py:77`, "archive retrieval inconclusive").
   - A case with either one now holds until the batch deadline, where today it continues. That is a regression for row 12's hands-free goal, and the section does not list it under deletions.
   - **Needed:** define when a persistent transport failure on an unflagged row falls back to the existing exclusion, such as a per-row wall-time budget, or justify the change and add it to the deletions.

3. **Change item 3: spending repair routes through the router does not produce the promised stop.**
   - The router excludes lanes keyed `pool/route`, where `pool` is the account (`model_router.py:96-117`). "Account changes are not new model routes" therefore means excluding every lane for a route. The section does not say this.
   - `router_excluded` lives in memory on the context (`model_runtime.py:429`, `diagnosis_dispatch.py:360`). It is lost on restart, and outage exclusions already share it.
   - In batch mode (`UNBUG_PROVIDER_WAIT=1`), when every route is excluded, `await_lease` does not raise `provider_routes_exhausted`. It waits until the batch deadline (`model_router.py:429-461`).
   - An implementer who follows "exclude the route through A's router" therefore gets a provider wait and then `provider_wait_deadline`, not the "distinct deterministic-output stop".
   - **Needed:**
     - persist spent routes, keyed by route rather than lane, in the durable repair record;
     - put them back into `router_excluded` on re-entry;
     - have the repair helper raise the deterministic-output stop itself, before admission, once every approved route is spent;
     - name the stop label;
     - say whether the next route gets a schema repair of the retained answer or a fresh full call. The text supports either reading.

4. **Change item 4: per-category stress runs conflict with "runs the existing prompt".**
   - `factory/prompts/attacker.md:22-26` and `:92` require the "review incomplete" marker and `complete:false` until *all* categories are inspected. A call scoped to one category can never mark itself complete under that contract.
   - So the prompt or the output contract must change, and the design must say how:
     - the per-category completion field or schema;
     - how a category report maps to `classify()`/`attack_report`;
     - whether the change alters the `prompt` hash in `attack_binding` (`run.py:882-889`). If it does, every saved receipt changes binding, which starts fresh coverage, and that effect should be stated.
   - The section should also say where categories are numbered and which names are stored in each report.

## Major findings (not blocking)

- **No file list or phase order.** The readiness standard asks for target files and stable phases. The section names neither:
  - where the new helper module and record schema live;
  - whether `bin/run_validity.retry` is extended or replaced;
  - which `run.py` functions change;
  - the commit order of the four changes.
- **Superseded HTTP receipts need a naming rule.** `retrieve()` writes `0-0.body` and similar names into a directory keyed only by the binding hash (`run.py:1957`). A refresh with the same binding overwrites the old files unless a new directory name, such as a generation suffix, is specified.
- **"Blocks next paid call" needs a scope.** Say whether a failed remote publication blocks only the next stress category or every paid call for the case. Also name the re-entry check: `durable-checkpoint.json` with `remote_durable != true`.

## Nits

- The Heilmeier cost, timeline and risk answers are only implied by the "(large)" label in the roadmap. One line on extra archive uploads would help: one forced full checkpoint per category, up to 4 per round.
- "Shared across categories for the revision": the allowance is keyed `attacker-{round}` (`run.py:418`). Say "per round" so that holds.

## Author response

All findings accepted. Added explicit failed-refresh charging, a 120-second
unflagged transport window with exclusion/top-up fallback, durable route-level
exhaustion with `malformed_output_exhausted`, schema-only fallback semantics,
and a category completion contract with intentional prompt-binding migration.
Also named implementation files/order, superseded HTTP directory naming,
publication marker and all-dispatch barrier, and checkpoint upload cost.
No implementation has started. Requesting a fresh design review.
