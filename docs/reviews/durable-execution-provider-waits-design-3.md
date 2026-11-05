# Provider waits design review 3

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

FAIL

- **Blocker — concurrent wait classification is underspecified.** [The design](/private/tmp/unbug-wp1-terminal-20261105/docs/designs/durable-execution-provider-waits.md:53) requires capturing joined waits but does not define which single result wins for simultaneous credential and quota waits, or how to handle a surfaced `cancelled` with a joined provider wait. The existing runner handles that cancellation case in `de/wp5a@63d01f1:factory/run.py:3820`, while its engine path flattens the exception at `:3524`. Specify precedence and reset selection, distinguish current waits from earlier serial attempts, and assert these cases in the integration test.

- **Blocker — the router deadline is not tied precisely to the supervisor’s deadline.** The design says “attempt deadline,” but `de/wp5a@63d01f1:factory/durable/worker_step.py:343` starts the supervisor deadline before restore; `factory/run.py:3247` computes another deadline afterward. Require the router deadline to be bounded by the supervisor’s actual deadline and test delayed setup.

The WP8 gate addresses scoped, generation-aware health clearing, concurrent and stale observations, and delivery to newly provisioned workers. The WP1 policy, report, worker-release, and fake-seam slice can proceed under the stated founder decision without changing `contract.py` or touching real secrets. Real credential recovery remains gated on WP5a and WP8.

No files were changed; no tests, databases, checkout, or network were used.

---

## Resolution

| Finding | Disposition |
|---|---|
| Concurrent wait selection | Revision 4 specifies current-step-only collection, credential precedence, cancellation handling and reset selection; fresh review and WP5a integration remain pending. |
| Supervisor deadline | Revision 4 binds router timing to the supervisor's actual pre-restore cutoff, with a slow-restore test; fresh review and WP5a integration remain pending. |
