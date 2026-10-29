# Goldfish design review: `docs/designs/invalid-runs.md` (Mode: REVIEW)

Personas used: zoom_out, design_critic, implementation_readiness. I read the design, `docs/ENGINEERING.md`, Murphy rows 14, 22–25, 36, 38, 40 and 41, and the code the design cites. The zoom-out standard could not be applied as written: `tools/egm/document_standards/` does not exist in this checkout. I modified nothing.

**Verdict: FAIL.** Three blockers are open.

---

## Blockers

**B1. The boundary marks failures caused by the guard as infrastructure, so some cases can never get a verdict.**
- **Scope:** design lines 12–16, item 1 (lines 22–24), item 2 (lines 31–32), deletions (line 88).
- **What's wrong:** item 1 treats every record error and every false checker validity as `invalid-infra`. In this codebase those are often real results:
  - `factory/run.py:2052-2053` (note dated 2026-10-18): runs that error under the pilot's guard, for example because it broke cart creation, mean the attempt failed.
  - `factory/run.py:2041-2042` (2026-10-20): a guard that breaks the API's shape crashes bench scoring, and that attempt failed.
  - `bin/bench.py:651-653`: a reset that fails because the guard was rejected is marked invalid.
  - `bin/verify-negative:194-199, 267-268`: tamper probes expect `checker.valid is False` as the *correct* rejection. A case cheat that tampers with stock behaves the same way.
- **Consequence:** under the design, a calibrator or cheat guard that reliably breaks traffic or trips tamper detection gets retried with identical inputs, fails identically every time, stops as resumable, and is resumed forever. G6, G7 and G10 never reach a verdict. Row 23's own fix asks to "separate harness-invalid attempts from guard-caused failures"; the design drops that distinction.
- **Required:** a written rule for blame, either by error stage (for example infrastructure reset/build versus guard install/traffic/checker), or by what happens when the same guard fails again but reference/no-guard controls stay valid. Say what each gate does with a guard-caused invalid result, and add a real artifact of one to the tests.

**B2. Retries are not saved anywhere, so a failure that always repeats loops forever.**
- **Scope:** lines 14–16, item 2 (lines 29–30), item 3 (line 36), item 7.
- **What's wrong:**
  - The `checkpoint` retry runs inside the gate retry, so one gate can execute up to 3 × 2 = 6 checkpoints. The design doesn't say whether that is intended, or how it stays within "does not expand economic/worker lifetime limits".
  - No retry counter is saved. Exhaustion becomes `runner_error:*`, which `factory/recovery.py:11` treats as retryable, and each resume starts the counter at zero again.
- **Required:**
  - Where the count lives (card field or private file), its key (gate, guard, seed, run count), how resume reads it, and the final state once the total is used up.
  - For G10, say that a retry re-runs `checkpoint` only, on the already-saved `ws/guard`. It must not re-run the paid calibrator. It also must not touch `CalibrationSeries` rows or advance the try number.

**B3. The new card shape is not handled by recovery, so the "resumable stop" claim is false.**
- **Scope:** item 3 (lines 36–41).
- **What's wrong:** the design says "Recovery's existing runner-error path handles this form". It doesn't:
  - `crash_stop` (`factory/recovery.py:14-26`) requires `failed_gate`, `failed_detail == {"error": …}`, a matching `gate_results` entry and `gates[G] == "fail"`. The new form sets none of these, so `recoverable_crash` returns `None`.
  - Several other checks only test `'fail' not in gates.values()`: `rereview_stop`, `freshness_retry_stop`, `gate_only_continuation` and `raised_limits`. An `"invalid-infra"` value passes all of them, which may send the card down the wrong recovery path.
  - The fields of `infrastructure_gate` are not defined.
- **Required:** define `infrastructure_gate`, list every reader of `card["gates"]`, `failed_gate` and `terminal_stop` (recovery, public_progress, coordinator, scorecard/collection, restart), say how each changes, and add one test per check that loads a real old crash card and a new invalid-infra card.

---

## Majors

**M1. G6's generic probes have their own invalid outcome that the design never maps (row 22).**
- **Scope:** item 2, row 22.
- `bin/verify-negative` reports `invalid-probe` and exits non-zero, and `g6` (`factory/run.py:1870-1877`) treats a non-zero exit as a scientific G6 failure. The design never says which side of the boundary this is, so row 22 stays only partly closed.

**M2. The new exception is caught by existing handlers.**
- **Scope:** item 1.
- `InvalidInfra(RuntimeError)` will be caught by `factory/run.py:1334` (`early_cheat_check` catches RuntimeError and continues to `attack_unresolved`). After that handler, `passed` at line 1336 may be unbound. Before line 2040 is deleted, it would be caught there too.
- Either don't subclass `RuntimeError`, or list every handler and how it changes.

**M3. One G14 check and the S11 patch source are missing (row 14).**
- **Scope:** item 6.
- G14's local `clean()` (`factory/run.py:1516-1517`) returns a scientific failure for invalid summaries. It is a per-call-site validity rule that the design neither removes nor routes through the shared boundary.
- `bin/strategy:94` already raises `ValueError` on invalid evidence. Say whether that becomes `InvalidInfra`.
- The "supplied two-number S11 patch" is not in the repo or the design. Name the files and lines.

**M4. G2 retrieval is underspecified and can stop cases permanently (row 24).**
- **Scope:** item 4.
- A page legitimately over 2 MiB is "truncated" and therefore invalid-infra, so it can never clear. Say how oversized bodies are handled.
- The design assumes the G2 runner process has outbound network access on the worker. It doesn't say where G2 runs, so that is unverified.
- It also doesn't say what "a successful lookup" means for Wayback, or how proxies and redirects to a different host are treated.
- From the zoom-out view, this is a new subsystem inside a boundary design. It is acceptable only because row 24 requires it, but it should be its own numbered step with its own tests.

**M5. Reviewer selection for G11, G16 and G17 is left to the implementer (rows 40, 41).**
- **Scope:** items 7 and 8.
- The design does not say where "an approved independent reviewer" and "next configured reviewer whose family differs" are configured, or what the prompt, output schema and budget source are. G11 adjudication is a new paid model call, and its cost line isn't stated.

**M6. Version bumps invalidate most cached passes, and the calibration rules contradict each other.**
- **Scope:** item 9, item 1 (line 26).
- Adding `run_validity` to the `MEASURE` dependencies changes fingerprints for G4–G6, G8, G9 and G13–G16. Changing `checkpoint_evidence.py`'s default already does the same, because it is in `MEASURE`. Every cached pass reruns, which conflicts with ENGINEERING §3 ("re-runs only the gates that changed").
- Bumping the calibration identity makes every G10 rerun its paid calibrators.
- That bump also makes "quarantine invalid legacy suffixes" pointless, because an identity bump rejects all old rows anyway. Pick one, and state the cost.

**M7. Collection drops the register's exceptions and leaves terms undefined (row 25).**
- **Scope:** item 5.
- Row 25's fix says to keep the explicit probe/startup exceptions. Without them, a card from a probe or startup failure (no archive by design) fails collection, and the worker is kept forever.
- The archive name pattern for final versus checkpoint archives is not given.
- "Stale" is not defined, for example as an archive digest that differs from the card but has an exact name match.

**M8. Real-artifact tests are not reproducible as written.**
- **Scope:** lines 97–104.
- The "provided read-only SSH command" is not in the design. The test suite can't depend on SSH, so the fixtures must be committed.
- Name the exact `results/` source paths and how many of each class are used.
- The list doesn't include a real guard-caused error batch (see B1) or a real verify-negative `invalid-probe` output (see M1). Without both, rows 22 and 23 can't be proven closed.

---

## Nits

- **N1.** `tools/egm/document_standards/` is missing, although ENGINEERING §1 says it exists.
- **N2.** Item 2 keeps `require_valid=False` as an escape hatch. Prefer deleting it unless a named caller needs it.
- **N3.** Item 8 says "update its execution evidence atomically" but doesn't name the file or how it is replaced.

---

**Not PASS:** B1, B2 and B3 are open.

## Elephant response (after the verbatim review)

Revised the design's normative resolution section for B1–B3 and M1–M8:
saved retry accounting and pending G10 submissions; explicit exhausted operational
stop and recovery consumers; valid judge rejections versus unproven runtime blame;
generic probe mapping; exact retrieval contract; configured reviewer selection,
schemas and budget; scoped identity migration; collection exceptions; committed
artifact sources and honest closure limits. No finding is rejected. The next
goldfish must judge whether the runtime-blame rule satisfies B1 under the user's
instruction that runtime failures never become scientific results.
