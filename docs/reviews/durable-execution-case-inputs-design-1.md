# Case-input scope design review 1

Fresh read-only goldfish, zoom_out, design_critic and implementation_readiness
personas, Mode: REVIEW. Verbatim response:

---

**FAIL — design review.** The store-scope conflict is real, but the proposed copy has not been shown necessary, changes a confidentiality boundary, and leaves rollout and verification decisions unresolved.

**Blockers**

1. **The design has not established that later steps need a case-scoped copy.** [The proposal](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-case-inputs.md:10) assumes every step needs the batch bytes. In `de/wp5a:factory/durable/worker_step.py:449–484`, non-ADMIT steps ignore `inputs`; `de/wp5a:factory/run.py:3300–3343` reconstructs their settings from the restored case snapshot. The WP5a design explicitly records that choice at `de/wp5a:docs/designs/durable-execution-wp5a.md:284–290`.

   A smaller candidate is to retain the original batch `INPUTS` ref in every `StepInput`, fetch its ciphertext using `scope_for`, remove the rescoping step, and continue sending the batch key only to ADMIT. This preserves the v5 record and original-input provenance while letting the snapshot remain authoritative for derived case settings. Update the WP1 fake worker, which currently assumes every input must decrypt, to match the real worker. If a present consumer actually needs the raw batch bytes, name it and explain why the snapshot is insufficient before adding `CASE_INPUTS`.

2. **The proposed copy changes a security property and needs a founder decision if retained.** [The proposal](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-case-inputs.md:25) makes the complete original batch payload decryptable by every later worker using its case key. Cryptographic separation between the batch key and case keys still holds, but the original payload’s readership expands beyond ADMIT; it contains the batch promise, app pin, and rotation, rather than only the admitted case’s derived settings. The proposal also opens that payload in control-side memory, whereas the approved [durable execution design](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution.md:317) says case content is opened in worker RAM. WP3 explicitly classifies inputs as case content at [its design note](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-wp3.md:7).

   The assertion that secrecy does not change at proposal line 39 is therefore too broad. Either retain the existing boundary or state the expanded disclosure and control-side plaintext handling as a security-property change for the founder to settle, as required by [ENGINEERING.md](/private/tmp/unbug-durable-execution-review-20261105/docs/ENGINEERING.md:7). If the copy remains, specify that it is the original batch payload, that the case snapshot remains authoritative for admitted and derived settings, and how any future consumer handles a disagreement.

3. **The v6 rollout does not actually detect incompatible databases or worker bundles.** [The migration paragraph](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-case-inputs.md:39) says to stop if a real v5 engine database is found. `CONTRACT_VERSION` is only a constant in [contract.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/contract.py:24): it is not present in serialized records, frames, or the worker release manifest. [Engine.launch](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:639) calls `DBOS.launch()` before inspecting recovered workflows, while the engine application version remains pinned. A v5 worker also rejects `case_inputs` during strict input parsing before its release-version check; WP2 treats the failed start as a transport problem, not as a negotiated contract mismatch.

   Specify an enforceable clean-database precondition and how it is checked **before** recovery starts, without deleting a discovered real database. Also specify how release creation and launch ensure that the control side and worker bundle both contain v6; do not rely on the constant alone. Include a test for rejecting or preventing an incompatible worker release and a check that an unknown or v5 database is not recovered under v6.

4. **The verification plan does not prove the stated secrecy and replay properties.** [Verification items 2–4](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-case-inputs.md:58) exercise cryptography and an executor frame, but do not require:
   - asserting that each opened copy is byte-for-byte equal to the original source payload;
   - a real DBOS replay across a crash after the immutable store write but before the rescoping step’s result is recorded, proving the same ref is recovered;
   - injected key, sealer, and store failures containing a harmless secret canary, with assertions that the DBOS record, exception chain, and captured logs do not contain it;
   - a real WP5a worker execution with the v6 record and the intended snapshot behavior, rather than only parsing the record.

   If the copy remains, add those checks using a public saved input artifact and the real WP3 store and sealer. Keep plaintext handling inside the recorded step and preserve WP1’s fixed-code, context-free exception wrapping around the composed `open_from` and `seal_into` calls.

**Major findings**

- **The wire boundary does not enforce the claimed key set.** [start_frame](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/contract.py:496) and `de/wp5a:factory/durable/worker_step.py:295–313` both allow a batch key on a non-ADMIT frame. The current executor happens to omit it, but the contract and receiver accept it. If the proposal’s key boundary is retained, require exactly the case and batch keys for ADMIT and exactly the case key otherwise, and test both producer and receiver.

- **Cross-package fixtures need explicit updates.** WP1’s fake worker special-cases the invalid scope in [test_durable_engine_fakes.py](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_engine_fakes.py:348). The WP2 and WP5a test constructors still use `INPUTS` for non-ADMIT (`de/wp2:tests/factory/test_durable_channel.py:60–72`; `de/wp5a:tests/factory/test_durable_worker_step.py:251–255`). A parser recheck alone does not identify these required fixture changes or establish that the combined packages work with the chosen contract.

- **Separate existing integration obligation:** WP3 says worker output refs should be opened under their proper scope before the engine records them ([WP3 design](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-wp3.md:76)). The current executor only checks existence at [executor.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/executor.py:142), and `de/wp2:factory/durable/channel.py:121–133` checks transfer integrity but does not decrypt. This is not introduced by the case-input proposal, but it remains a cross-package gap and should not be counted as proven by these tests.

**Nit**

“The real store must reject each wrong scope” should distinguish a batch-versus-case scope mismatch from a *different valid case ID*. [check_scope](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/artifacts.py:197) checks the kind’s scope category, not which case owns a ref. A cross-case test should verify that the other case key cannot open the ciphertext; it should not expect the store to infer ownership from the ref.

The Murphy rows are correctly described as targets rather than closed. No tests were run; this was a read-only design review.

---

## Resolution

| Finding | Disposition |
|---|---|
| Blockers 1–4 and proposal-specific major findings | Proposal rejected. No contract change or new artifact kind will be made. |
| Existing output-authentication obligation | Accepted for the WP1 fix and verification. |
| WP11 snapshot requirement | Carry forward to WP5a/WP11 integration. |
