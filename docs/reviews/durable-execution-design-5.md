# durable-execution design review 5 (verification)

Reviewer: fresh goldfish subagent (general-purpose), read-only, persona
implementation_readiness, Mode: REVIEW. Focused verification of review 4's finding 1
and of `git diff b22d88b ffc678d`. Verdict: **PASS**. Verbatim below; the resolution
follows at the end.

---

# Goldfish verification review 5: durable-execution revision 5 (ffc678d against b22d88b)

Persona: implementation_readiness. Mode: REVIEW. Standard: implementation-readiness-standard.md. Read-only.

**Tests run (all pass):** `test_durable_policy.py` 13 OK; `test_durable_contract.py` 24 OK.

## Review 4, finding 1: VERIFIED-FIXED (the contract can now express it; what is left is owned by single packages, listed below)

| Required by review 4 | Status | Evidence |
|---|---|---|
| DIAGNOSIS and every extension step pass `draws_case_money=False` | Fixed | Ledger docstring (contract:624-630); design:193-198; `policy.draws_case_money` (policy:92-94), which returns False for DIAGNOSIS and for `in_extension`; tested in `test_diagnosis_and_extensions_never_draw_case_money`. |
| The request is defined | Fixed | Ordinary steps request `case_money_usd_micros`, capped by the ledger. Batch-only steps request the batch's remaining bound, or a smaller figure from WP1 (contract:627, :629-630). The tie labels and the rule that a repeated reserve returns the original Grant are frozen (contract:633-635). |
| `settle(..., waste=True)`, booked to the batch only | Fixed | contract:636-641, :647; `policy.settles_as_waste` (policy:97-100) covers INFRA_ERROR (which includes `attempt_busy` and `cancelled`) and PROVIDER_LIMIT results that spent money; `settle_lost` books as waste (contract:641). |
| Policy test: case-limited EXHAUSTED leads to DIAGNOSE, the diagnosis is batch-only, broken runs are waste | Fixed | `test_batch_money_waits_case_money_diagnoses`, `test_diagnosis_and_extensions_never_draw_case_money`, `test_broken_runs_settle_as_waste`. |
| "Five INFRA_ERRORs do not reduce case money" | **Claim false** | The resolution says this is WP6's "Done when" test, but the WP6 row did not change (design:374: "Implements `Ledger`… Replay gives an identical ledger. Concurrent reservations never exceed either limit."). See N1. |

WP6 and WP1 now share one frozen rule for which money each attempt draws on and how waste is booked, so neither has to change contract.py. The blocking part is closed. The money path still has gaps, but each one sits inside one package (N2-N5).

## New findings

None are BLOCKING.

### N1 (WP6): the ledger behaviour the resolution promised is not in WP6's "Done when"
design:374 does not list the waste test, the tie labels, or the repeated-reserve rule, so a WP6 built to its row can skip all three.

**Fix:** add these to WP6's "Done when":
- settling five INFRA_ERRORs that spent money, with `waste=True`, leaves the case's remaining money unchanged and lowers the batch's remaining bound;
- `settle_lost` does the same;
- the three tie cases of the label rule (contract:633-635);
- a repeated `reserve` after `raise_bound` returns the original Grant.

### N2 (WP1): SEAL, and a GATES rerun after an extension, still draw on case money that is already spent
- The contract lists "SEAL outside an extension" as an ordinary step (contract:625). `Counters.in_extension` covers only "one writer round + stress + gates" (policy:39).
- So after an extension passes, its SEAL draws on the case's money. For a case that went to diagnosis because it ran out, that money is $0: it gets `Grant(0, CASE)`.
- Rev 5 adds a path where SEAL needs the GATES step's versions, or the engine reruns GATES first (design:253). If a release lands after an extension, that rerun is not in the extension, so it also gets `Grant(0, CASE)`.
- GATES is paid: it runs calibrators and reviewers. The rerun therefore ends EXHAUSTED under a CASE label, goes to DIAGNOSE, and uses up a diagnosis or an extension or retires the case. That is a wrong scored path, from the same root cause as review 4 finding 1.
- WP1 owns `policy.py` and the Counters, so WP1 can fix this alone.

**Fix:** once a case has had its first DIAGNOSE, no step of that case draws case money. Either make `draws_case_money` return False when `counters.diagnoses_used > 0`, or define `in_extension` to cover every step from EXTEND until the case seals or returns to diagnosis, including SEAL and any GATES rerun. Update the contract:625 wording in WP1's note, and add a policy test.

### N3 (WP1): the diagnosis and extension request figure fails either way, and the policy turns a small figure into a case result
- **Default figure (the batch's whole remaining bound, contract:629-630):**
  - One diagnosis or extension step holds the entire bound while it runs. Every other case gets a $0 BATCH grant and waits.
  - A lost attempt then goes to `settle_lost`, which "books the whole grant" (contract:641), so the whole remaining bound becomes waste. Every case is then left in WAIT_FOR_BOUND until the founder raises the bound, against section 3's "no human pit stop".
- **A smaller WP1 figure:**
  - A grant below the batch's remaining bound is labelled NOTHING (contract:633-635).
  - EXHAUSTED under a NOTHING grant goes to `give_up()` (policy:84-86). For DIAGNOSIS that means RETIRE, and for an extension it means DIAGNOSE.
  - So the WP1 figure acts as a price cap that turns plumbing into a case result, which the design itself forbids (design:186-187).

**Fix (WP1 note and `policy.py`):**
- Pick a finite figure for batch-only steps.
- For a step with `draws_case_money` False, treat EXHAUSTED with `paid >= grant` as RETRY with a fresh grant. That is plumbing, not a case outcome, and it is bounded by the batch bound, where it becomes WAIT_FOR_BOUND.
- Add a test: a diagnosis that spends its whole NOTHING grant does not RETIRE.
- Also add "the batch-only request figure" to WP1's "Settled in WP1's own note" list (design:369). The contract delegates it there, but the list does not mention it.

### N4 (WP1): the minimum grant must not make a case-limited attempt wait
- design:229-230 says an attempt whose grant is below WP1's minimum "waits before it starts".
- For a grant labelled CASE, the case's own money never comes back. Settles and `BOUND_RAISED` do not refill it, so the case waits forever.
- The same happens after a BATCH-limited exhaustion in the tie case. The case's money and the bound were equal, so the next grant is `Grant(≈0, CASE)`.
- Stream D's rule is to diagnose without calling ("At spent $44 and next maximum $12, diagnose without calling", stream-d.md:67-68).

**Fix (WP1 note):** a sub-minimum grant labelled CASE goes to DIAGNOSE without starting. Only a sub-minimum grant labelled BATCH waits. Add a test for each.

### N5 (WP5a): the worker's in-process case budget still enforces $50, so a batch-funded extension stops on the worker anyway
- `run.py` stops writer rounds on the card's cumulative `case_budget` (`limit_usd - spent_usd < estimate`, run.py:1515-1520 and :1677-1681). It also uses `writer_round_estimate`'s floor.
- That card is in the snapshot every step restores. An extension writer round for a case that spent its $50 is refused inside the worker with `budget_exhausted`, whatever its batch-funded `money_ceiling_usd_micros` is.
- `StepInput` carries no extension flag (contract:208-224), so the worker cannot tell an extension round apart.
- WP5a's list of in-process lifecycle it turns off (design:373) does not include this check.

**Fix (WP5a "Done when"):** under the engine, `money_ceiling_usd_micros` is the only money stop. It is applied to this attempt's spend, not to cumulative case spend. Turn off `case_budget.limit_usd` and `writer_round_estimate`. Test: restore a snapshot with spent ≥ $50, give a $20 ceiling, and check the writer round runs.

### N6 (WP1, with WP5a): a cancelled attempt's usage is unspecified, so `settle(waste=True)` can under-book the batch
- `cancel` writes INFRA_ERROR `infra:cancelled` "if none exists" (contract:461-463), and nothing says what `Usage` that result carries.
- A deadline-killed attempt may have spent its grant. If the result carries `Usage()`, rev 5's "cancelled… attempts settle with waste=True" (design:221-223) books $0, and the batch can overshoot its bound. That breaks the guarantee at contract:631-632.

**Fix:** WP1's note settles every `infra:cancelled` result with `settle_lost`, which is conservative. Alternatively, WP5a's `cancel` reports the attempt's usage so far, read from its model-call ledger, and WP1 settles that. Either way, apply N3's finite figure, so that `settle_lost` cannot book the whole bound.

### N7 (WP1/design): stale text about the bound wait
Rev 5 changed the wait rule, but three places still describe the old one:
- design:154-156 still reads "If the batch bound shaped that attempt's grant, WAIT_FOR_BOUND: wait for `BOUND_RAISED`". It needs the "usage reached the grant" condition and the wake on every settle that design:218-230 now gives.
- `LimitedBy.BATCH`'s comment (contract:607) and `Action.WAIT_FOR_BOUND`'s comment (policy:27) still say "waits for BOUND_RAISED".

**Fix:** align all three with design:227-228. The contract comment is not normative, so WP1's note can record the intended meaning.

## Verdict: PASS

Review 4 finding 1 is fixed at the contract level. `Ledger` now freezes which money each attempt draws on, the request, the tie labels and waste booking. The policy helpers and tests match, and every wave-1 package can still be built and tested on its own against contract.py. N1-N7 are each owned by one package: WP6 (N1), WP1 (N2, N3, N4, N6, N7) and WP5a (N5, with WP1 on N6). N2 and N5 should be settled before WP1's and WP5a's mid-term exams. Left open, they repeat finding 1's harm: a case that ran out of money loses its extension.

---

## Resolution (elephant)

The review passes. The NITs are handled as follows.

| # | Resolution |
|---|---|
| N1 | Added to WP6's "Done when" in the design and in the wave-1 brief: waste and `settle_lost` leave the case's money unchanged, the three tie labels, and re-reserve after `raise_bound`. |
| N2 | Fixed now in `policy.py`, WP1's baseline. `draws_case_money` is False once `diagnoses_used > 0`, so SEAL and any GATES rerun after a diagnosis draw on the batch only. Tested. |
| N3 | Fixed now in `policy.py`. EXHAUSTED on a batch-only step whose usage reached its positive grant is RETRY with a fresh grant, not a case outcome. A zero grant never counts as used up, so it cannot loop; the existing test caught that while the fix went in. Tested. A finite request figure for batch-only steps is added to WP1's list. |
| N4 | Given to WP1 and stated in the design: a sub-minimum CASE grant goes to DIAGNOSE without starting; only a sub-minimum BATCH grant waits. |
| N5 | Added to WP5a's "Done when": under the engine, `money_ceiling_usd_micros` is the only money stop, applied to the attempt's own spend. `case_budget` and `writer_round_estimate` are turned off. The snapshot test uses spent ≥ $50 and a $20 ceiling. |
| N6 | Given to WP1: every `infra:cancelled` result settles with `settle_lost`, using the finite figure from N3. |
| N7 | Fixed. The design's EXHAUSTED bullet, and the `LimitedBy.BATCH` and `WAIT_FOR_BOUND` comments, describe the "usage reached the grant" condition and the wake on every settle. The contract comment change is not normative, and the contract stays at version 5. |
