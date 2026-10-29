# Extensions for cases that ran out of rounds or budget

Status: a seed for stream D. The rule and its limits are in
`docs/ENGINEERING.md` section 3. Stream D completes this design and gets a
goldfish review before any code. Reviews of the rule so far:
`docs/reviews/extension-rule-design-1.md` to `-3.md`.

## Mechanism as reviewed

- **Stages.** A case moves through its stages in order: stress review,
  then the gates in pipeline order. A case's furthest point is the first
  stage it has not yet passed. A case that ran out of rounds during
  stress review is at stage 0.
- **What an extension is.** One more writer round, plus its stress
  round, plus a re-run of the gates. It gets a fresh $15 allowance at
  list price, on top of the case's spend so far, drawn from the batch's
  money cap. Recent rounds cost about $5 each, so $15 covers the writer,
  stress and gate costs with room to spare.
- **What is recorded.** Before each extension, the case record keeps a
  snapshot of its furthest point and its gate results. A repair must not
  wipe these snapshots.
- **Who decides.** The diagnosis agent proposes each extension and
  records why. Code enforces the limits:
  - at most 5 extensions per case;
  - the batch still has room in its money cap;
  - each further extension needs progress.
- **Progress** means two things are both true:
  - the case's furthest point is later than in the previous snapshot;
  - every gate that passed in that snapshot still passes.

  An extension that runs out of its allowance before it reaches the
  gates counts as no progress.

## Open items for stream D (from goldfish review 3)

1. **Entry test.** Decide, in code, which case may get its first
   extension. For example: the case reached the gates, or its stress review
   has no open blocking finding.
2. **Gate versions.** Compare snapshots only at the same gate version. A
   gate change must not count as a regression and retire a good case.
3. **Prove the $15.** Point to real cost receipts for a writer round, a
   stress round and a gate re-run, including the model gates G10, G16 and
   G17. Raise the figure if they don't fit.
4. **Repairs inside an extension.** The gate loop runs up to 2 repairs
   (`factory/run.py:2297`). Say whether they are disabled inside an
   extension, or count against its one writer round.
5. **Amend `docs/factory-single-path.md`,** lines 36 and 65, to match.
