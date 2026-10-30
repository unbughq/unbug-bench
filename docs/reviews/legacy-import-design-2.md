# Legacy import record: design review 2

**Reviewer:** fresh goldfish (read-only), Mode REVIEW
**Personas:** `zoom_out`, `design_critic`, `implementation_readiness`
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`

**Scope:** `docs/designs/interfaces.md` §8 "Legacy import record (proposed)" at `9cb25e6`, read as the cumulative change `f7ff54a..9cb25e6`. The separate `release_uninvoked` idempotency fix and `stream-d-diff-11.md` are not reviewed here.

**Checked against:**
- `docs/reviews/legacy-import-design-1.md`, including the elephant resolution
- `docs/designs/stream-d.md` lines 418–436 and 628–649
- `factory/carry_over.py`: `usage_facts`, `v0_to_v1` and the field classes `FACTS`, `DERIVED`, `VOLATILE`
- `factory/budget.py`: `_spending`, `_event_components`, `usage_coverage`
- `factory/restore_ledger.py`: `authenticate`
- Real fixtures: `canary6-collected-card.json`, `c7d405-collected-card.json`, `canary6-confirm-timeout-card.json`, `c7d405-confirm-timeout-card.json`, `canary6-last-legacy-card.json`, `infrastructure-kills.json`

**Prior reviews:** `legacy-import-design-1.md` (FAIL: 1 blocker, 4 major, 3 nits; all accepted). **Rejected findings:** none.

## Verdict: PASS (0 blockers, 0 majors, 5 nits)

The blocker and all four majors from round 1 are resolved, and none of the fixes grants authority too early. The nits below are wording and readiness fixes. They should go into the implementation commit, but none of them blocks this design.

## Real-card check (read-only, in memory)

I applied the proposed migration in memory to the real `continuation_budget` ledgers. It used the exact event JSON, raised the top-level `list_cost_usd` by $33 × N, and moved the covered markers into `resolved_unpriced_invocations`. Nothing was written to disk.

| Card | Known total | Anonymous top-level markers | After migration: `usage_facts` | After migration: `case_spending.total_spent_usd` |
|---|---|---|---|---|
| canary6 | 27.072383602 | 1 (`{"role":"writer","model":"claude/claude-opus-5-5"}`) | passes | **60.072383602** (matches the doc example) |
| c7d405 | 38.94274723 | 1 (same marker) | passes | **71.94274723** |

The c7d405 legacy remainder (unattributed spend, `legacy_unattributed` $29.275657097) is preserved. That works because the aggregate total and the events both rise by $33.

The cards that carry the resolved nested marker have no top-level markers and an unpriced count of 0. Those are `canary6-confirm-timeout-card.json` and `canary6-last-legacy-card.json` (known totals $43.091763729 and $43.166938577) and `c7d405-confirm-timeout-card.json` (known total $59.241735101). So the rule "the unpriced count must equal the top-level marker count" holds, and the nested marker is not counted again.

## Round-1 resolutions

- **B1 (resolved):**
  - Each top-level anonymous marker in the authenticated original ledger counts as exactly one unresolved invocation, even when two markers are byte-identical.
  - The invocation ID is derived as `sha256(canonical {import_id, marker_index, marker})` and appears only in the migration output, so the original ledger bytes stay unchanged.
  - Markers nested in `infrastructure_waste[].derivation` are excluded.
  - Unpriceable events are handled: the raw unpriced count must equal the marker count, or the case is refused.
  - Tests use the real canary6 and c7d405 cards. The replay above confirms both totals.
- **M1 (resolved):**
  - The initial format is shrunk to spend accounting plus retirement, with `lifetime_history` always null.
  - A future resumable format needs real history evidence and a separate review.
  - The dry-run consumes no headroom.
  - Historical spend counts against a batch only when the founder explicitly includes the case, and B may omit it.
  - There is no unused history schema, no worker recomputation of history, and no launch branch.
- **M2 (resolved):** The design now pins:
  - the exact event JSON, with `list_cost_usd` 33 and explicit `calls: 0`;
  - the top-level aggregate raise, falling back to the event sum when the total is absent;
  - calls preserved;
  - output that must pass `usage_facts`;
  - an exact nine-place match against `estimated_total_usd`, refusing rather than adjusting known charges.

  The replay confirms this.
- **M3 (resolved):** B allows one accepted import per case per batch. The worker and migration refuse any source that already has a `legacy-import:` event, an import resolution marker or a `legacy_import` card marker. Tests cover two generations of one case and a repeated pure replay.
- **M4 (resolved):**
  - The canonical ledger is `continuation_budget` on the public card. It must equal `work/scorecard.json`'s copy and, when present, `work/continuation-budget.json`.
  - `case_budget` is checked by recomputing it, never by byte equality, and it grants no authority.
- **N1 (resolved):** Late reconciliation for anonymous markers is explicitly not implemented. It needs a separately reviewed attribution format, and D's late-replacement requirement is recorded as still open.
- **N2 (resolved):** There is no diagnosis and no replacement. B's adoption must explicitly accept or change the retirement-only routing.
- **N3 (resolved):** The example uses the real canary6 amounts.

## Authority and consistency check

- **RAM config and `job_config.install`:**
  - The frozen nine-field RAM config is unchanged.
  - `job_config.install` still refuses legacy checkpoints that have no job money.
  - Both helpers stay unwired until B adopts and reviews the manifest and holder integration.
- **Founder authorization:**
  - `founder_authorized_total_usd` is null in the dry-run.
  - B must authenticate the founder's approval of the exact numbers; filling in the field is not proof.
  - No helper allocates commitment or writes job money.
- **Separation from job money:** The record must not already appear as job money or be inferred from a public-card limit.
- **Unknown history:** Unknown history stays null, never zero.
- **Comparison with stream-d:**
  - Known total plus $33 per marker, the dry-run visibility of $33 × 10 = $330, and refusing a case only when the count is missing all agree with `stream-d.md:421–431`.
  - Retiring when extension history is unproven agrees with `stream-d.md:632`.
  - The one deviation, late replacement of estimates, is declared as outstanding. It is not quietly claimed.
- **Murphy register:** No row closes on authored records. That is correct.

## Nits

### N1: the migrated card's new field and stale `case_budget` are left to the implementer

**Where:** lines 885–894: "Store a content-free `legacy_import` card marker…" and "Migration returns a new card".

**Problem 1: the new field is unclassified.** `carry_over.v0_to_v1` refuses any card field that is not in `FACTS`, `DERIVED` or `VOLATILE` (`carry_over.py:115`), and `legacy_import` is in none of them. Any later reader of a migrated card that goes through that path will refuse it with "unclassified scorecard fields".

**Problem 2: `case_budget` goes stale.** The design does not say whether the output card's derived `case_budget` is recomputed. If it is not, the migrated card would still show `spent_usd: null` and `unpriced_events: 1`, while its `continuation_budget` values the case at $60.07.

**Fix:** state both decisions.
- Add `legacy_import` to `FACTS`. Alternatively, state that migrated cards are never read through the carry-over path.
- Recompute the output `case_budget` from the migrated ledger with `case_spending`. Alternatively, drop it explicitly.

### N2: the named nested-marker fixture contains no ledger

**Where:** lines 914–915: "real `infrastructure-kills.json` for resolved nested markers".

`infrastructure-kills.json` holds kill-derivation records keyed `873d7f` and `c7d405`. Its `derivation` is a prose string, and it has no `continuation_budget`. The real ledgers that do carry `infrastructure_waste[].derivation.unpriced_invocations` together with `resolved_unpriced_invocations` are these three cards:
- `canary6-confirm-timeout-card.json`
- `c7d405-confirm-timeout-card.json`
- `canary6-last-legacy-card.json`

Name those cards instead. Assert that each one yields zero unresolved invocations, that its known total stays unchanged, and that it gets `retired_import_history_unknown`.

### N3: the term "import resolution marker" needs an exact test

**Where:** lines 896–899.

Real cards already carry `resolved_unpriced_invocations` entries that come from waste, for example `{infrastructure_waste_id, original}` on the confirm-timeout cards. The refusal must not catch those entries. Define the refusal by key: an entry with an `import_id` key is an import resolution marker. An entry with `infrastructure_waste_id` is allowed.

### N4: small output-shape gaps

- **Missing status:** for the known-usage branch, state `status: retired` explicitly. Today the text sets `status` only for the unknown-usage branch.
- **Number type:** state that the raised top-level `list_cost_usd` stays a JSON number, not the record's nine-place string. `usage_facts` rejects strings.

### N5: reuse `restore_ledger.authenticate` for the ledger-equality checks

**Where:** lines 851–862.

`restore_ledger.authenticate` already does the following:
- binds `public_card.sha256` to the generation;
- checks case identity on the archived `work/scorecard.json`;
- checks embedded-versus-retained ledger equality, with a fallback when `continuation-budget.json` is absent.

The validator should call it, or explicitly say it builds on it, rather than implement a second equality path. That follows ENGINEERING's "one path" and "delete before adding" rules.

## Standard checklist

**Heilmeier:**
- Objective, current state, new approach, risks and exams are present.
- Cost (the $33 × N visibility) and the exams on real cards are now concrete.
- Timeline is not stated. That is acceptable for an additive, unwired interface section.

**Implementation readiness:**
- Target files are named: `carry_over.py` for the pure dry-run and migration, `restore_ledger.py` for the worker validator, plus tests.
- Record schema, event JSON, aggregate rule, source paths, refusal set and terminal stops are all specified.
- The remaining choices are the small ones in N1 and N4.
- The phases are stable: the code is unwired, and B owns adoption, which gets its own later review.

**Murphy:** no row closes. That is correct.

**Pass condition met:** there are no open blockers. Folding N1–N5 into the implementation commit is recommended, so the zero-decision rule holds and the real-artifact exams use cards that actually hold ledgers.

---

I worked read-only, so the review file is not saved. The text above is the full content for `docs/reviews/legacy-import-design-2.md`.

## Elephant resolution

PASS accepted; all N1–N5 will be included in implementation: classify legacy_import, recompute case_budget, use actual resolved-marker cards, refuse import_id resolution markers only, keep numeric ledger totals and retired status, and share the existing restore-authentication path. No finding rejected. No Murphy row closed.
