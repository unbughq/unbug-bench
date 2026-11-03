# Preflight diff review 1

Goldfish: fresh Codex (gpt-6.1-sol, reasoning high) delegated task, read-only. This is a different model family from the Claude writer. Personas: zoom_out and implementation_readiness, Mode: REVIEW. Diff: `656cc15..cddd8ad`, excluding the parallel-runner merge. HEAD at review: 9207fd8; the commits after cddd8ad add suite reports only.

## Verdict: FAIL

### Blocking
- **B1. `factory/practice_preflight.py:179`: preflight discards archive metadata that the launcher validates.** The dictionary silently collapses duplicate members and strips `./`, and `router()` then checks a rebuilt archive. A bundle with duplicate credential members can pass preflight, reach `dispatch_started=True`, and then fail the real launcher's `router_delivery.pack`. Smallest fix: before building the dictionary, reject incompatible names, duplicate members and unsupported member types with `PreflightHold`. Add a real-dispatch regression showing the operation stays pending.
- **B2. `tests/factory/test_preflight.py:85`: retained policy/release coverage is missing.** The inherited setup fabricates the policy and release, and mocks `batch.verify` (`tests/factory/test_batch_service.py:45–51`). Only the practice manifest is retained. This breaks the design's artifact requirement and overstates the evidence for closing `new-preflight-2`. Smallest fix: use the retained practice policy and pinned release with real verification, and correct the fixture description and the Murphy closure claim.

### Nits
- **N1. `factory/practice_preflight.py:229`:** router preflight makes a second `status` RPC after `pack` already made one, where the design specifies one.
- **N2. `factory/practice_preflight.py:43`:** the returned "effective practice paid ceiling" uses $19.99, but practice specifies $11.63, and dispatch ignores the return value. Remove the unused calculation or make its meaning accurate. The existing router still enforces $11.63.

### Confirmations requested by the brief
- Design-review B1–B4 are implemented on their main paths:
  - credential holds replace the terminal label checks;
  - dispatch decrypts once, in memory;
  - `available_credit(token)` keeps existing callers working;
  - R2 does one signed GET;
  - the paid status check validates the schema and zero outstanding;
  - setup checks the SHA-256 before installing and fails closed.
- A recipient mismatch and a fingerprint mismatch are still terminal. No new secret persistence, environment export or credential logging was found.
- `eval` takes shell-quoted arguments. `parse_known_args`, rotation defaults and fail-closed role resolution are all present. No other ungated Codex launch path was found.
- The tests exercise the real `dispatch`, age and the local TLS router fixture. The Boat text and receipts are retained, and the JWT is explicitly authored. The policy/release evidence has B2's limitation.
- Murphy rows 1 and 4 show their narrow regressions. Rows 3 and 5 correctly stay open. Row 31's checksum-refusal test supports its installer note. Row 2 is overstated.

### Tests run by the reviewer
`test_preflight.py`: 19 passed. `test_batch_holder.py`: 60 passed.

## Elephant resolution
Both blockers are accepted. The fixes go to a fresh implementer, followed by a fresh diff goldfish (round 2 of 2).
