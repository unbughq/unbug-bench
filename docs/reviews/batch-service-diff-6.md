**Verdict: PASS.** I found no blocking findings. The code PASS from diff-4 carries forward: `git diff --stat 34098c8..HEAD` touches only the two designs and two reports, and nothing in the docs contradicts the reviewed code at 19289c8. The contract follows your latest refinement. The two Major findings are readiness gaps to fix before 2b is coded, not blockers for this contract. I edited nothing and ran nothing beyond `git` and `grep`.

## Findings

**1. Major (readiness): one root-count cap is not named.** Affects `interfaces.md` §"Replacement derivation" and `batch-service.md` §"Authorized replacement chains", in the paragraph that starts "Increment2b removes check_manifest's current <=len(jobs)…".
- That paragraph names only `check_manifest`, at `factory/batch_money.py:43-44`.
- `factory/key_holder.py:126` (`policy_load`) has a second, independent check: `1 <= max_concurrency <= len(policy['jobs'])`. Remove only the first and the test "max_concurrency greater than root count" still fails in the holder.
- The same list should also name the direct lookups that a derived job breaks:
  - `factory/key_holder.py:559`: `policy['jobs'][name]` on launch;
  - `factory/job_config.py:69`: `record['jobs'][current['job_id']]`;
  - `factory/batch.py:138`;
  - `factory/batch_money.py:94/121/142/144`.
- `factory/batch_money.py:73` (`record['jobs'] != policy['jobs']`) is fine to keep, because derived jobs never go into either map.
- **Minimal fix:** add `key_holder.policy_load`'s `max_concurrency` cap to the named removal list, and list the lookup sites above.

**2. Major (readiness): how the settled checkpoint gets collected is left to the implementer.** Affects interfaces §8 ("A known settled checkpoint must be durably collected/acknowledged before dependent replacement admission; it does not wait for the diagnosis result") and the matching sentence in `batch-service.md`.
- The worker's single ordinary resume does three things in order: it settles, checks that the total is known, and then runs diagnosis, which makes model calls.
- The replacement needs a collected and acknowledged known-total checkpoint before it is admitted, and must not wait for the diagnosis.
- The docs don't say how that checkpoint gets out while the same worker keeps running. There are two possible paths:
  - **(a)** If the total was unknown at launch, the worker checkpoints and exits after settling. That checkpoint is collected and acknowledged, and diagnosis runs on the next ordinary same-owner relaunch. This decision comes from the restored state, so B gets no new mode.
  - **(b)** A mid-run checkpoint is published and collected while the worker stays live. No current collection path does this, and interfaces line 150 assumes a checkpoint carries no live record.
- **Minimal fix:** state (a) in one sentence. It reuses the existing checkpoint, collect and launch path. It also stays consistent with "no settlement-only mode", because the stop is a worker decision, not a B mode.

**3. Nit: which priority class an exhausted resume with an unknown total belongs to.** The order is: settlement resumes, then replacement, then the exhaustion/diagnosis resume. Add a few words saying that an exhaustion resume with an unknown total is in class 1 (the settlement resume), and one with a known total is in class 3. Otherwise a reader could put it behind the replacement it is blocking.

**4. Nit: suffix rules.**
- Say that `-r<positive integer>` means canonical decimal with no leading zeros, so `J-r01` is reserved and can never be derived.
- Say that `check_manifest` enforces both the reserved suffix and the exact `replacement_policy` shape `{schema:1, enabled:bool}`. Today it validates neither; unknown keys pass silently. That is safe while derived work is gated off.

**5. Nit: one report line reads like the superseded behaviour.** `docs/reports/batch-service-increment-2.md`, under Delivered: "exhausted owners settle without a model call". Reword it to "settle before any further model call".

## Checked facts
- The diff is docs-only, which matches the claim that the code basis is unchanged.
- **Your points (1)–(3)** are all present and consistent in both designs:
  - Diagnosis adds no launch mode, flags or frozen-config fields; it runs in an ordinary same-owner relaunch, after settling and a known-total check, under the original owner.
  - D's pure eligibility function and pending-diagnosis projection are consumed; B does not re-derive them.
  - One replacement is queued immediately per immediate parent; denied-zero work doesn't qualify and zero-cash work does; nothing waits for diagnosis.
  - `replacement_policy` enabled/absent behaviour, the reserved `-rN` suffix and deterministic J→J-r1→J-r2 naming are specified.
  - The journal deduplicates on the immediate parent across generations and extensions; each child gets a distinct owner and reservation.
  - One shared pure resolver is used, and the frozen manifest and the nine-field config are not mutated.
  - There is no hidden cap on chain length; the cumulative money bound and the deadline are the only total limits.
- **Earlier contract unchanged:** the conservative unknown-total policy, which allows only the same owner, the same revision and the same or a lower commitment, keeps the full old hold, and blocks new revisions, money, replacements, diagnosis and extensions until the total is known. Stale A→B→A refuses. The non-blocking FIFO is kept. No text still describes a separate settlement-only mode; the only mention is the explicit denial at interfaces line 365.
- **Test plan** in `batch-service.md` covers: the J→J-r1→J-r2 chain, deterministic IDs and distinct owners, once per parent across generation and extension replays, the actual-work eligibility cases, FIFO and bypass, a settlement resume ahead of a blocked replacement, the known-settlement ACK without waiting for diagnosis, same-owner diagnosis and extension, and money/deadline refusal.
- **Gating** is stated in both designs and the report: the D adapter and the derived/diagnosis integration stay disabled, and the D API names are left for D to supply (none are invented). The report claims no enablement, no Murphy closure and no exam case. The report's review references (design-6, diff-4, diff-5 copied to interfaces-design-12) match the files in `docs/reviews/`.
- **Codex probe report:** read-only, returns booleans only, and claims only that the prerequisites exist. No overclaim.
- Historical reviews were not rewritten.

Save as `docs/reviews/batch-service-diff-6.md` and `docs/reviews/interfaces-design-13.md`. The concrete proof formats for the whole of 2b still need review before coding starts.

---

Elephant response: PASS accepted; both readiness Majors and all nits addressed in text before2b coding. Named the holder policy_load root-count cap and all direct derived-job lookup sites. Chose worker-driven checkpoint/exit after settling an unknown-at-launch exhausted owner, followed by collection/ACK and an ordinary same-owner diagnosis relaunch. No new mode/config fields. Clarified unknown-vs-known queue classes, canonical derivation and reserved suffix, future exact replacement-policy validation, and report wording. Concrete2b proof/API addendum still required before coding. Full suite138scripts0failures; no code changes since that run. No rejected findings or Murphy closures.

