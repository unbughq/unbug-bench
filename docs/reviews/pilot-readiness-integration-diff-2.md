PASS — no blocking findings in correction `8a5c38f`.

Activation, validation, `_admit`, legacy authorization refusal and cleanup now share the exact `money.PILOT_BATCH == 'b-real-pilot'` contract. The regression exercises authenticated activation plus real reserve, rejects an invalid role in another template, and checks that no authority/journal files appear.

Fixture updates preserve role, replay and state-immutability assertions. Earlier shape rejection correctly changes three expected error labels. The preflight doubles leave both cleanup checks, pending-state assertions and eventual same-operation dispatch exercised.

Nit: `docs/designs/pilot-admission-cleanup.md` still says “must begin” and “reserved ID prefix.” Both should describe exact-ID matching.

B2 retained-release evidence remains open. This review grants no waiver, live qualification or Murphy closure. No edits, tests, Docker, network, secrets or delegation used.

## Parent disposition

PASS accepted; wording nit fixed to exact-ID matching. Frozen deployment package and saved-pin replay are a separate evidence audit. No activation or policy decision follows.
