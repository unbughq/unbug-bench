# Output verification design review 1

Fresh read-only goldfish; zoom_out, design_critic and implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — two blockers in the proposed boundary.**

1. **Settlement after a bad DONE output is unspecified.** Lines 17–19 permit settlement only after verification, while lines 30–32 say to reject invalid ciphertext without defining the resulting settlement. For a completed result with nonzero usage, require a fixed `INFRA_ERROR` with all output references removed and the original parsed usage retained; settle that usage as batch waste. Reserve lost settlement for outcomes whose usage is unknown. Test missing and invalid DONE outputs with nonzero usage across crash and replay, asserting no reference is applied and settlement occurs exactly once.

2. **The new recorded steps need an explicit exception boundary.** `guarded_run` protects executor execution, but the separate verifier can receive exceptions containing private data from the key service, store, or sealer. Contract parsing can also echo a malformed enum value in an exception. Require both steps to prevent exception messages and chained context from reaching DBOS or logs; malformed results must undergo exact-lease reconciliation, and transient or unknown verification failures must retain the grant and retry verification. Test both paths with private sentinel text and inspect the journal and logs.

---

## Resolution

| Finding | Disposition |
|---|---|
| Invalid DONE usage | Revision 2 specifies a ref-free fixed infra result, actual usage settled as waste once, and crash/replay tests. Fresh verification pending. |
| Exception containment | Revision 2 specifies caught errors, exact-lease reconciliation and held-grant verification retries, plus sentinel tests. Fresh verification pending. |
