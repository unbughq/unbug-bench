Mode: REVIEW. Scope: B8 and M3 money-policy adjudication only. No files changed or saved.

**B8 — Agree with the proposed rejection. Drop the blocker.**

Affected scope: `docs/designs/interfaces.md:295–319`; `docs/designs/stream-d.md:59–77,348–360`.

ENGINEERING §3 requires factory-bug costs to appear on the infra-waste line. It does not require a separate waste cap or exclude that money from cumulative batch authority. ENGINEERING §4’s capacity rule does not establish a financial exemption for infrastructure failures.

D explicitly separates ordinary case spend from cumulative consumption: reclassification reduces ordinary `spent_usd`, increases `infrastructure_waste_usd`, and leaves `total_spent_usd` unchanged. The ordinary $50 diagnosis threshold uses ordinary spend; the job commitment bounds total consumption, including waste. The job is the money owner within the batch, not a separate scientific allowance.

Consequently, including waste in cumulative job authority does not itself charge waste against the ordinary diagnosis threshold. A case can exhaust authorized batch money without being judged scientifically defective. Infrastructure exhaustion must remain an unscored operational outcome.

The proposed clarification is appropriate. Preserve separate reporting and ordinary-threshold treatment while retaining waste in cumulative authority. No `infra_waste_limit_usd` is required by the cited rules.

The accounting invariant is concrete: with commitment $13 and total $12 comprising $8 ordinary spend plus $4 waste, $1 remains authorized. Reclassification must not make $5 available. B8’s proposed exclusion would require another reservation mechanism to preserve this invariant, without a demonstrated requirement for that added mechanism.

**M3 — Accept the proposed ownership/policy clarification, but retain the original priority ambiguity as a Major until clarified.**

Affected scope: `docs/designs/interfaces.md:280–305`; `docs/designs/stream-d.md:36–43`; `docs/ENGINEERING.md:110–118`.

The original reviewer correctly identifies an ambiguity: an extension or diagnosis of an existing case must not create a second money owner. Attach the scheduling priority to the admission/revision request, or explicitly define how the existing owner’s request carries that priority. Preserve the same job and reservation identity across stages.

The recommendation to require B to implement `requested_total_usd = previous + 15` is too prescriptive. Cumulative authority and an extension allowance are different constraints. Increasing an existing commitment by $15 does not, by itself, enforce a $15 allowance for one extension, particularly when unused authority already exists.

However, ENGINEERING’s $15 allowance remains governing policy. D’s explicit proposal to remove it is a proposed amendment, not an already-effective replacement. B’s cumulative authority must neither grant extension eligibility nor implicitly waive the allowance. Until the amendment is adopted, D must enforce the active allowance alongside the extension count, package, diagnosis and progress requirements. After adoption, D may enforce the amended policy.

Thus, agree with rejecting B-specific automatic $15 commitment increments; disagree with any interpretation that the current allowance can already be ignored. The proposed fix resolves this distinction if it states the policy transition explicitly.

These conclusions adjudicate only B8 and M3; they do not approve the remaining design.
