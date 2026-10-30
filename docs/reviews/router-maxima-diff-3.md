# Router maxima diff review 3 (integration)

**Reviewer:** a fresh, read-only goldfish from a different model family than the author. Personas: `zoom_out` and `implementation_readiness`, `Mode: REVIEW`.

**Scope:** frozen HEAD `0a91d8abb7fee8c275af50ae641ab8ff94418c2b` against integrated base `6abe1690d2cc65078a64b347d923cd0aba6be655`. I compared it explicitly with the old reviewed `d6e1f80`.

**What I read:**
- the egm `zoom_out` and `implementation_readiness` agents and their two standards;
- the founder's current `ENGINEERING.md`, read directly; it is byte-identical in the worktree;
- `docs/murphy-register.md` and `docs/factory-single-path.md`;
- interfaces §2, §3, §4, §7 and the new §8;
- the router.md follow-up and its integration paragraph;
- the stream-d.md accounting obligations;
- `job_authority.py`, and `budget.py` reserve/settle;
- design reviews 2–4 and diff reviews 1–2, with their author responses.

**What I did not do:** edit, compile, run tests, or launch anything.

## Verdict: FAIL. 0 Blockers, 1 Major, 2 Nits. Full-suite validation is still pending.

The code integration is faithful. The one Major is a documentation and handoff gap that the integration test itself exposes. Fixing it needs no source change to A.

**Full suite:** `/tmp/router-maxima-full-0a91d8a.log` had reached 43 scripts with no failures; it was then on `tests/factory/test_case_budget.py`. `/tmp/router-maxima-full-0a91d8a.json` did not exist yet. **I do not claim the full suite passes.**

---

## Integration assessment

I checked each of the author's claims myself.

**Byte identity:**
- These A files match `d6e1f80` exactly: `model_call_gate.py`, `model_router.py`, `model_runtime.py`, `token_prices.py`, `calibration.py`, `gate_state.py`, `test_model_router.py`, `test_model_runtime.py`, `router_test_support.py`, `test_invalid_runs.py` and `router_maxima_pin_probe.py`.
- These D/B files match `6abe169` exactly: `budget.py`, `job_authority.py`, `job_config.py`, `batch_money.py`, `batch.py` and `launch.sh`.
- `interfaces.md` §8, from its heading to the end of the file, is byte-identical to `6abe169`. Section 7 differs from `d6e1f80` only by the §8 heading that follows it.

**Merged files:**
- `run.py`: base..HEAD contains only A's three `model_call_cap` re-raise lines (`:307`, `:2260`, `:2643`). B's `--factory-job-config` and `job_config.install` hooks are kept unchanged.
- `launch_manifest.py`: it adds `token_prices.py` and `model_call_gate.py` to TRUSTED and REQUIRED_RELEASE. B's `batch_money.py`, `job_config.py`, the control-recipient file and the `factory/batches/*.json` glob all remain.
- The manifest test expects the union of A's and B's files. `launcher-sha256.json` pins only two unrelated helpers, so it needs no regeneration.

**D's settlement reader against A's receipt:**
- `_usage_leaves` requires `lease_id` (str), `final_usage_known` (bool), `events` (list) and `booked_event_ids` (a list of strings). A's receipt has all four.
- A's extra fields (`max_*`, `price_source`, `cap_used`, `unidentified_events`, `outcome`) are ignored by D.
- A's stricter `final_usage_known` (closed, no unknown requests, no in-flight requests) can only push D toward its conservative estimate: maximum minus already-booked.
- D never consumes `cap_used`. An unknown receipt therefore settles at the reservation maximum ($50), not at the gate's held W ($19.04). That is conservative and consistent.

**D's Lease fixtures:**
- The three `test_stream_d.py` constructors now add `synthetic_maximum('accounting-fixture-only')`.
- `reserve_invocation` never validates a lease's maximum fields, so the fixtures stay accounting-only, exactly as labelled. All original D assertions are unchanged.

**The new contract test** (`test_model_call_maxima.py:247`):
- It uses a real Store-policy Lease, checked with `valid_lease`, and B's actual `job_authority.for_case`.
- With authority of `49.999999999`, it raises `money_wait` and the ledger bytes are unchanged.
- With authority of `50`, it admits a `maximum_usd` of `'50.000000000'` with $50 outstanding. The unknown-cap receipt settles at 50, the replay settles at 0, and `events==[]`. A revision mismatch makes `for_case` refuse.
- Its comments say the binding is synthetic and that D2 and B's installer are not exercised. That is accurate.

**Linux gate fixture:**
- `integration_base` is `6abe169`.
- I recomputed all 7 `source_sha256` entries against HEAD, including the new `budget.py`. All match.
- All 10 records ran the pinned 2.1.299 CLI on x64 and ARM64, with `returncode` 0. Their `cap_used` matches the brief:

| Scenario | Forwarded | Validated | Unknown | Notes |
|---|---|---|---|---|
| tools | 3 | 3 | 0 | |
| retry | 2 | 0 | 2 | exhausted, ends in `model_call_cap` |
| compaction | 4 | 3 | 1 | `compact_boundaries=1` |
| output | 2 | 2 | 0 | |
| concurrency | 3 | 3 | 0 | not exhausted |

- The scope string says it is not live-WebFetch evidence. That is accurate.

**Things this change does not touch:**
- No D Decimal booking, B authority, E subprocess handling or C scoring code changed.
- Murphy rows 2, 3, 4, 20, 47 and 48 stay OPEN, and nothing claims to close them.

---

## Major

### M1. The $50 route maximum uses up the whole default $50 job commitment. Under the integrated D/B contracts, a case can then make only one Claude call. This is not documented.

**Scope:**
- `docs/designs/router.md:720-727` (the integration paragraph);
- `docs/designs/interfaces.md:284` and `:293` (§7);
- `docs/reviews/router-maxima-validation.md`;
- demonstrated by `tests/factory/test_model_call_maxima.py:247`.

**Evidence:**
- **D's reservation rule.** `budget.reserve_invocation` (`budget.py:159-161`) admits a call only when total + outstanding + maximum ≤ commitment.
  - The enforced route maximum is `lease.max_usd = 50.0`. D must reserve at least the enforced bound.
  - §8's default `committed_total_usd` is `"50.000000000"`.
  - The new test proves that 49.999999999 already refuses.
  - So on a fresh $50 job, call 1 is admitted. After it settles at any real cost above $0, say $3, call 2 needs $3 + $50 > $50 and gets `money_wait`.
- **D's ordinary threshold.** stream-d.md:66-70 diagnoses whenever `spent_usd + next_writer_invocation_max > ordinary_limit_usd`, and the default limit is $50. With a $50 writer maximum, every Claude writer round after a priced first call goes to diagnosis.
- **Concurrent owners.** A G10 tester and reviewer would need $100 outstanding.
- **Qualification.** stream-d.md:529 fails qualification only when the maximum *exceeds* $50. So this route passes qualification and then halts in operation.

**Why it matters:**
- The brief requires a positive bounded route and says "all refusal is insufficient". Under integrated D, the claimed positive route is positive for **one invocation per $50 owner**.
- Every later call becomes a `money_wait` revision cycle or a diagnosis. That is the hidden pit-stop class ENGINEERING §4 and the factory throughput goal forbid, and it would first surface in D2 or in B's practice run.
- The integration paragraph and validation doc present "$50 admits the route's maximum" as the contract fitting, without stating this consequence.
- This is not an integration code defect, and the brief fixes the $50 finance. But the cross-contract consequence has to be visible before D2 wires `lease.max_usd` into reservations.

**Action:** documentation only; no A source change.
1. Add one paragraph to router.md's integration section and to interfaces §7. State that with `max_usd=50` and the default $50 commitment:
   - D2 can admit at most one Claude invocation from zero spend;
   - D's ordinary threshold diagnoses after any priced writer call;
   - concurrent nested owners cannot both reserve.
2. Name this as an explicit prerequisite for enabling D2, owned by the founder, D and B: size job commitments (or B revisions) to settled + per-call maximum, or approve a lower route maximum against the 153-receipt fit table. A does not choose.
3. Repeat the limit in `router-maxima-validation.md`, so that B's practice qualification does not treat a first-call success as availability.

---

## Nits (optional)

**N1. `reserve_invocation` does not bind `maximum_usd` to the lease.**
- **Where:** interfaces.md:284, "D reserves only after admission".
- **What happens:** `reserve_invocation` accepts a `maximum_usd` the caller chooses and never checks it against `lease.max_usd` or `valid_lease`.
- **Action:** one sentence for the D2 handoff. D2 must reserve exactly the route-owned `lease.max_usd`, rounded up as router.md requires, from a Lease that passes `valid_lease`. A caller-chosen smaller maximum would under-reserve against the gate's real bound.

**N2. The new test settles the reservation maximum, not the gate's held amount.**
- **Where:** the new test's unknown-receipt branch.
- **What happens:** it settles at the reservation maximum ($50), while `cap_used.held_usd` is $19.041792. That behaviour is correct and conservative.
- **Action:** a one-line comment or doc note that D intentionally ignores `cap_used` would stop a future reader from "fixing" settlement to use the held amount.

---

## Prior findings

**Design reviews 2–4:**
- The fixes are present in the frozen source. That source is byte-identical to `d6e1f80`, which diff-2 passed.
- Design 2's B1 suggested keeping `max_usd` under $50. The author chose exactly $50, as the brief's finance parameters allow, but the effect on the D commitment was never revisited. See M1.

**Diff 1:**
- M1 (only active allowances causing a cap stop) stays fixed. `Allowance.reserve` is unchanged from `d6e1f80`.
- N2–N8 stay fixed. N1 stays documented.

**Diff 2:** its three optional nits (the orphaned queued request, the wording, deadline ordering) are unchanged and acceptable. The author's documentation of N1 stands.

**Rejected findings:** none. M1 here may be rejected only through arbitration by a different model family.

## Still needed before merge

1. Resolve M1, which is documentation only.
2. A green `uv run --with numpy --with scipy python -B tests/run.py` on the final SHA, with its terminal metadata saved. If M1 changes only docs, a fresh check that `git diff 0a91d8a <new> -- factory tests bin tools` is empty is enough to show the code is unchanged.
3. No source change after this freeze without another fresh review.

Nothing was edited, run, merged or pushed.

## Author response

Accepted M1. Documented the exact $50 commitment and ordinary-threshold consequences in router.md, interfaces §7 and validation: after one positively charged invocation a $50 owner cannot reserve another $50; a priced writer triggers ordinary diagnosis; two nested concurrent owners need $100 plus settled charges. First-call success is not availability qualification. Founder/D/B must agree sufficient job authority/revisions or a separately reviewed lower route profile against the receipt fit table before D2 enablement. A changes no cap, authority or policy here.

Accepted N1/N2 as documentation: D2 must reserve the exact verified route-owned lease.max_usd rounded upward to its nine-place unit; a caller-chosen smaller argument is forbidden. D ignores cap_used for settlement; unknown usage reserves maximum minus already-booked events, not held W. No code/test/source changes. The required full run continues on frozen 0a91d8a; source equivalence will be recorded and a fresh review checks these documentation fixes. No finding is rejected.
