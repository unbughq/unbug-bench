**PASS**

Neither blocker is still open. B1 and B2 are fixed. M1, M2 and every nit from review 7 are addressed in `35659f0`. One new Major and two nits are below; each can be fixed in a phrase before or alongside implementation.

### Prior findings: how each was resolved
- **B1 (fixed)**, `batch-service.md:921-923`. An exhausted parent whose `case_budget.total_spent_usd` is null or absent now always gets the same-owner settlement resume, even when `pending_projection` is None. Combined with `:935-936` (child marked `unknown_total`, resume gets settlement priority), every unknown-total child now has something queued that can unblock it. This matches interfaces §8 (`:370-375`).
- **B2 (fixed)**, `:924-927`. On replay, stored facts win: D is not called again and nothing is overwritten. Launch state stays `pending`. Facts, derivation and requests are written in one atomic journal replacement. This also fits `:930`, which requires the derivation to be persisted before requests: both land in the same write.
- **M1 (fixed)**, `:922-924`. `case_budget.total_spent_usd` is named as the only total field B reads, and missing means unknown, never zero.
- **M2 (fixed)**, `:870-872`. The design names `statement_cipher_sha256` and `public_search.cipher_sha256` against `statement.age`/`search.age`, and says `statement_sha256` is plaintext and is never compared to ciphertext. These names match `run_artifacts.py:83,87,95`.
- **Nits (fixed):**
  - The new schema supersedes the illustrative journal shape (`:890-891`).
  - `verify` must return exactly `{case}` (`:870`).
  - The unbound alternative archive is excluded (`:873-874`). This can be decided: when `card.archive` is absent, `collection.verify` binds the one archive whose digest matches.
  - The resolver applies to root jobs too (`:895-896`).
  - Contradictory eligibility refuses (`:920-921`).
  - `now=` is injectable, the same way `batch_money.authorize` (`batch_money.py:112`) does it (`:904`, `:943-944`).
- **Cumulative calls:** the brief's point that they are telemetry only, with no call-count admission rule, is now explicit (`:944-946`).

### New findings

**Major: there is no sentinel for "already planned"** (`:886-887` with `:915`, `:924-926`)
- An entry starts with `projection:null`, but `pending_projection` can legitimately return None.
- If the implementer stores D's answer directly in `projection`, a planned entry with an absent projection looks unplanned. Replay would then call D again, which breaks "stored facts win".
- The field that holds `exhaustion` and `actual_model_work` is also unnamed.
- Fix: pin one shape. For example, `facts: null | {exhaustion, actual_model_work, pending_projection}`, where null means not yet planned. Keep the verbatim projection inside it.
- I rated this Major rather than Blocker because the replay rule itself is clear; only the field shape is missing.

**Nit: "iff" now contradicts the B1 exception** (`:917-918`). "Queue an ordinary same-owner resume iff pending_projection is present" is followed by "always … even when pending_projection is None". Change "iff" to "when", or fold the unknown-total case into that sentence.

**Nit: two refusals have no named test** (`:950-956`). Contradictory eligibility (`replacement_eligible:true` with a predicate false) is not in the test list, and neither is the refusal of a deadline-expired plan using an injected `now`. Add both by name.

### Checks on the brief's constraints
- **D's draft is not imported or enabled in production.** The draft D API in interfaces §8 (`:440-457`) matches the brief's signatures, purity, no generation self-reference, and denied-reservation-is-false. The gate is a tracked `False` constant with no environment toggle and nothing imported in production. D's API is relayed by the parent and "not activation authority".
- **This increment is not claimed as a working scheduler.**
  - There is no money ACK, current pointer, grant, launch or dispatch API (`:937-939`).
  - Holder, bind, money and installer restrictions stay unchanged until the full 2b/3 addendum (`:898-902`).
  - Nothing is deleted from live controllers.
  - No Murphy rows are claimed closed.
- **Reused code exists as cited:** `collection.verify`, `batch_money.manifest`/`locked`/`authorize(now=)`, `registry.atomic_json`, `transfer.digest` and `launch_manifest.collection_files`. The only new code is the pure resolver and the queue core. No new architecture is added.

I only read files and ran read-only git and grep. I made no edits and ran no crypto, cloud or models. The writer should save this verbatim to `docs/reviews/batch-service-design-8.md` and `docs/reviews/interfaces-design-16.md`.

---

Elephant response: PASS accepted. Pin facts:null|{exhaustion,actual_model_work,pending_projection}; null alone means unplanned, so a None projection still replays stored facts. Fixed iff wording and named contradictory-eligibility/deadline tests. No rejected findings, enablement, spend or Murphy closures.

