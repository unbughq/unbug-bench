# Goldfish review: import money grant (diff 1)

- Branch: feat/import-money-grant, commit cf19b530 on main 47cb9a9d
- Mode: REVIEW (lenses: fail-closed money, replay safety, test coverage). No design doc (change under ~40 lines); reviewed against the commit message.
- Reviewer: goldfish (fresh agent), read-only. Ran tests/factory/test_durable_runtime.py (30 OK).
- Verdict: **PASS, no blocking findings.**

## How the money is enforced

The real ceiling is `spec.case_money_usd_micros`, which the ledger caps per batch and case. The grant is checked only at `Runtime.start`: `declared + spec.case_money <= 50M + raised`. The engine only records the grant for the card, so a grant cannot raise the ledger ceiling beyond what runtime allowed.

## Findings and disposition

1. NIT (fail-closed gap): `lineage_case_money_extra` read grants only from `<case>@...` resume workflows. An import's grant sits on the case job, so resuming a granted import that later stopped `held` would ignore it and refuse with `resume_money` (fail-closed; never over-grants).
   **Fixed:** the lineage now starts from the import case workflow's own `case_money_extra`. Test added.
2. NIT: a retried import start with a different grant attached to the existing batch and silently kept the first grant (the resume path refuses this).
   **Fixed:** mirrors the resume rule. A different grant on a retried start is refused with `case_money_extra_invalid`, and a retry with no grant keeps the recorded one. Test added.
3. NIT: CLI help text and the `case_money_needs_resume_case` code still named only `--resume-case`.
   **Fixed:** help text mentions `--import-file`. **Kept:** the error code name, since operators and scripts already match on it.
4. NIT: test gaps.
   **Fixed:** added a test that a grant with neither an import nor a resume gives `resume_invalid`, plus tests for findings 1 and 2.
   **Rejected:** a test that the stored job has no key without a grant. Both writes are guarded by `is not None`, and the existing card test fails if the key leaks into the card path.
   **Rejected:** a CLI end-to-end test. The CLI change is one condition, and runtime refuses the bad combinations on its own.

## Checked and clean (reviewer)

- Replay: the new key is written only when a grant exists and is read with `.get`, so older jobs replay unchanged.
- The card is set once from the recorded job, so the grant is never counted twice.
- The grant goes to the first case only, and an import has `max_cases_started` = 1.
- Overrides and role swaps remain resume-only.
- Grant validation runs before the money check, with the same limits as a resume.
- The boundary test (24,999,999 vs 25,000,000) proves "exactly the grant".
