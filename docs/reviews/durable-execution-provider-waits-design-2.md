# Provider waits design review 2

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

FAIL

- **Blocker — WP5a’s proposed metadata source is not populated reliably.** At `de/wp5a` commit `63d01f1`, `run_step` catches `ProviderWait` and converts it to a string without writing the current wait to `c.card`. The proposed lookup can therefore see no reason or stale snapshot data. The router also emits `ProviderWait` only with `UNBUG_PROVIDER_WAIT=1`; that mode requires a job ID, which the engine context does not provide. Specify engine-mode activation and identity, capture fresh reason and reset metadata before the exception is flattened, and prevent stale metadata from classifying a later wait. The WP5a gate must test the real router → runner → worker path, including credential and quota waits.

- **Blocker for the later WP8 repair gate — a healthy observation clears too much.** `observe(pool, healthy=True)` currently clears all health entries for that pool and its routes, including unrelated or newer quota, credit, rate, and outage observations. Credential delivery alone cannot verify those conditions. Require scoped or conditional clearing that preserves independent and newer blocks. Test duplicate or stale renewal receipts and a concurrent unrelated block. Since WP1 releases the waiting worker, the gate must also prove newly provisioned workers receive the verified replacement credential.

The other prior findings are resolved **in design scope**, pending implementation and tests: old draft journals are explicitly unsupported under the undeployed, disposable-database boundary; the report must accept and publish the credential status and publish `running` on wake; and both credential and genuine-provider waits release workers. WP8’s separate fresh-generation database gate remains open.

The frozen `max_spent_limits_per_step` field remains serialized and validated but no longer enforces a provider-wait cutoff; paid limits still settle as batch waste under the cumulative bound. WP1 may implement and test its policy, status, release, and fake-seam behavior now. It cannot claim real credential recovery until the WP5a and WP8 gates pass.

No files were changed; no tests, databases, checkout, or network were used.

---

## Resolution

| Finding | Disposition |
|---|---|
| WP5a current-wait metadata | Revision 3 specifies engine wait-mode activation, case-derived identity, current-exception capture and cross-package tests; implementation remains pending. |
| WP8 credential clearing | Revision 3 requires scoped, generation-aware clearing and tests preserving independent/newer blocks; implementation remains pending. |
