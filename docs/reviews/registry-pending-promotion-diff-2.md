**PASS — no blocking findings in the final code/test delta.** Reviewed `dd81ff8..271f4a87`, concentrating on changes after the original diff review.

- **M1 satisfied:** the new test drives `statement_round.prepare` through two waves using a copied retained registry, real ciphertext and an authored public digest card. Both candidates receive complete, mutually visible snapshots.
- **M3 satisfied:** promotion supplies different retained ciphertext bytes with the same declared statement digest and asserts the original ciphertext binding survives. I independently confirmed those ciphertext files differ. This tests the trusted digest contract without claiming plaintext equivalence.
- **N3/N4 safe:** promotion refuses a missing stored object before committing state, and only promotes `completed`, incomplete historical entries. Existing locking and predecessor recomputation remain intact.
- Focused verification: `BENCH=<checkout> python3 -B tests/factory/test_registry_promotion.py` — **6 tests passed**. No full suite, network calls or decryption performed.

**Row-status recommendation:** row 7 may close for its stated same-candidate historical-promotion failure, citing this test file. The retained-artifact regression meets ENGINEERING’s closure bar; live deployment proof is not required.

At merge, explicitly preserve `new-registry-pending-promotion-1` as an **open register row**, describing stale history after candidate reselection. Cross-reference it from row 7 and clarify that pending history imports remain intentional. Closing row 7 must not imply that different-content stale-history recovery is finished.

## Parent disposition

Accepted; no findings rejected. The integration candidate records the original
row7 closure with the retained-artifact prepare/ciphertext tests and separately
records the unfinished stale-history/reselection case as open. This is not a
main-branch closure or deployment until combined integration validation and merge.
