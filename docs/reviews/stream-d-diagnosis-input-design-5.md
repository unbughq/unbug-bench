No blockers, so this is a PASS for design readiness. One major is a stale-copy problem of the same kind as diff-22's Ma1, and it should be fixed before the dispatcher is wired. Nothing was written or run: no commits, tests, workloads, launches or decryption.

---

# Review: stream-d diagnosis-input design 5. PASS (no blockers, 1 major, 4 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. Personas: `zoom_out`, `design_critic` and `implementation_readiness`. Standards: `heilmeier-standard.md` and `implementation-readiness-standard.md`.

**Scope:** `docs/designs/stream-d.md`, section "Queued diagnosis inputs (review-17 follow-up)", at `a540e70`, cumulative diff `ebf3b1a..a540e70`. The diff touches only that section plus the two added review records.

**Read verbatim:** `stream-d-diagnosis-input-design-3.md`, `stream-d-diagnosis-input-design-4.md` and `stream-d-diff-22.md`, with their elephant resolutions.

**Supporting inspection only:**
- `factory/gate_state.py` (`inventory`, `save`, `load`)
- `factory/diagnosis.py` at `ebf3b1a` (`add`/`add_tree` selection, `_verify_input_records`)
- `factory/run_artifacts.py` `seal`
- `bin/bench.py` `RESULTS`/`IDS`/baseline paths
- the `run.py` restored-results readers

The `ebf3b1a` production code is still the old, unqualified version. It still checks `card.sha256` against the generation and still copies `gate-cache` whole. It is not reviewed here.

## Prior findings carried forward

- **Design-4 Ma1 (founder-correction and carry-forward receipt tests): resolved.** The tests now name three real `restore_ledger.install` branches:
  - an authenticated founder correction, where the public ledger differs from the archived ledger, accepted through `retained_ledger_sha256`;
  - deleting that field or changing its digest refuses. Deleting it makes the binding fall back to `ledger_sha256`, which is the "compare against `ledger_sha256`" mutant design 4 asked to kill;
  - a carried-forward ruling (`ruling_carried_forward: true`, no `retained_ledger_sha256`) accepted through `ledger_sha256`.

  The design also states that authored ruling and control envelopes are marked as authored and use the saved real ledger and practice bytes.
- **Design-4 N1–N4: resolved.**
  - N1: a missing or null archived `continuation_budget` refuses, with no fallback to the work ledger.
  - N2: the version check is `type(version) is int` and `version == 1`; the authentication check is `accounting_authenticated is True`.
  - N3: `card.json` has its own bullet.
  - N4: there is a rationale paragraph. The receipt is code-written proof of restore that can be frozen for replay. `source_generation` is mutable current authority.
- **Founder correction on the archived-card generation: holds.** The generation comes only from the existing `sealed/<case>.restore-accounting.json`, through the existing `launch.sh → restore_ledger.install → authenticate/_authenticated_source` path. The design says the card's `sha256` may be absent or older and must never be used as the generation. No new launch mode, field, producer change or authority is added. B's RAM job config stays the current binding, and a receipt cannot replace it.
- **Design-3 resolutions 1–6: still hold.**
  - Replay checks the frozen receipt and card against the manifest generation. It never checks against the live receipt or the current binding.
  - Changed or missing frozen bytes refuse.
  - The orphan, lifecycle, stop-evidence and isolation rules are unchanged.
- **Diff-22 Ma1 (stale gate-cache hints): resolved in the design.**
  - At creation, all selected current evidence is copied first. Each `gate-cache/*.json` record is then kept only if every evidence reference is safe, has kind `work` or `bench`, carries a SHA-256, and resolves to an already-copied file with the same digest. Stale, malformed or missing-evidence records are left out. Their live bytes are not touched.
  - This matches how `gate_state.load` already treats unusable records: return `None`, with no authority. That is a reuse of existing semantics, not a new mechanism.
  - Unsafe paths, symlinks and non-regular files still refuse, so leaving a record out cannot mask tampering or a path attack.
  - Replay is strict. It never leaves out or re-selects a file, and every retained cache reference must still resolve. So "omit at creation" cannot become "omit at replay".
  - The planned pass-then-fail-then-exhaust test uses a real `gate_state.save` record, overwrites the detail the way a failed re-run does, and asserts all of: the freeze succeeds, the failed detail is kept, the stale record is left out, and the live cache is unchanged.
- **Diff-22 N1 and N2:** they stay as stated. Reconciliation before the snapshot is the dispatcher's job, and N2 is a planned descriptor-based read. Neither is a design gap.

## Findings

### Blockers
None.

### Majors

**Ma1. The rule that restored and current bench copies must agree has the same stale-copy problem as diff-22 Ma1. Fix before dispatcher wiring.**

- **Where:** the `work/` inventory bullet: "Current inventory bench-kind files go under that same `work/bench-results/` prefix; if both copies exist they must agree." This text predates the amendment, but the amendment's claim that pass-then-fail cases "must remain diagnosable" depends on it.
- **Mechanism:**
  - `RunArtifacts.seal` moves every `bench/results` file written since `c.t0` into `work/bench-results/` (`run_artifacts.py:59–62`). The archive therefore carries the earlier run's copies.
  - On a resume, the same bench rewrites fixed-name files under `RESULTS`. Examples: `runs/baseline.json` (`bench.py:339`), and under a factory slot, `factory-slots/<n>/seed-ids.json` (`bench.py:26`), which is regenerated by each fresh seed.
  - The snapshot is taken during the run, at the exhaustion point, before that run's seal. Both copies exist then, under the same relative path.
  - If their bytes differ, `add` raises `different input copies`. The case then stops terminally with `diagnosis_input_invalid`, with no automatic reset.
- **Who is affected:** any case resumed at least once on the same slot path whose re-prepared bench bytes differ. That is the population that typically reaches `budget_exhausted` or `extension_incomplete`.
- **Evidence status:** read from code, not executed. The elephant should confirm with real saved bytes that two prepares produce different `seed-ids.json` or baseline bytes.
- **Fix:** mirror what the next seal already does. For a duplicated relative path, the current `bench/results` copy is the one frozen at `work/bench-results/<rel>`; the restored copy is superseded, just as `shutil.move` would overwrite it. Cache records whose bench evidence named the superseded bytes are then left out under the new cache rule. No other change is needed.

  Add a named test: a restored `work/bench-results/<fixed name>` whose bytes differ from the current file under the same relative path. The freeze must succeed and record the current bytes. If the elephant prefers to keep both copies, it must name a distinct prefix and say which one cache resolution uses. "Current wins" is the smaller change.

### Nits

- **N1. The inventory contradicts itself.** The `work/` bullet still lists `gate-cache` among the roots kept whole by name. Later text says cache records are copied selectively. The planned stale-cache test would catch an implementation that copies it whole, but the bullet should drop `gate-cache` or say "selected per the gate-cache rule below". The current code (`diagnosis.py:430`) copies it whole, so this is exactly where an implementer would read the wrong rule.
- **N2. A kept cache record is not a current verdict.** A record that passes the evidence check can still have a stale fingerprint, because the source changed since it was saved. `gate_state.load` would reject it, while the snapshot keeps it. The design says "no cached verdict is promoted". To stop the diagnosis role reading `info` as a current gate pass, add one sentence: kept cache records are historical receipts of an earlier pass; the current gate outcome comes only from the card and the current gate details.
- **N3. The cache test list is missing two path cases.** "Missing and malformed cache references" should explicitly include:
  - an absolute or `..` reference;
  - a reference that resolves through another `gate-cache/` file.

  Both must be left out, never followed. Add one assertion that a symlinked `gate-cache/*.json` still refuses rather than being left out, which is the "only semantic invalidity is omitted" boundary.
- **N4. Formatting.** "No card SHA is synthesized or overwritten. Gate-cache records are optional reuse hints…" runs two separate rules into one line. Start the cache rule as its own paragraph.

## Review against the brief

- **Stale-selection safety:** the cache side is correct and fails closed at both creation and replay. The bench duplicate rule (Ma1) is the remaining gap of the same kind.
- **No cache authority, no false scientific verdict:** records are left out without re-certification. Nothing is promoted to authority, and live bytes are not touched. N2 adds wording for the diagnosis-reader side.
- **Immutable replay:** it is strict. Exact inventory and digests are required, cache references must resolve, and nothing is re-selected. The original generation survives later restores.
- **Receipt binding:** all three ledger branches are specified with real-install tests. Types are strict. A missing embedded budget refuses.
- **Test completeness:** the tests cover design-4 Ma1 and diff-22 Ma1. Ma1 above and N3 add the remaining cases.
- **Heilmeier and readiness:** the problem, change, rationale, target files (`factory/diagnosis.py` and the held/input tests) and test plan are all present. The section states that nothing is deleted and no Murphy row closes.

## Validation boundary

PASS applies to design readiness only. Ma1 should be fixed in the design before the dispatcher calls `queued_inputs`, because the failure is a terminal refusal. The `ebf3b1a` code still needs these changes and its own diff review:
- receipt-based generation;
- selective cache copying;
- the bench duplicate rule;
- the descriptor-based read (diff-22 N2).

No files were written. No tests, suite, workloads, launches or decryption were run. No Murphy row closes. No dispatcher, money or runtime enablement is claimed.

## Elephant resolution

PASS accepted with Ma1 and all nits accepted. The existing seal overwrites a
restored fixed-name bench result with the current result; snapshot creation will
use the same current-copy precedence. Keep strict frozen replay. Add the named
duplicate, historical-cache and unsafe-reference cases, and clarify the list.
No finding is rejected. A fresh focused design review follows before implementation.
No Murphy row closes.

