# WP6/WP7 initial diff review 1

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Verbatim response:

---

**Verdict: FAIL.** The review found four blocking issues: one cross-package money-bound conflict, one key-secrecy issue, and two PostgreSQL first-use races.

Reviewed `git diff durable-execution...de/wp6-wp7` with integration branch `526e620f5fa3d29a62565ede28a9245b0e3fbc76`, package branch `4cabb424350229752a7096830fef5cddfe0d7311`, and merge base `db13be8f2ec5e51d453a7aea76fc16e37666bb7f`. The approved design, wave-1 brief and frozen contract are identical between the two branch heads.

1. **Blocker — actual spending can exceed both promised money limits.** `factory/durable/ledger.py:217-229` accepts and books usage above a grant. The WP6 note explicitly permits this at `docs/designs/durable-execution-wp6.md:86-91`, while the approved design promises concurrent cases never overshoot either limit at `docs/designs/durable-execution.md:204-213`. WP5a confirms an in-flight model call can overrun its ceiling at `docs/designs/durable-execution-wp5a.md:296-299`. For example, with a batch bound of 100 and two held grants of 50, settling the first at 60 leaves 110 booked or held. Reconcile the cross-package design and contract: enforce a real pre-call worst-case authorization, or obtain an approved revision of the bound guarantee. Do not clamp reported usage, which would hide expenditure. Add a concurrent runner-and-ledger overrun test.

2. **Blocker — key-bearing exception state survives sanitization.** In the swapped-scope failure already exercised by `tests/factory/test_durable_keys.py:170-175`, `factory/durable/keys.py:159-165` decrypts a real scope key and raises while `_unwrap` locals still contain its raw and base64 forms. An exception logger that captures traceback locals can expose them. Separately, `_age` raises inside an exception handler at `keys.py:49-56`: `from None` suppresses ordinary traceback display but retains `__context__`; a decryption `TimeoutExpired` can contain partial plaintext stdout. The existing secrecy test formats exceptions without locals and does not inspect context. Sanitize failures at the public service boundary after sensitive helper frames and original exception contexts have unwound. Test the swapped-scope failure with local-capturing traceback and a decryption timeout with recursive context inspection. Ordinary traceback formatting does not itself demonstrate a leak.

3. **Blocker — concurrent first `open()` is not idempotent on PostgreSQL.** At `factory/durable/ledger.py:149-153`, two transactions opening the same absent batch can both observe no row; `FOR UPDATE` cannot lock a row that does not exist. Both then insert, and one receives a unique-constraint error instead of the specified successful repeat and maximum bound. Use a conflict-safe insert/upsert or retry and lock the winning row. Add a synchronized PostgreSQL test for concurrent first opens, including different bounds.

4. **Blocker — concurrent key-service initialization can race on a fresh PostgreSQL schema.** `factory/durable/keys.py:94-95` calls `create_all(checkfirst=True)` independently in each constructor. Two processes can both observe the missing table and race its creation, causing one constructor to fail. `tests/factory/test_durable_keys.py:199-207` creates the table before starting its concurrent callers, so it does not exercise this path. Serialize or safely retry schema initialization, or establish a single initialization step before concurrent startup. Add a fresh-schema multiprocess PostgreSQL test.

The source implements the three specified label ties and the stated waste accounting. Once a batch row exists, its PostgreSQL row lock and SQLite `BEGIN IMMEDIATE` serialize reservation calculations and settlements; this does not resolve the overrun in finding 1. Same-scope key insertion reads back the stored winner.

The WP1, WP2 and WP3 source paths are consistent with retrieving keys inside DBOS steps, putting worker keys in `start_frame`, and passing the sealer identity through a pipe. That integration is **not proved end to end**: WP1’s workflow tests use a fake ledger and key service. PostgreSQL coverage is optional in the package tests and was not exercised by this review.

For WP8, carry forward the package note’s requirement to durably export each wrapped scope key with its artifacts. Losing the control database before its next backup otherwise makes affected R2 artifacts unreadable. This remains deployment and publication work.

No tests, databases, edits, checkouts or network operations were performed.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–4 | Open; design, fixes and verification follow after WP1, WP2 and WP5a in the specified order. |
| WP8 key export | Open deployment integration requirement. |
