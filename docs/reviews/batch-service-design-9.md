**FAIL** for committed `35659f0`. Two blockers are still open. Both are small text fixes.

Note on the worktree: it is not clean. There is an uncommitted edit to `docs/designs/batch-service.md` (+7/−2), and two untracked files, `docs/reviews/batch-service-design-8.md` and `docs/reviews/interfaces-design-16.md`. That edit appears to fix both blockers below. I reviewed the commit as briefed, not the working tree. The edit must be committed and get a fresh review. I disagree with the PASS in the untracked review-8 draft on B2.

---

# Goldfish design review: batch-service Increment2b.1 (6abe169..35659f0)

Mode: REVIEW. Personas used: zoom_out, design_critic, implementation_readiness. Standards used: heilmeier-standard.md and implementation-readiness-standard.md.

## Verdict: FAIL (2 blockers)

### Blockers

**B-1 (B2 not resolved). Blocker.** `batch-service.md:884-887`, `:916-917`, `:924-926`.
- **The schema has no slot for the facts.** The text says "Persist D's returned facts" and "Stored facts win on replay". But each entry has only `projection:null`. Nothing stores `exhaustion` or `actual_model_work`.
- **An unplanned entry looks the same as a planned one.** `None` is a legitimate answer from `pending_projection`. It is stored as `null`, which is also what an unplanned entry holds. So a replay of a planned entry with `None` projection looks unplanned and calls D again.
- **The design's own test would fail.** "replay without re-calling a changed draft module" (`:954-955`) fails for every absent-projection entry, which is the common case. The implementer would have to invent a schema.
- **Fix:** add a `facts` field: `null` (unplanned), or `{exhaustion: bool, actual_model_work: bool, pending_projection: None | projection}`. The uncommitted edit does exactly this.

**B-2 (B1 fix contradicts itself). Blocker.** `batch-service.md:918-923`.
- "Queue an ordinary same-owner resume **iff** pending_projection is present" conflicts with the next sentences. They say an exhausted unknown-total parent "always gets the same-owner settlement resume, even when pending_projection is None".
- An "iff" leaves no room for an exception. The implementer must pick which sentence wins on exactly the deadlock path B1 was meant to fix. That breaks the zero-decision rule.
- **Fix:** "when pending_projection is present or the exhausted total is unknown (below)". The uncommitted edit says this.

### Majors (not blocking)

**M-1. No stop rule for a total that is never known.** `:921-923`, `:935-937`.
- When a model has no price, `budget.py:419` writes `total_spent_usd: None`. This path is reached via `model_runtime.py:182`. No later settlement fills that total in.
- An exhausted case on an unpriced model therefore gets a settlement resume at every generation. The dedup key `resume/<case>/<generation>` is new each time. Only the deadline ends the loop.
- The money bound cannot price this spend, so it does not limit it. All 53 saved scorecards in `sealed/` have no `case_budget`, so every legacy card takes this path too.
- No dispatch exists in this increment, so this does not block. But the design should say now what ends the loop. Options: a second unknown-total settlement at a later generation refuses; or a future admission rule refuses unknown-total resumes for unpriced models. Do not leave it to the future dispatcher.

**M-2. "When present" in the ciphertext check is ambiguous.** `:870-871`.
- "check statement_cipher_sha256 and public_search.cipher_sha256 against statement.age and search.age when present" can mean the digest field is present, or the file is present.
- It does not say what happens when the card carries a digest but the `.age` file is missing. Is that a missing-member refusal, or an unchecked copy?
- **Fix:** a digest on the card requires the file, and the bytes must match. A file with no digest is copied as an unreferenced companion.
- No saved card has either digest field (0 of 53). The "digest present" test must therefore use a clearly labelled authored card. Say so.

### Nits

- **N-1.** `:921`: say whether a card with no `case_budget` key at all counts as "absent". All saved cards are in that state. Reading it as unknown is right, but write it down.
- **N-2.** `:872-873`: "the alternative archive not bound by this card". When the card has no `archive` field, `collection.verify` allows both names and binds whichever digest matches (`collection.py:28-43`). Say that this digest-matched archive is the bound one.
- **N-3.** The text refuses contradictory `replacement_eligible:true` (`:924-925`) and has injectable `now` (`:945-946`). But the Tests paragraph in HEAD names neither test. The uncommitted edit adds them.

## Prior review 7 findings

| Item | Status in 35659f0 |
|---|---|
| B1: unknown-total deadlock | Rule added, but contradicts the "iff" sentence (B-2) |
| B2: replay without re-calling D | **Open.** No facts schema; `None` projection looks unplanned (B-1) |
| M1: total field | Fixed. Only `case_budget.total_spent_usd` is read; missing means unknown. Matches `budget.py:419` and `model_runtime.py:171` |
| M2: ciphertext fields | Fixed. `statement_cipher_sha256` and `public_search.cipher_sha256` match `run_artifacts.py:87,95`; plaintext `statement_sha256` (`:83`) is excluded. "When present" is still ambiguous (M-2) |
| Nit: verify returns exactly {case} | Fixed (`collection.py:44-47` returns the set; probe/startup cards return empty and refuse) |
| Nit: archive siblings | Fixed (unbound archive excluded; see N-2) |
| Nit: two journal shapes | Fixed (`:890-891` supersedes the earlier shape) |
| Nit: resolver grammar on every call | Fixed (`:895`) |
| Nit: contradictory predicates | Refused in text; test not named (N-3) |
| Nit: injectable now | Fixed. Matches `batch_money.authorize` `now=None` (`batch_money.py:112,119`) |

## Other checks, no finding

- **Reuse:** the design reuses existing helpers instead of adding new ones. These exist: `batch_money.manifest` and `batch_money.locked` (`:57`, `:103`), `collection.verify`, `transfer.digest` (`:21`), `registry.atomic_json` (`:18`), `launch_manifest.collection_files` and `TRUSTED_FILES` (`:147`, `:12`). The worker-file test list is at `tests/tools/test_launch_manifest.py:77-86`.
- **D gate:** D stays off behind a tracked False constant and is imported lazily. `factory/diagnosis*` does not exist yet. The design states this as an enablement blocker, not a passing claim. That is correct.
- **Interfaces addendum** (`interfaces.md:440-457`): it is consistent with the batch-service text. It keeps the eligibility list owned by D and adds no environment toggle.
- **Scope:** no money transitions, no launch, no VM change. No Murphy rows are claimed closed. Cumulative calls are telemetry only, with no admission rule. This matches the pending 2026-10-30 ruling.
- **Heilmeier:** objective, scope, risks, tests and next work are stated. Cost and timeline are implied by increment scope. That is acceptable for an addendum.

## Files checked

- In the reviewed worktree:
  - `docs/ENGINEERING.md`
  - `tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md`
  - `tools/egm/document_standards/{heilmeier-standard,implementation-readiness-standard}.md`
  - `docs/reviews/batch-service-design-7.md`
  - `docs/designs/batch-service.md:849-971` at 35659f0
  - `docs/designs/interfaces.md:437-460`
  - `factory/collection.py`
  - `factory/run_artifacts.py:58-100`
  - `factory/batch_money.py:19-125`
  - `factory/budget.py:161,274-316,410-425`
  - `factory/model_runtime.py:171,182`
  - `factory/launch_manifest.py:12,45,107-148`
  - `factory/transfer.py:21`
  - `factory/registry.py:18`
  - `tests/tools/test_launch_manifest.py:73-89`
  - `sealed/*.scorecard.json` (53 cards: budget and digest fields), `.gitignore:7`
- Also read: `/Users/bugsincode/.codex/RTK.md`.
- Uncommitted working-tree diff: read only to report drift, not reviewed.

No files edited. No money spent. VM not touched.

---

## Elephant resolution

Both blockers accepted. Compared every uncommitted hunk against 35659f0: keep
all three predecessor edits, because the facts sentinel resolves B-1, the
when/or wording resolves B-2, and the named tests resolve N-3. Preserve the
predecessor's design-8 and interfaces-design-16 verbatim; their PASS was not
accepted as resolution of this review's blockers. No changes were discarded.

M-1: no unknown-total launch is enabled by this core. The existing interfaces §8
coverage rule refuses unknown legacy/unpriced usage without admitted maxima;
make that future admission obligation explicit here, without adding a retry cap.
M-2/N-1/N-2: digest references require companion bytes; absent case_budget means
unknown; without archive the unique digest-matching archive is bound. Tests
label authored operational card fields. No rejected findings, VM changes,
spend, enablement or Murphy closures. Fresh committed-design re-review follows.

