- **NIT — Non-default VM forwarding lacks coverage.** In [test_campaign_launcher_vm_type.py](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-abef7a1161b77b73d/tests/factory/test_campaign_launcher_vm_type.py:86), every approved-type case uses `default`. I confirmed that all four tests still pass if the wrapper always forwards `default`; with an approved `large` request and helper, that mutation creates a default VM. Add a case that asserts Boat receives `--type large`.

- **NIT — The architecture guide omits the bounded-campaign restriction.** [ARCHITECTURE.md](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-abef7a1161b77b73d/ARCHITECTURE.md:632) says a helper’s `vm_type` may differ. An operator who configures an approved `large` helper for a `default` bounded campaign will instead get a refused lease and local fallback. The guide should state the bounded-campaign exception.

The create and credential-delivery signatures match their call sites. For **fresh creates**, rejecting a different type before `reserve_start` is consistent with the compute bound, which prices every slot at the request’s rate. Existing-worker reuse bypasses that type check and checks the observed rate on credential delivery; that path predates this diff and books no new start.

The new tests exercise the real `acquire`, `_create`, and controller wrapper. With filesystem and locking substituted in memory, all four passed on HEAD; using the `origin/main` controller, the three acquire tests failed with the original `TypeError`. The warm test calls the wrapper with the same two arguments as `_make_warm`, rather than invoking `_make_warm` itself. The unmodified test run could not get past setup because the read-only sandbox has no writable temporary directory; live Boat was not exercised.

PASS (no blocking findings)
---

## Elephant's record

Reviewer: Codex gpt-6.1-terra, read-only, on commit 6ea112d1. Verdict: PASS, no blocking findings.

- NIT 1 (non-default type not covered): fixed. Added `test_an_approved_large_type_reaches_boat`, which
  approves `large` in the request, acquires with `vm_type="large"` and asserts Boat's `new` gets `--type large`.
- NIT 2 (ARCHITECTURE.md says a helper's `vm_type` may differ): fixed. The helper paragraph now says the
  bounded campaign controller refuses a helper type other than the request's approved one.
