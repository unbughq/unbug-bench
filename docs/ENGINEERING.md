# Engineering rules for the case factory

The founder adopted these rules on 2026-10-29, after two weeks of factory
pit stops. Every agent working on this repo follows them. If a rule here
conflicts with an older doc, this file wins.

## 1. Elephant and goldfish (from https://egm.dev)

- **Elephant:** the agent that holds the project context. It writes the
  design and the code, and it starts the goldfish reviews.
- **Goldfish:** a fresh reviewer subagent with no conversation history. It
  reads only the design, the diff and the files they reference. It is
  read-only, and it is never the agent that wrote the change.
- **Founder:** sets direction and settles escalations. The founder does not
  approve each design, unless the design changes a rule in section 4 or a
  security property.

### Flow for every factory change

1. **Branch.** One change gets one branch or worktree, cut from
   `factory-simplify`. Parallel agents never share uncommitted edits in one
   checkout.
2. **Design.** Write `docs/designs/<topic>.md` covering:
   - the problem;
   - the change;
   - what it deletes;
   - its tests;
   - the Murphy rows it closes.

   A fix under about 20 lines with an obvious cause may skip the design. It
   still gets step 5.
3. **Design review.** A goldfish reviews the design using `zoom_out`,
   `design_critic` and `implementation_readiness`.
4. **Implement and test.** Commit on the change branch, as often as you
   like. The full suite must pass:
   `uv run --with numpy --with scipy python -B tests/run.py`.
5. **Diff review.** A fresh goldfish reviews the branch diff against its
   design, using `zoom_out` and `implementation_readiness`. A reviewer from a
   different model family than the writer is preferred.
6. **Merge.** Merge into `factory-simplify` only when the review passes.

### What counts as passing

- **Pass** means no blocking finding is left open.
- **Who may reject a blocking finding:** the elephant may not reject a
  finding on its own work. A rejected blocking finding goes to a second
  goldfish from a different model family. If it agrees with the
  rejection, the finding is dropped. If it agrees with the first goldfish,
  the elephant fixes it. Founder escalation happens only when the elephant
  believes a fix would break a section 4 rule.
- **Nits** are optional.

### Records

- Save every review, verbatim, to `docs/reviews/<topic>-<design|diff>-<n>.md`.
- Record what was fixed, and what was rejected and why, in the same file.
- The merge commit lists every review file for the change in
  `Reviewed-by:` trailers.

### Personas

Reviewer personas are in `tools/egm/agents/`, and their standards are in
`tools/egm/document_standards/`. Both are copied from
google/elephant-goldfish-model at commit f0ba151.

Tell each goldfish three things:
- read its persona file first;
- use `Mode: REVIEW`;
- if the change skipped step 2, say so and review against the commit
  message.

Standards to name in the prompt:
- design review: `heilmeier-standard.md`;
- readiness review: `implementation-readiness-standard.md`.

A review never replaces tests.

## 2. Murphy register

`docs/murphy-register.md` lists every known way a batch can stop, hang or
give a wrong result.

- **Every design names the rows it closes.**
- **Closing a row:** a row is closed only by a test that uses real artifacts.
  - The elephant sets `Status` to `closed`.
  - It fills `Closed by` with the test path, in the same commit as the fix.
    The merge commit is the record of when the row closed.
  - The diff goldfish checks that the test really proves the row.
- **New failures:** every new failure seen in a real run becomes a new row
  before it is fixed.
  - Row numbers are taken only on `factory-simplify`, at merge time.
  - Branches add rows as `new-<topic>-<n>` until they merge.

## 3. Target properties

These are what the factory must become. They are not true yet, so check the
register for each one's status. A change that works towards one needs a
design.

- A launched batch finishes with no human pit stop. The only thing that
  reaches the founder is a real disagreement between reviewers about a case.
- Broken runs are never scored. An infrastructure failure is retried. It is
  never counted as a case pass, a case fail, or writer feedback.
- A case that runs out of rounds or budget goes to an automatic diagnosis
  agent, which picks one of three outcomes:
  - **factory bug:** resume after the fix, with the cost on the infra-waste
    line;
  - **close to passing:** one extension at most;
  - **not converging:** retire the case and start a replacement.

  The replacement launches at once and never waits on the diagnosis.
- Plumbing updates roll onto running cases at the next checkpoint. Plumbing
  means the launcher, router, retries, collection and publication.
- A gate change re-runs only the gates that changed for the affected cases.
  Every other pass is kept.

## 4. Design rules

- **No Mac dependency.** The control VM and R2 own the batch lifecycle:
  launch, resume, collection and publication. The founder's Mac can sleep,
  lose power or lose network without stopping anything.
- **Proportionate security.** This is an experiment VM, not a vault. On
  2026-10-29 the founder approved a scoped VM restore key. Keep the
  protections that keep cases secret from contestants. Drop ceremony that
  only adds pit stops.
- **No capacity excuses.** There are two full Claude accounts plus free
  models. The router handles limits: it waits, switches account, or uses a
  fallback from the same model family. A limit is never a reason to stop or
  to shrink the plan.
- **Plumbing and bench logic are separate.**
  - Plumbing carries no case result.
  - Bench logic means the gates, judge and scenarios. It is versioned per
    gate.
- **One launch path.** A resume is a launch from a checkpoint. Do not add
  per-case bundles, rescue branches or one-off rulings.
- **Real artifacts.** Tests use real saved cards, real bundles and real VM
  layouts. A fixture generated by the code under test proves nothing.
- **Delete before adding.** Prefer removing a path to guarding it.
- **Never push, and never touch `main`,** without the founder.
