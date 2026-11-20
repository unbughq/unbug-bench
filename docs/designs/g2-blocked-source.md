# G2: a founder ruling for a source that blocks every fetch (2026-11-20)

Founder decision, 2026-11-20 morning: give G2 (freshness) a path for a flagged source URL that blocks
every fetch and has no readable archive copy. This is an explicit founder exception to `docs/ENGINEERING.md`
section 4 ("no one-off rulings"): the rulings are per case and per URL by the founder's choice.

**Amendment, 2026-11-20 ~17:00 UTC (founder: "Yes, do it", for 5813be):** a `hand_checked` ruling may also
settle a flagged row whose live fetch returned a page (for example HTTP 200) that the reviewer left
unresolved (`resolved: false`), such as a JavaScript "Loading" shell it could not read. The code cannot tell
why a reviewer left a page unresolved; the person who hand checked that URL is the safeguard. It never settles a row the reviewer
confirmed (`same_bug: true`). See section 2 and the amendment section below.

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
`loop_freshness` one. The founder's ruling is about the page, so it holds wherever G2's freshness rule
judges that URL, the stress round included.

For each flagged row, `g2_source_ruling(c, row, answer, receipt)` returns the ruling only if all of these
hold:
- the review completed;
- the row is unread, in one of two ways:
  - the runner's own receipt for the row shows an access failure (`freshness_retrieval.access_failure`);
    any `kind` applies; or
  - (amendment, `hand_checked` only) the receipt shows a page fetched live (`retrieved_from: live`)
    and the reviewer's answer for that row is a dict with `resolved: false`, `same_bug` null or false,
    the row's URL, and retrieval fields that agree with the receipt (`freshness_retrieval.agrees`). An
    archive copy of a dead page does not qualify: it keeps the unreachable rule;
- the reviewer's answer does not say `same_bug: true`, whether that answer is valid or not;
- exactly one valid entry matches.

The ruling then decides the row:
- `not_needed`, or `hand_checked` with `reports_this_bug: false`: the row is cleared.
- `hand_checked` with `reports_this_bug: true`: the row is a confirmed public match, as if the reviewer
  had confirmed it, so G2 fails as `public_match`.
- Either way, a ruled row never sets `freshness_transport_pending`, so G2 does not wait on it again.

What a ruling does not override:
- A page the reviewer can read goes back to the reviewer: an access-failure ruling needs the receipt's
  access failure, and a hand check of a fetched page applies only while the reviewer leaves that page
  unresolved. A `not_needed` ruling never settles a fetched page.
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
  allowlist. Still, case text that names a case's bug stays out of the repo where it is not needed:
  `page_says` says what the page is (site, topic, product, version, date) and whether it reports this
  case's bug, without restating the bug; the same rule redacts the 18681d reviewer text in the test
  fixture.

### 4. Supporting changes in `ordinary_freshness` (plumbing, no identity)

- `keep_mixed_receipt` judges one row at a time through a namespace. That namespace now carries `case`,
  so a `hand_checked: true` row counts in `confirmed_rows`. `tools/open-g2-verdicts.py` already passes
  `case`.
- `ruled(c)`: the URLs the last verdict ruled (`freshness_review_summary['ruled_rows']`). Two places
  leave them out (design review 3, findings 1 and 2):
  - `stalled` never counts a ruled page as a wall to wait on. Otherwise another row's 429 next to a
    ruled 202 stops G2 as `freshness_source_blocked` after 3 cycles, instead of the 30-minute retryable
    stall.
  - `ensure.metadata()` never counts a ruled (unread) row as search evidence, as `_g2` already does
    (`freshness_unfetched`). Otherwise the two counts disagree: for 18681d, `_g2` is one builder/web
    search short while `metadata()` says enough, and since its saved `last_topup` equals the digest of
    its rows (read on the VM), the guard skips the top-up and refetches the 429 page until the attempt
    deadline. With the fix, the short minimum gets a top-up; it is charged as a defect only if the case is
    still short after it (bounded by `completed_defects` 2).

Nothing else about G2 changes: the reviewer prompt, the retrieval, the confirmation contract, the stall
stop thresholds, the minima and the searches all stay as they are.

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

`G2_SOURCE_RULINGS`, `g2_source_ruling` and `checked_freshness_verdict` are hashed only into G2's runner
inputs (the stress round's `loop_freshness` also reaches them, and the stress version hashes no runner
source). So only `gate_state.runner_inputs('G2')` changes. No other gate's identity changes, and
neither do the judge, model science or the delivery contract. The PR lists the `myident.py` proof, and
the committed test `test_only_g2_identity_reads_the_rulings` checks it.

Retained G2 data cannot skip a ruling:
- `public-search.json` is reused only when no row is flagged.
- `freshness-verdict.json` holds reviewer answers only, and the ruling is applied again on every read.

### Amendment: hand-checked pages the reviewer could not read (2026-11-20, 5813be)

- **Problem.** 5813be-h3 held G2 `review_unresolved` on one flagged row:
  `docs.medusajs.com/resources/references/medusa-workflows/createOrderFulfillmentWorkflow`. The runner's
  receipt is a live HTTP 200, but the saved body is the docs site's JavaScript shell ("Loading..."), so
  the reviewer answered `resolved: false`. h1 had held on four rows of `docs.medusajs.com/api/admin/orders/create-fulfillment`
  for the same reason. A ruling could not settle either, because the receipt shows no access failure
  (`tools/check-g2-rulings.py` on h3's snapshot: `MISMATCH`).
- **Change.** `g2_source_ruling` also accepts a `hand_checked` entry for a fetched page that the
  reviewer left unresolved (section 2). Nothing else changes: the same matching, validity, card and
  `ruled_rows` rules apply, and so does the hand check's `reports_this_bug`.
- **Rulings.** Two `hand_checked` entries, `reports_this_bug: false`, keyed to 5813be's statement
  (`6bef1af4...`): the workflow page (case `case-import-5813be-h3-1`; read by Claude in a browser and as
  the site's Markdown) and the Admin API page (case `case-import-5813be-h1-1`; its endpoint section never
  renders, so it was read from its source, the OpenAPI spec in medusajs/medusa). G2 reruns its searches
  on a relaunch, so either URL may be flagged again.
- **Not overridden.** A reviewer's `same_bug: true`, a `resolved: true` answer, an answer that disagrees
  with the receipt or names another URL, a receipt with no page (`retrieved_from: none`) and a page read
  from an archive copy (`retrieved_from: archive`).
- **Tests.** `test_a_hand_check_settles_5813be_unreadable_shells_never_a_confirmed_row` on both real
  rows (fixture entries read from h3's and h1's snapshots): the shipped hand checks clear them;
  `reports_this_bug: true` confirms a match; `not_needed`, a confirmed row, a read row, another URL, a
  disagreeing answer, a non-bool `same_bug`, no answer, a dead page with no copy and a dead page read
  from an archive copy settle nothing. It fails on the previous
  predicate, and each new guard fails it when removed. `test_each_held_row_stays_blocked_without_a_ruling`
  now expects these two rows to hold as unresolved, not as transport.
- **Identity.** Only G2's runner inputs change (`g2_source_ruling` and `G2_SOURCE_RULINGS`).

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
- **What a release reruns.** The resumed GATES attempt reruns G1, G2 and G3 (the table's "gates on
  card" is this attempt). Passes cached in `gate_state` from earlier attempts (cae763 G4/G5, 2a7b2a G4)
  stay valid, because their identities do not change (see the PR's identity lists per batch source).
- **The release is the resume.** `wait_for_fix` ends a hold as soon as the batch's plumbing changes
  (`engine.py` `wait_for_fix`). Every release to a held batch therefore resumes it, and uses one of the
  lineage's 3 factory-bug resumes (`MAX_FACTORY_BUG_RESUMES`). All three workflows began as imports
  (first result `admit:imported_hand`), not resumes, so their lineage count starts at 0
  (`lineage_factory_bug_resumes` comes only from a resume record); each card shows `diagnoses: 1`. This
  release is each lineage's first resume, leaving 2.
- **Search minima after the ruling.** An unread page never counts toward G2's minima
  (`freshness_unfetched`), and the ruling does not change that. G2's last recorded counts:
  cae763 builder/web 19, builder/github 25, attacker 8 (met); 2a7b2a 3 / 4 / 6, met only on cycles where
  the Shopline archive copy is found (then the row counts); 18681d 2 / 4 / 4, one builder/web short.
  Where a minimum is short, the cleared hold exposes it and G2 runs its usual top-up search
  (`evidence_incomplete`): 18681d takes this path. A top-up is charged as a defect only if the case is
  still short after it, and the second charged one ends `freshness_evidence_unavailable` (which
  diagnosis may treat as case-caused). The saved counts (read on the VM, 20 Nov): `completed_defects`
  cae763 0, 2a7b2a 1, 18681d 0.
- **2a7b2a's no-archive cycles now buy a top-up.** Before this change a 2a7b2a cycle with no Shopline
  archive copy refetched for free until the copy came back or the attempt deadline. Now that cycle,
  ruled and unread, is one builder/web search short and gets a builder top-up. Its first cycle likely
  reuses the saved archive receipt, so the row counts and no top-up runs; a reviewer re-ask refetches
  and can lose the copy. Because 2a7b2a already has `completed_defects` 1, one top-up that adds no
  readable builder/web search ends its G2 `freshness_evidence_unavailable`. The top-up appends rows to `case/freshness.jsonl`, which only G8/G9 identity
  reads; none of the three has passed G8 or G9 on this attempt. Today the hold stops the attempt before
  the top-up can run.
- **Case money.** The rerun (G1, G3, the re-asked review, 18681d's top-up) is paid from each case's
  remaining case money (`wait_for_fix` takes `case_limit`). I did not read the remainders; a shortfall
  is a money stop and another hold, so the operator reads each card's money before releasing.
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
  - a duplicate entry, a bad `kind`, an unknown key, a `hand_check` key on `not_needed`, an extra key in
    `hand_check`, or empty `page_says`;
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
- **18681d's path.** `run.g2` on 18681d's real row shape (ambiguous, searcher-unretrieved, 429), ruled
  by a hand check, one builder/web search short, with `last_topup` equal to the rows' digest: one builder
  top-up that fixes the shortfall, then G2 passes; `completed_defects` stays 0. Without the `metadata()` fix it refetches until cancelled.
- **A ruled wall is not a stall reason.** `stalled` on cae763's real 202 receipt, ruled, next to a held
  429 row: no `freshness_source_blocked` after 3 cycles; unruled, it stops.
- **Card and mixed receipt.** A later verdict without a ruling leaves no `ruled_rows` on the card;
  `keep_mixed_receipt` lists a `hand_checked` / `reports_this_bug: true` row in `confirmed_rows`.
- **Every shipped ruling is valid** and keyed to a held case's real digest and URL
  (`test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case`), so a malformed entry fails a test, not
  a held case.
- **Operator pre-release check, `tools/check-g2-rulings.py`.** It runs on the VM from the candidate tree,
  read-only and in memory, against each held case's latest snapshot: its real statement, flagged rows,
  current receipt and retained answer, through the candidate's own `g2_source_ruling`. It prints `OK`,
  `MISMATCH` or `NO RULING` per case, with G2's last search counts, the reviewer answer file it used, and
  how many flagged rows share each ruled URL. Its logic is tested on the fixture
  (`test_the_pre_release_check_names_each_ruling_ok_or_mismatch`); its snapshot reading was run live,
  read-only, on this branch: cae763 OK, 2a7b2a OK, 18681d NO RULING.

The existing G2 suites (`test_stream_d_retries`, `test_freshness_archive`, `test_freshness_restore_fixes`,
`test_admission`) pass unchanged.

## Murphy rows

The local register, `docs/murphy-register.md` in the main checkout, is untracked by design (AGENTS.md).

- **`new-g2-blocked-source-1` (new).** A flagged G2 source that blocks every fetch has no path to clear.
  The case holds for a release and every resume loops (cae763-h5, 18681d-h5, 2a7b2a-h1, 20 Nov). The
  sources seen are a bot wall, a 429/202 challenge, and a 403 whose archive copy is found only sometimes.
  Closed by `tests/factory/test_g2_blocked_source.py` (on authored statements) together with the recorded
  live run of `tools/check-g2-rulings.py` against the held snapshots (real digests and URLs).
- **`new-walled-flagged-row-1` (already closed).** Its open half, "a person reads it", now has a path:
  the `hand_checked` ruling.

## Operator steps (after the founder merges; the operator deploys)

`$V` is the campaign venv python; run everything in `~/durable-first-case-20261106` with `BOAT_NO_UPDATE=1`.

1. Upload the merge commit's tree to the VM as `source-<sha>` (as for every deploy), then run
   `$V -B source-<sha>/tools/check-g2-rulings.py case-import-cae763-h5-1 case-import-2a7b2a-h1-1 case-import-18681d-h5-1`.
   Expected, exactly: cae763 `OK`, 2a7b2a `OK`, each with `flagged rows with this url: 1`, and 18681d
   `NO RULING` until its hand check is in (a wrong digest also prints `NO RULING`, so check the case
   names). Stop on anything else. Also read each case's `G2 repair` line (`completed_defects`, recorded
   20 Nov: cae763 0, 2a7b2a 1, 18681d 0) and its remaining case money on the card; a case that needs a
   top-up (18681d; 2a7b2a on a no-archive cycle) with `completed_defects` 1 has one top-up left before
   `freshness_evidence_unavailable`.
2. Build and install the plumbing from that tree, for new launches only.
3. Send `plumbing_release` to `b-import-cae763-h5` and `b-import-2a7b2a-h1`. The release itself ends
   their holds; `resume_held` is needed only if a card still says `held_for_release` after a minute.
4. 18681d:
   1. The founder opens the page and fills in the `<...>` fields of this template, one
      `G2_SOURCE_RULINGS` entry (`page_says` describes the page; it need not restate the bug):

      ```python
      {"gate": "G2", "kind": "hand_checked", "by": "founder", "at": "<YYYY-MM-DD>", "case": "case-import-18681d-h5-1",
       "statement_sha256": "50f568b817bc374ddbcb3d6b927127db90fc368b1c2cb14b1477a9e7b30df5d5",
       "url": "https://www.answeroverflow.com/m/1273391376289239134",
       "ruling": "Hand checked: a person opened the page; the factory takes this check as its content.",
       "hand_check": {"checked_at": "<YYYY-MM-DD>", "checked_by": "<who opened it>",
                      "page_says": "<what the page says, in a sentence or two>",
                      "reports_this_bug": <True or False>}},
      ```
   2. The entry is added to `G2_SOURCE_RULINGS` in one commit (no other change; the shipped-ruling test
      checks it against the 18681d fixture digest and URL), reviewed by a goldfish, and merged by the
      founder.
   3. Run step 1 from that tree; 18681d must print `OK`.
   4. Install, then send `plumbing_release` to `b-import-18681d-h5`.

   Never release anything to `b-import-18681d-h5` before its ruling is in. Any release resumes it, and
   it would loop on the 429 again.
