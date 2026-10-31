I've finished the read-only diff review: **PASS**, with no blocking findings. The review below is ready to save verbatim as `docs/reviews/stream-b-deployment-inventory-diff-1.md`.

---

# Goldfish diff review: `stream-b-deployment-inventory` (diff 1)

Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `tools/egm/document_standards/implementation-readiness-standard.md`. Worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`, diff `d7c1277..HEAD` (`e1ea5af`, `7c9fc40`, `91ed74a`).

I read:
- `docs/ENGINEERING.md`, the persona files and the standard;
- the design, both saved design reviews and `docs/reports/stream-b-remaining-20261031.md`;
- `factory/deployment_inventory.py` and `tests/factory/test_deployment_inventory.py`;
- the manifest test change and `factory/launch_manifest.py:worker_files`;
- both full-suite records and their logs.

I made no writes in the repo, no paid calls, and started no workers or subagents. I did not rerun the full suite. I ran two targeted test files and two offline probes in a throwaway temp directory, then deleted it.

## Verdict: PASS

No blocking finding is open. The code matches the design's output contract, secrecy rules, bounded reads and exit codes. The manifest fix is correct and minimal. Nothing in the diff claims live cleanup, historical provenance, controller ownership or a Murphy closure.

## Independent checks

**1. Manifest-inventory fix: verified.**
- The retained failed log (`full-suite-20261031T131910Z-b6fd72a1.log.gz`) shows exactly one failure: `test_successful_bundle_dependencies_and_current_consumers`, with `Items in the first set but not the second: 'factory/deployment_inventory.py'`. Summary: `159 test scripts run; 1 failed.`
- `launch_manifest.worker_files` globs `factory/*.py`, so the inert scanner does enter the worker upload. The fix is a one-line addition to the independent expected set in `tests/tools/test_launch_manifest.py:87`. No bundling rule changed.
- `git diff d7c1277..HEAD -- factory/batch.py` is empty.

**2. Suite evidence: verified.**
- Both `log_sha256` and `uncompressed_log_sha256` values match the committed `.log.gz` files.
- The passing record (`full-suite-20261031T134357Z-c891d510.json`) says `exit_code: 0`, head `7c9fc40`, and `159 test scripts run; 0 failed.`, and its log agrees.
- Its `tested_files_sha256` matches `git show 7c9fc40:<file>` and HEAD for all three files. The only commit after `7c9fc40` adds the evidence files themselves.
- I also ran the two test files myself: `test_deployment_inventory.py` passed 8/8 and `test_launch_manifest.py` passed 2/2.

**3. No mutation: verified.**
- The module only lstats paths, iterates directories, and opens files with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK`. It never writes, takes no locks, starts no subprocesses, and makes no network or provider calls.
- The legacy-layout test compares file bytes and mtimes before and after two fresh CLI processes.

**4. Secrecy and output: verified.**
- A launch ID is printed only when it matches `[0-9a-f]{32}` and is a real directory, not a symlink.
- Allowlisted files and `new.N` files are reported by metadata only; their contents are never read.
- Unknown files, the restore copies and admission files are counted, not named.
- Ledger keys, raw values and status strings are never printed.
- The only errors on stdout are the four allowed codes. Argument errors go to stdout and stderr stays empty.
- The guard-layout test patches `read_regular` to fail on any read under the launch directory, and it plants poison strings in file contents, a filename, ledger keys and an unknown ledger field.

**5. Bounded accounting reads: verified.**
- The ledger and each source file are capped at 8 MiB: an lstat size check up front, then reading at most `LIMIT + 1` bytes.
- File identity is checked before and after the read.
- The parser rejects duplicate keys and NaN/Infinity tokens, and catches deep nesting (`RecursionError`).
- The version must be an `int`, so a bool is rejected.
- Any malformed record or unknown status makes the ledger invalid and `reserved_usd` null.
- A hold is expired only when its expiry is strictly earlier than the observation time.
- One exception to exactness is finding 1.

**6. Design compliance: verified**, including both rounds of design-review clarifications:
- `parked_markers` and `keep_markers` are counted by type, like `deleted_markers`;
- a non-regular numeric creation file makes the item an error;
- launches sort by ID and creations by serial string;
- `reserved_usd` is rendered with `format(total, 'f')`;
- an invalid ledger keeps the counts computed from parsed records, while envelope errors leave all counts zero;
- an invalid root returns the same envelope with `sources` empty.

**7. Murphy and claims: verified.**
- `docs/murphy-register.md` is not touched.
- The design and report say this is not live proof and that no row closes.
- The output always carries `activation_authorized: false`, `snapshot_atomic: false` and all four outstanding proofs.
- The remaining-work report gives carry-over to `t3/batch-carry-over` and router/cheap-profile work to stream A.

## Findings

**1. Severity: Major (non-blocking).**
*Scope:* `factory/deployment_inventory.py:197-220`, and the design line "use sufficient local precision for the exact sum (64 plus ledger-size digits)".
*Finding:* the precision is `64 + len(str(LIMIT))`, which is 71 digits. That is not always enough for an exact sum within the accepted bounds.
- A single accepted value can span 68 digits: 32 significant digits at exponent 18, plus decimals down to 1E-18.
- With 20,000 such records plus one `1E-18` hold, in a 2.1 MB ledger (under the 8 MiB cap), I got `state: ok` and a rounded `reserved_usd`: the `1E-18` was silently dropped.

This breaks the design's promise of an exact sum, never a partial one. It only happens at amounts around 1e53 USD, which `boat-spend` never writes, so it does not block.
*Fix:* add `context.traps[decimal.Inexact] = True` and treat the error as an invalid ledger. That one line fails closed whatever the precision is. Add one test with the 20,000-record ledger.

**2. Severity: Nit.**
*Scope:* `number()`, line 177.
*Finding:* `Decimal()` accepts surrounding whitespace (`' 1 '` → 1) and underscores (`'1_0'` → 10). These are lenient readings of ledger strings that `boat-spend` would never write.
*Fix:* optionally require `re.fullmatch(r'[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?', value)` for string inputs.

**3. Severity: Nit (test coverage).**
*Scope:* `tests/factory/test_deployment_inventory.py`.
*Finding:* two cases the design lists are not directly asserted:
- **`complete` presence:** the guard layout creates `complete` but never asserts it is `present`/`file`;
- **lstat failure on a launch file:** the `metadata` `state: error` path is never exercised. The "generic read failures" case only patches `os.open` for sources.

Neither leaves the behaviour wrong.
*Fix:* add one assertion for `complete`, and patch `Path.lstat` to raise `PermissionError` for one allowlisted name.

**4. Severity: Nit (record hygiene).**
*Scope:* the design's "Full-suite integration finding" section and `full-suite-20261031T131910Z-b6fd72a1.json`.
*Finding:*
- The design gained a new section after design review 2 passed. It is test-only and this review covers it, but the record should say it was added after that review.
- The failed-run record says `uncommitted_implementation: true` against head `e1ea5af`, and has no `tested_files_sha256`. It is a retained failure, so this does not matter for acceptance, but the run cannot be tied byte-for-byte to the code it tested.

## Zoom-out

- A standalone stdlib module with no persisted state and no integration is the right size. `factory/coordinator_inventory.py` queries the live fleet, so it does not cover this offline need.
- The stat-signature checks and digit/exponent bounds are more defence than a quiesced, trusted filesystem needs. They are cheap and fail closed, and they should not grow.

## Author disposition

*(For the author to fill in.)*

Author disposition: PASS accepted; no blocking findings were rejected. Finding 1 fixed with an Inexact trap and an invalid-ledger regression for the reported 20,000-record case. Finding 3 fixed with explicit complete metadata and allowlisted lstat-failure assertions. Finding 4 clarified in the design and failed-run record; the original failed run has no captured file hashes and none are retroactively claimed. Optional finding 2 deferred: decimal string syntax remains compatible with Decimal; numeric finiteness/range validation and secret-safe invalidation are unchanged. The final code receives another full-suite run. These are non-blocking follow-ups, not author verification of a blocker.
