# G2: a founder ruling for a source that blocks every fetch (2026-11-20)

Founder decision, 2026-11-20 morning: give G2 (freshness) a path for a flagged source URL that blocks
every fetch and has no readable archive copy. This is an explicit founder exception to ENGINEERING.md
section 4 ("no one-off rulings"): the rulings are per case and per URL by the founder's choice.

This note is kept out of the top-level `*.md` files on purpose, because those files are G8/G9 gate
identity (`factory/gate_state.py` `DEPENDENCIES`).

## Problem

G2 asks an independent reviewer about every flagged search row. Some rows can never be cleared: the live
page answers with an access failure and there is no archive copy. Access failures are `http_202` (a WAF
challenge), `401/403/451`, `429`, `5xx` or a network error.

- `run.checked_freshness_verdict` keeps any unresolved answer. The reviewer prompt says an access failure
  with no snapshot stays unresolved.
- An archived copy can confirm a match, but it never clears one while live access fails.
- `ordinary_freshness.stalled` then stops the attempt: `freshness_source_blocked` after 3 walled cycles,
  or `freshness_refresh_stalled` after 30 minutes of 429/5xx.
- Diagnosis calls that stop a factory bug, and the case is held for a release. A resume loops on the
  same wall.
- No person can feed what the page says into G2, and no ruling can say the page does not matter.

Three cases are held on this today. All three are `held_for_release` with `diagnoses: 1`. I read the
snapshot facts in memory from the VM.

| case | batch, plumbing (source) | row | runner receipt | reviewer answer (retained) | gates on card |
|---|---|---|---|---|---|
| `case-import-cae763-h5-1` | b-import-cae763-h5, cd0418e7 (a6b7c6d4) | flagged 277 of 361, builder/web ambiguous, Square Community thread | `http_202`, no Wayback copy | `resolved:false, retrieved_from:none` | G1, G3 pass |
| `case-import-18681d-h5-1` | b-import-18681d-h5, 00ff2156 (3dfdde3c) | flagged 4 of 5, builder/web ambiguous, answeroverflow thread | `http_429` (Vercel challenge), no Wayback copy | `resolved:false, retrieved_from:none` | G1 pass, G3 invalid-infra |
| `case-import-2a7b2a-h1-1` | b-import-2a7b2a-h1, d3cab739 (8504a571) | flagged 16 of 16, builder/web ambiguous, Shopline help article | `http_403`; the 2025-07-17 Wayback copy is found only on some cycles | `resolved:false, retrieved_from:archive` | G1, G3, G4 pass |

None of the three has G2 recorded as passed on its current attempt: no card's `gates` map contains `G2`.

The founder's rulings:
- **cae763 and 2a7b2a: not needed.** A Square or Shopline page cannot be a public report of a Medusa bug.
- **18681d: hand checked.** A person opens the page. The factory takes that check as the source's
  content: what the page says, and whether it publicly reports this case's bug.

## Change

### 1. The rulings: `run.G2_SOURCE_RULINGS`

The rulings are a tuple constant in `factory/run.py`, next to `SOURCE_CODE_NOT_PUBLIC`. That is where the
2026-11-19 G2 source-code ruling lives (aa7a1bf9). Each entry is one founder ruling for one URL of one
case, a dict with exactly these keys:

| key | value | used for |
|---|---|---|
| `gate` | `"G2"` | validity |
| `kind` | `"not_needed"` or `"hand_checked"` | the effect |
| `by` | `"founder"` | validity |
| `at` | the ruling date, `YYYY-MM-DD` | validity |
| `case` | the case id ruled on | the record only |
| `statement_sha256` | sha256 of the case's `case/statement.md` | **match** |
| `url` | the flagged row's URL, exactly | **match** |
| `ruling` | the founder's words, non-empty | the record |
| `hand_check` | `hand_checked` only: `{checked_at: YYYY-MM-DD, checked_by: non-empty, page_says: non-empty, reports_this_bug: bool}` | the effect |

- **Valid** means: exactly these keys, with `hand_check` present only for `hand_checked`, and every value
  as in the table.
- **Matched** means the statement digest and the URL are equal. The digest makes the ruling per-case.
  It survives a resume, or a relaunch of the same statement, and it stops matching when the statement
  changes.
- It is a constant rather than a data file for two reasons. First, `gate_state.runner_inputs('G2')`
  hashes it automatically, so every ruling is part of G2's identity and nothing else's. Second, it ships
  in every plumbing release under `WORKER_GLOBS` (`factory/*.py`) with no manifest change and no
  missing-file case.
- The cost: adding a ruling changes G2 identity for every batch that receives that release. That costs
  nothing extra. G2 already reruns on every GATES attempt (`ensure_freshness`), and any plumbing release
  already re-asks retained model answers.

### 2. G2 applies a ruling in `run.checked_freshness_verdict`

This is the one place that decides every G2 verdict: a fresh one, a retained one, and the stress-round
`loop_freshness` one.

For each flagged row, `g2_source_ruling(c, row, answer, receipt)` returns the ruling only if all of these
hold:
- the review completed;
- the runner's own receipt for the row shows an access failure (`freshness_retrieval.access_failure`);
- the reviewer's answer does not say `same_bug: true`, whether that answer is valid or not;
- exactly one valid entry matches.

The ruling then decides the row:
- `not_needed`, or `hand_checked` with `reports_this_bug: false`: the row is cleared.
- `hand_checked` with `reports_this_bug: true`: the row is a confirmed public match, as if the reviewer
  had confirmed it, so G2 fails as `public_match`.
- Either way, a ruled row never sets `freshness_transport_pending`, so G2 does not wait on it again.

What a ruling does not override:
- A page that becomes readable live goes back to the reviewer, because the ruling needs the receipt's
  access failure.
- A dead page (404/410/DNS) keeps its existing unreachable rule.
- A reviewer's `same_bug: true` always stands.
- Malformed, duplicate or unmatched entries apply nothing. That fails closed: the row stays blocked, as
  it does today.
- Several flagged rows with the same URL are the same page, so a ruling settles them all. In practice
  each held case has one.

### 3. The card

- The review summary gets `ruled_rows`: the flagged row number plus the whole ruling entry. It appears
  only when a ruling applied, so a case with no ruling produces byte-identical G2 info.
- It lands in `card.freshness_confirmation`, which keeps only the current verdict's rulings, and in G2's
  info (`admission_freshness` / `gate_results.G2`), beside `unreachable_rows`.
- The repo and the card are not contestant-visible. The contestant box copies only
  `factory/case_permissions.py` (`harbor/*/Dockerfile`), and the card is published only through the
  allowlist.

### 4. Supporting change: `ordinary_freshness.keep_mixed_receipt`

`keep_mixed_receipt` judges one row at a time through a namespace. That namespace now carries `case`, so
a `hand_checked: true` row counts in `confirmed_rows`. `tools/open-g2-verdicts.py` already passes `case`.

Nothing else about G2 changes: the reviewer prompt, the retrieval, the confirmation contract, the stall
stops, the minima and the searches all stay as they are.

### Why not the existing sealed FOUNDER_RULING artifact

The founder-ruling mechanism today is `unbug prepare <case> ruling` plus `founder_reply continue`
(`rulings/22e434-h2-g8-continue.json`, on the VM). It cannot carry this ruling without engine and
contract changes:

- **It cannot reach these cases.**
  - A FOUNDER_RULING reaches a step only after an escalation (`Engine.escalate`), and only a STRESS or
    GATES step (`contract.py`: "a ruling goes only to stress or gates").
  - These cases are `held_for_release`, and `resume_held` carries no ruling.
  - An admit-time G2 (a non-hand case) could never take one.
- **It would redo passed work.** A ruling on a GATES step rescopes every engine checkpoint
  (`durable/checkpoints.directory`), every `gate_call` binding and every retained model answer
  (`run.retained_answer`).
- **G8/G9 would read it.** `run.review` adds `engine_review_ruling(c)` with no gate argument to the G8/G9
  panel prompt. Fixing that changes G8/G9 identity, which the held cases forbid.

So the ruling keeps the G8 rulings' fields and takes the G2 source-code rule's path: a founder ruling
written into G2's code, reviewed, and merged by the founder. The founder's merge and the content-addressed
plumbing release digest seal it.

### Identity

`G2_SOURCE_RULINGS`, `g2_source_ruling` and `checked_freshness_verdict` are reachable only from G2's
runner root. So only `gate_state.runner_inputs('G2')` changes. No other gate's identity changes, and
neither do the judge, model science or the delivery contract. The PR lists the `myident.py` proof, and
the committed test `test_only_g2_identity_reads_the_rulings` checks it.

Retained G2 data cannot skip a ruling:
- `public-search.json` is reused only when no row is flagged.
- `freshness-verdict.json` holds reviewer answers only, and the ruling is applied again on every read.

## What it deletes

Nothing in code. Operationally, it ends the hold-and-resume loop for a permanently walled row: three held
batches today. It also replaces the per-case `disclosure.md` workaround used for 5813be, which was a
case-file edit that changes every gate's identity.

## Cost and risk of the resume

- **Reviewer re-ask.** A plumbing release changes `source_binding`, so the G2 reviewer is asked again on
  every flagged row: 361 for cae763, 16 for 2a7b2a, 5 for 18681d. Retained answers are bound to the
  plumbing version. cae763's whole G2 review cost about $0.5 last time.
- **A different row can go unresolved.** A fresh answer can leave some other row unresolved. That row is
  re-asked up to `REVIEW_REASKS` = 2 times and can still end `freshness_review_unavailable`. The ruling
  does not help there: that is today's rule.
- **What a release reruns.** The resumed GATES attempt reruns G1, G2 and G3. It keeps the `gate_state`
  caches (cae763 G4/G5, 2a7b2a G4), because their identities do not change (see the PR's identity
  lists per batch source).
- **The release is the resume.** `wait_for_fix` ends a hold as soon as the batch's plumbing changes
  (`engine.py` `wait_for_fix`). Every release to a held batch therefore resumes it, and uses one of the
  lineage's 3 factory-bug resumes. Each card shows `diagnoses: 1`.
- **Timeline.** About an hour per case to get back to G2, for G1, G3 and the re-asked review.

## Tests

`tests/factory/test_g2_blocked_source.py` uses real shapes: the flagged row, the current runner receipt
and the retained reviewer answer of each held case, read in memory from its snapshot into
`tests/factory/fixtures/g2-blocked-source.json`.

- **No ruling.** Each held row stays blocked, with transport pending, and the summary has no new key
  (today's behaviour).
- **Shipped rulings.** The `not_needed` rulings clear cae763's and 2a7b2a's rows and appear in
  `ruled_rows` on the card. They match the real statement digests and URLs.
- **Hand check on 18681d.** `reports_this_bug: false` clears the row. `true` confirms a public match.
- **Scope.** Each of these settles nothing:
  - another statement or another URL;
  - a duplicate entry, a bad `kind`, an unknown key, or empty `page_says`;
  - a reviewer `same_bug: true` with an access-failed receipt;
  - a page read live;
  - a dead page.

  A valid live `same_bug: true` still counts as a match. Another row in the same verdict is judged as
  before.
- **Identity.** Only G2's runner inputs contain the new names. G1–G17 and the calibrate/stress roots
  are checked.
- **End to end.** `run.g2` under the engine harness of `test_stream_d_retries.RetryTests.bot_wall`, with
  cae763's real URL behind an authored 202 wall. With the ruling, G2 passes on its first cycle with
  `ruled_rows` on the card. The existing test shows that without a ruling it stops
  `freshness_source_blocked`.
- **Operator pre-release check.** This one is outside the repo because it needs the VM. It runs the
  candidate `run.py`'s `g2_source_ruling` read-only, in memory, against each held case's latest snapshot:
  its real statement, flagged rows, receipt and retained answer. It must print `OK` for each ruled case
  before a release.

The existing G2 suites (`test_stream_d_retries`, `test_freshness_archive`, `test_freshness_restore_fixes`,
`test_admission`) pass unchanged.

## Murphy rows

The local register, `docs/murphy-register.md` in the main checkout, is untracked by design (AGENTS.md).

- **`new-g2-blocked-source-1` (new).** A flagged G2 source that blocks every fetch has no path to clear.
  The case holds for a release and every resume loops (cae763-h5, 18681d-h5, 2a7b2a-h1, 20 Nov). The
  sources seen are a bot wall, a 429/202 challenge, and a 403 whose archive copy is found only sometimes.
  Closed by `tests/factory/test_g2_blocked_source.py`.
- **`new-walled-flagged-row-1` (already closed).** Its open half, "a person reads it", now has a path:
  the `hand_checked` ruling.

## Operator steps (after the founder merges; the operator deploys)

1. Run the pre-release check against the merge commit's `run.py` for all three cases. Expected output:
   cae763 OK, 2a7b2a OK, and 18681d "NO RULING" until its hand check is in.
2. Build and install the plumbing from the merge commit, for new launches only.
3. Send `plumbing_release` to `b-import-cae763-h5` and `b-import-2a7b2a-h1`. The release itself ends
   their holds; `resume_held` is needed only if a card still says `held_for_release` after a minute.
4. 18681d:
   1. The founder fills in the hand-check template.
   2. The entry is added to `G2_SOURCE_RULINGS`. This is a data-only commit, checked by a goldfish.
   3. Run step 1 for 18681d, which must print OK.
   4. Install, then send `plumbing_release` to `b-import-18681d-h5`.

   Never release anything to `b-import-18681d-h5` before its ruling is in. Any release resumes it, and
   it would loop on the 429 again.
