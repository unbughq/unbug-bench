# Legacy import record — design review 1

**Reviewer:** fresh goldfish (read-only), Mode REVIEW
**Personas:** `zoom_out`, `design_critic`, `implementation_readiness`
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`
**Scope:** `f7ff54a..7c7bc7e`, `docs/designs/interfaces.md` §8 "Legacy import record (proposed)" (lines 780–872). It is checked against the rest of §8, `docs/designs/stream-d.md` (the import and $33 text around lines 421–431, 606–609, 632–649 and 853–860), `factory/carry_over.py:usage_facts`, `factory/budget.py` (`case_spending`, `_event_components`, the `unpriced_invocations` producers) and the saved fixtures under `tests/factory/fixtures/`.
**Prior reviews of this proposal:** none. **Rejected findings:** none.

## Verdict: FAIL (1 blocker, 4 major, 3 nits)

The constraints are kept. The proposal does not change the frozen nine-field RAM config. It keeps `job_config.install` refusing legacy checkpoints. Both helpers stay unwired. The founder authorizes exact amounts, and the dry-run leaves that authorization null. No record grants a commitment, revision, extension, diagnosis, replacement or resume. Unknown history stays null and is never zero. The record digest, generation and ledger digests come from B's authenticated boundary, not from the restored card. Those parts are sound.

The blocker is that the core path, known spend plus $33 for each unknown invocation, cannot apply to any real legacy archive.

---

### B1 — Blocker: the $33 path needs invocation identities that no real legacy ledger has

**Where:** lines 815–821 ("An unresolved invocation must have a unique canonical UUID4 and an explicit `booked_event_ids` list in the retained ledger's `unpriced_invocations` marker … No count is inferred from … the number of anonymous markers") and line 871 ("authored identified unknown markers").

**Finding.** Every saved real ledger has only anonymous markers in `unpriced_invocations`:

- `canary6-collected-card.json`, `c7d405-collected-card.json` and `infrastructure-kills.json` (873d7f, c7d405) all hold `[{"role":"writer","model":"claude/claude-opus-5-5"}]`.
- There is no `invocation_id` and no `booked_event_ids`.
- The code agrees. `budget.py:1230` adds `invocation_id`/`lease_id` only when `factory` is true. `carry_over.usage_facts` adds a `legacy_unfinished` marker with no ID.

So under this proposal, every real legacy case with unknown usage is refused. canary6 has $27.07 known plus 1 unknown, and c7d405 has $38.94 known plus 1 unknown; both are refused. The $33 addition then only ever runs on authored test markers. That defeats `stream-d.md:421–431`, which requires known booked total plus $33 per unknown invocation, with the dry-run making $33×N visible before import.

The text also contradicts itself. Nobody can add UUIDs to a legacy marker without changing the bytes that `ledger_sha256` ("canonical original ledger") and archive equality bind to. The design does not say who assigns those IDs, or when.

**Required decision (pick one and state it):**

- **(a) Count anonymous markers.** Count each top-level anonymous `unpriced_invocations` marker in the authenticated original ledger as exactly one unresolved invocation. Derive a stable ID deterministically, for example `sha256(import_id, marker index, canonical marker)`, instead of requiring a UUID4. Leave `booked_event_ids` empty for legacy markers, or prove it some other way. Keep the refusal for markers inside `infrastructure_waste[].derivation`, since those are already resolved waste and must not be counted again. Also say how unpriceable events are handled: `case_spending` counts them as unpriced too (`budget.py:441–445`).
- **(b) Refuse all of them.** State plainly that every current legacy unknown-usage case is refused and handled only by retirement. Amend stream-d's $33×N / $330 text to match. Delete the estimate-event migration as dead machinery.

Then test the chosen rule against the real canary6 and c7d405 cards, not only authored markers. ENGINEERING §4 requires real artifacts.

### M1 — Major (zoom-out / YAGNI): no real legacy case can ever launch, so a large part of the machinery has nothing to do

**Where:** lines 829–842 and 860–861.

Unknown-usage imports always retire as `retired_import_estimate`. Cases with null `lifetime_history` retire as `retired_import_history_unknown`. The text also says no older archive has an authenticated `lifetime-history.json`; it is a "producer obligation for later checkpoint writers". So every legacy import retires, which leaves several parts with no real input:

- the `lifetime_history` schema;
- the worker's history recomputation;
- the factory-bug-resume history rules;
- the "can launch" branch.

`stream-d.md:632` allows "zero only with receipts proving none". Legacy archives come from before extensions existed, and a schema or version proof might qualify. The proposal forbids that without explaining why. The design should do one of two things:

- name the real archive class that can launch and how its history is proven; or
- shrink to dry-run plus spend-accounting plus retirement, and defer `lifetime_history` until a producer exists.

It should also say why spend from a case that never launches must count against the *new* batch bound (line 866). It consumes headroom without enabling any work.

### M2 — Major (readiness): the shape of the estimate event and its effect on ledger totals are not specified, and the result would fail the existing validator

**Where:** lines 852–856.

Real legacy ledgers carry top-level `cost`, `list_cost_usd`, `estimated_subscription_cost_usd` and `calls` totals. For example, canary6 has `cost` 0.0859 and `list_cost_usd` 26.98. `carry_over.usage_facts` refuses any ledger where `total + 1e-8 < sum(events)` for each priced key. It also defaults a missing event `calls` to 1. The proposal says to append a $33 event and to "preserve original events, rounds and waste", but it leaves these undecided:

- which component holds the $33: `cost`, `list_cost_usd` or `estimated_subscription_cost_usd`;
- whether the top-level totals are raised. If they are not, the migrated ledger fails `usage_facts`;
- the exact event keys: `id`, explicit `calls: 0`, `role`, `configured_model`, and an `estimated`/`kind` discriminator so it stays "distinguishable from observed model work";
- how `case_spending` / `_event_components` values it, so the batch total equals `estimated_total_usd` exactly.

Write out the exact event JSON and the total adjustments. Add a test that the migrated real ledger passes `usage_facts` and `case_spending`, and that the result equals `estimated_total_usd`.

### M3 — Major (design-critic): nothing guarantees one import per case, so estimates can stack across generations

**Where:** lines 795 and 857–858.

`import_id` hashes `{case, legacy_generation_sha256, ledger_sha256}`, and estimate event IDs embed `import_id`. Two records for the same case from different archived generations would have different `import_id`s. Event-ID deduplication would not catch them, so the same unknown invocations would be charged $33 twice. "A different import never stacks an estimate" only holds within one migrated ledger.

State the invariant: at most one accepted import record per case per batch, enforced by B at manifest adoption. Add the worker check: refuse a ledger that already has any `legacy-import:` event or a `resolved_unpriced_invocations` entry from another `import_id`. Add a test with two generations of one case.

### M4 — Major (readiness): it is unclear which ledgers the worker must compare

**Where:** lines 845–846 ("public and archived ledger equality (and a separate retained ledger when present)").

Real cards carry both `continuation_budget` (the raw ledger) and `case_budget` (a derived projection with `spent_usd: null`, `known_spent_usd`, `unpriced_events`). `case_budget.infrastructure_waste[].derivation` also embeds copies of `unpriced_invocations`. Name the exact fields and paths:

- which one is the canonical original ledger that `ledger_sha256` hashes;
- whether "public" means the card's `continuation_budget`;
- what "separate retained ledger" refers to;
- that `case_budget` is checked by recomputation, not by byte equality.

Without this, two implementers would build different validators.

### N1 — Nit: late-receipt reconciliation is deferred but stated as if it works

**Where:** lines 859–861.

Anonymous legacy invocations have no event or invocation ID that a late receipt could match against `legacy-import:<import_id>:<invocation_id>`. "Replace … by the existing event-ID deduplication rule" therefore cannot fire for real legacy data. Say this explicitly: late receipts for anonymous legacy invocations are not reconciled, and the estimate stands. The deferral note already blocks enablement, so this is a wording fix.

### N2 — Nit: the replacement and retirement routing for `retired_import_*` is left to B, but ENGINEERING §3 has a default

**Where:** lines 862–866.

§3 says a retired case gets a replacement. The proposal says a legacy record alone makes nothing replacement-eligible. State the intended default (no replacement until B adopts the routing) so B's later review has a baseline to accept or change.

### N3 — Nit: the example amounts

The JSON example (12 + 33 = 45) is fine. Consider using the real canary6 numbers instead ($27.072383602 known, rounded up once, plus $33), so the doc's example is a value the tests can reproduce from a saved card.

---

### Standard checklist

- **Heilmeier**
  - Objective, current state, approach, risks and tests are present.
  - Cost and timeline are missing; that is acceptable for an additive interface section under stream-d's estimate.
  - Success criteria (dry-run on real cards) are weakened by B1.
- **Implementation readiness**
  - The zero-decision rule fails on B1, M2 and M4.
  - The target files are implied by D ownership but not listed. Add them: likely `carry_over.py` or `restore_ledger.py` for the pure migration/dry-run, plus the worker validator module, plus tests.
- **Murphy**
  - It correctly closes no row.

**Pass condition for the next round:** B1 resolved with a stated rule and a real-card test, and M1–M4 addressed or rejected through the ENGINEERING §1 second-goldfish process.

## Elephant resolution

All findings accepted. Next revision uses authenticated top-level anonymous marker ordinals with deterministic IDs, exact estimate-event and aggregate adjustments, one-import-per-case ownership, explicit source ledger paths, and a spend-only retired initial format with lifetime_history null. No zero-history producer is invented. Late-receipt matching is deferred explicitly. Real canary6 and c7d405 replays will replace the authored-only primary evidence.
