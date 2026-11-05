# durable-execution design review 4 (verification)

Reviewer: fresh goldfish subagent (general-purpose), read-only, personas
implementation_readiness and design_critic, Mode: REVIEW. Focused verification of
review 3's findings and of `git diff db9a0d2 b22d88b`. Verbatim below; the resolution
follows at the end.

---

# Goldfish verification review: durable-execution revision 4 (b22d88b vs db9a0d2)

Personas: implementation_readiness and design_critic. Mode: REVIEW. Standard: implementation-readiness-standard.md. Read-only.

**Tests run (all pass):** `test_durable_contract.py` 24 OK; `test_durable_policy.py` 11 OK; `test_durable_replay.py` 4 OK (44.0 s).

**Probes** (scratch, importing `factory/durable`):
- `decide(GATES, EXHAUSTED "writer:rounds", money_limited_by=BATCH)` gives `WAIT_FOR_BOUND`.
- `decide(DIAGNOSIS, EXHAUSTED, money_limited_by=CASE or NOTHING)` gives `RETIRE`.
- `Grant(0, NOTHING)` is valid.

## Review 3 blocking findings

| # | Status | Evidence |
|---|---|---|
| 1 passed gates | VERIFIED-FIXED | `StepResult.passed` is a tuple of distinct `GATE` names that cannot include the failed gate (contract:274, :283-285). Only a GATES step may report it (contract:320). The strict round-trip refuses a list in place of a tuple (contract:705-707; test `test_passed_gates`). The design says `progressed()` and `report.py` read it (design:117-118, :346). It holds gate names only, so it carries no case content. |
| 2 worker seam and release identity | VERIFIED-FIXED | `key_frame` (contract:465-468) is defined. `start`, `poll` and `cancel` have stdin, stdout and exit rules, and any other exit or unparsable output is a transport failure (contract:453-461). `RELEASE_ROOT` and `RELEASE_MANIFEST` are frozen, and both digests are defined as `launch.sh` computes them (contract:440-451; `launch.sh:683`, `:707`; `run.bench_manifest` excludes `factory/`, run.py:195-210). The `gate_state` claim holds: fingerprints hash the AST of the gate source and the listed dependency files (gate_state.py:58-91, :221). There is a practical install gap (new N3). |
| 3 ABSENT on transport failure | VERIFIED-FIXED | A transport failure is RUNNING, and ABSENT now needs an answering worker with no result and no live unit (contract:504-506, :587-592). The engine cancels attempt n before starting n+1 (contract:591; design:243). `start` refuses with `infra:attempt_busy` (contract:456-457; WP5a "Done when"). `WorkerPool.alive` (contract:576) lets WP1 detect a dead VM without waiting out the deadline. There are races inside WP5a (new N4). |
| 4 money cap and refusal | PARTIAL | Fixed: per-step caps are gone, batch-limited exhaustion waits, and extensions are charged to the batch (contract:597-629; policy:83-85; design:184-210). Not fixed: rev 4's new rule that case-limited exhaustion is a case outcome (contract:601) produces wrong case results on the path that follows it (new 1). The wait rule also misroutes, and needs a human to end it (new N1). |

## New findings

### 1. BLOCKING: under rev 4's grant rules, a case that runs out of money is retired without the diagnosis or extension ENGINEERING section 3 promises, and infrastructure waste spends the case's money

**Evidence.**
- **The routing.** Case-limited EXHAUSTED goes to DIAGNOSE (design:200; contract:601). The DIAGNOSIS step still draws on the case's own money: only "Extension attempts pass `draws_case_money=False`" (contract:621-622; design:203-204).
- **What follows.** When the case's money is spent, the diagnosis reservation is granted $0, or only what is left. A paid diagnosis call then ends EXHAUSTED, and `give_up` for DIAGNOSIS is RETIRE (policy:63-64; probed).
- **Why this is wrong.** Section 3 says "a case that runs out of rounds or budget goes to an automatic diagnosis agent". Stream D says diagnosis draws on the batch bound (stream-d.md:36-38). Here, a near-pass case that spent $50 is retired, which is a scored outcome, instead of being extended.
- **The extension request is undefined.** "The engine requests the case's whole remaining money" (contract:621; design:187-188). For an extension that comes after money exhaustion, that request is $0. So the extension gets `Grant(0, NOTHING)` and is EXHAUSTED at once, which leads to DIAGNOSE and then RETIRE.
- **Infrastructure waste.** `settle(key, usage)` books every attempt's real usage against the reservation, and that reservation drew on the case's money. This covers INFRA_ERROR retries, `infra:attempt_busy`, `infra:cancelled`, deadline kills and spent PROVIDER_LIMIT attempts.
  - Rev 4 turns exhausting that money into a case outcome. Infrastructure failures can therefore end a case through DIAGNOSE, then RETIRE.
  - Section 3 says broken runs "are never scored", and Stream D keeps infrastructure cash on a separate line (stream-d.md:39-41).
- **Why it is blocking.**
  - The frozen `Ledger` contract (WP6) and WP1's routing must agree on which attempts draw on case money and how waste is booked.
  - `settle` cannot express waste, so a correct WP6 cannot be built against contract.py as written.

**Fix (contract v5, docstring plus one keyword).**
- In the `Ledger` docstring and design:203, say that DIAGNOSIS and every extension step pass `draws_case_money=False`.
- Define the request:
  - an ordinary step requests `case_money_usd_micros`, and the ledger caps it at the case's remaining money;
  - a DIAGNOSIS or extension step requests the batch's remaining bound, with WP1 free to set a smaller figure in its note.
- Change `settle(idempotency_key, usage, *, waste: bool = False)`. The engine passes `waste=True` for INFRA_ERROR results, for PROVIDER_LIMIT results that spent money, and for attempts it settles as lost. Waste is booked to the batch only and never counts against the case's money.
- Add a policy test:
  - case-limited EXHAUSTED leads to DIAGNOSE;
  - the diagnosis grant is batch-only;
  - five INFRA_ERRORs that spend money do not reduce the case's remaining money.

### NITs

- **N1 (WP1): WAIT_FOR_BOUND triggers on the wrong condition and waits for the wrong signal.**
  - **Wrong condition.** `decide` returns WAIT_FOR_BOUND for any EXHAUSTED under a batch-limited grant, including the runner's own round limits. `Outcome.EXHAUSTED` covers "round or money limit" (contract:193), and a probe of `"writer:rounds"` gave WAIT_FOR_BOUND. That case then loops: wait for the founder, retry, hit the same limit, wait again.
    - Fix: wait only when `result.usage.paid_usd_micros >= grant.amount`. Pass the Grant to `decide`, not just `LimitedBy`.
  - **Wrong signal.** Every attempt reserves the case's whole remaining money for the attempt's full duration. With `max_concurrency > 1`, other cases' reservations hold most of the bound. A case can then get a small or $0 batch-limited grant, run out, and wait for `BOUND_RAISED`, even though settles will soon free the money. Design:209-210 calls this "intended", but it stalls the batch until the founder steps in, against section 3's "no human pit stop".
    - Fix: wake the waiters on any `settle` or `settle_lost`, as well as on `BOUND_RAISED`.
    - Do not start an attempt whose grant is below a floor WP1 sets in its note; it waits before it starts.
    - Say whether a waiting case holds a slot.
- **N2 (WP6, with WP1): label rules for `LimitedBy`.** The `Ledger` docstring does not say how ties are labelled. If the request equals the case's remaining money, it could be NOTHING or CASE. If the case's remaining money equals the batch's remaining bound, it could be CASE or BATCH, and the policy routes those two differently. WP1's fake ledger and WP6's real one could disagree. Add one docstring sentence:
  - BATCH whenever the batch's remaining bound is at or below the granted amount; otherwise CASE whenever the case's money capped the grant; otherwise NOTHING;
  - a repeated `reserve` on the same key returns the original Grant unchanged, even after `raise_bound`.
- **N3 (WP2): where release bytes come from.** `acquire(case_id, plumbing_version, bench_version)` receives two digests, and WP2 must install matching bytes. Two gaps:
  - **The bundle cannot be rebuilt to its digest.** It is a tar.gz with mtimes, so it is not reproducible, and it embeds `worker-release-manifest.json`, which hashes bench files (`launch_manifest.py:142-174`). A bundle must be built once and stored by its sha256, and nothing names who builds it or where it is kept.
  - **The two versions are not independent.** Nothing maps a `bench_version` digest back to a tree. A rolled pair (old plumbing, new bench) may fail `worker_release.py` qualification, because the embedded manifest names old bench hashes.
  - Fix: in WP2's note, add a release store keyed by digest that the release command fills. Define whether a BENCH_RELEASE implies a new bundle.
- **N4 (WP5a): three races in the wire rules.**
  - **The busy check is not atomic.** `attempt_busy` must be checked and the attempt detached under one per-case lock. Without it, two starts that race (a late `start` n whose ssh dropped, plus `start` n+1) can both pass the check.
  - **A cancelled attempt can still start.** `cancel` must create the attempt marker if it is missing, as a tombstone, so that a late `start` n does nothing.
  - **The result can be overwritten.** The result is "written once by atomic rename" (contract:483), but `rename` overwrites, so the attempt and `cancel` can each replace the other's result. Use `link()` or `O_EXCL` to make the write first-wins.
  - **Define "live"** as a unit with no result, so that a unit still tearing down after DONE does not make the next seq busy.
  - **WP1:** if `cancel` hits a transport failure, retry it until the worker answers, or wait out deadline + grace, before `start` n+1. Otherwise `attempt_busy` uses up `max_infra_retries_per_step` and turns a network flake into DIAGNOSE.
- **N5 (WP1): a gate fix released between GATES OK and SEAL.** Rev 4 makes a gate fix a PLUMBING_RELEASE ("steps started afterwards"). A case between GATES OK and SEAL therefore seals on gates passed under the old code, against section 3's "a gate change re-runs only the gates that changed for the affected cases". Fix: SEAL requires its `plumbing_version` and `bench_version` to equal those of the GATES step that passed. Otherwise the engine reruns GATES; `gate_state` reuses the gates that did not change.
- **N6 (design): wording and the section 4 rule.**
  - **Section 4.** "A gate fix is a plumbing release" (design:230; contract:448) reads against section 4 ("Plumbing and bench logic are separate"). State that per-gate versioning is kept by the `gate_state` fingerprints, or list it under Founder decisions.
  - **Stale test table.** The table at design:409 still lists "spec ceilings", which rev 4 deleted.

## Verdict: FAIL

One blocking finding is open: new 1, how case money pays for diagnosis, extensions and infrastructure waste. It needs a contract-v5 change to the `Ledger` docstring and `settle`. Review 3 findings 1-3 are verified fixed. Finding 4 is partial, and new 1 is what remains of it. N1-N6 can each be settled in the named package's own files and note.

---

## Resolution (elephant)

No finding was rejected. The fixes became revision 5 and contract version 5, with 24
contract and 13 policy tests passing.

| # | Resolution |
|---|---|
| 1 | Fixed. The `Ledger` docstring now says which money each step draws on: ordinary steps draw on case and batch; DIAGNOSIS and every extension step draw on the batch only. It also says what each step requests. `settle` gains `waste=True`, booked to the batch only, and `settle_lost` books as waste. Policy gains `draws_case_money()` and `settles_as_waste()`. Tests: case-limited EXHAUSTED goes to DIAGNOSE, diagnosis and extensions do not draw case money, and broken runs settle as waste. The ledger behaviour itself (waste never reduces case money) is WP6's "Done when" test. |
| N1 | Fixed. `decide` takes the `Grant` and waits only when usage reached a batch-limited grant, so a round limit diagnoses (tested). Waiting cases wake on every settle, not only `BOUND_RAISED`. The minimum grant is WP1's. A waiting case holds no slot. |
| N2 | Fixed. The `Ledger` docstring gives the tie-breaking labels, and a repeated reserve returns the original Grant. |
| N3 | Given to WP2: a release store keyed by sha256, and whether a bench release implies a new bundle, recorded in its "Done when". |
| N4 | Fixed in the contract docstring. A per-case lock covers the busy check. A cancel leaves a tombstone. Results are first-wins (`link()` or O_EXCL). "Live" means a unit with no result. Retrying a cancel after a transport failure is WP1's. |
| N5 | Given to WP1, and stated in the design: SEAL runs only under the GATES step's versions. |
| N6 | Fixed. The design states that per-gate versioning is kept by the `gate_state` fingerprints (ENGINEERING section 4). The stale "spec ceilings" entry is gone. |
