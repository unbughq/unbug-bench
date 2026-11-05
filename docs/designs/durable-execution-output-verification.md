# Preserve received results across verification outages

Status: revision 2 after design review 1; fresh verification pending. WP1; no
`contract.py` change.

## Problem

A worker can finish and its encrypted output can reach the artifact store, then
the control process can die while output authentication is temporarily
unavailable. The current DBOS step has not returned, so its DONE result is not
in the journal. If the worker is later gone, recovery can repeat completed work.

## Change

Split the current attempt step into two recorded steps. The first receives and
strictly parses a contract-shaped `StepResult`, including only codes, usage and
encrypted artifact references, and records it as **provisional**. It does not
change the registry, public outcome, case snapshot or ledger. The second step
authenticates every output with `open_from` and `scope_for` before returning the
result to the workflow. Only that verified result can update state or settle the
attempt. A replay reuses the recorded provisional result and does not contact or
restart its worker just to recover it.

`guarded_run` and exact-lease reconciliation remain the only worker-execution
paths. A malformed result or an unknown dispatch is reconciled against the exact
worker before any new attempt. An unverified result cannot authorize publication
or a new model call. If a worker is confirmed lost, retain its lost-usage outcome
while verifying any provisional checkpoint: a missing or invalid checkpoint is
dropped, but the original lost outcome must still settle the held grant as lost.

Transient storage, key-service and age errors retry the same verification. An
`open_failed` age exit alone is ambiguous and cannot establish corrupt ciphertext.
A malformed age header or a digest mismatch is conclusive; reject it. A local
`stat` I/O failure is not proof of absence. A sustained verification outage holds
the grant and the model slot; this change does not claim automatic progress while
the store, key service or decryptor remains unavailable. For a conclusively
missing or invalid DONE output, construct a fixed `INFRA_ERROR` with every
output ref removed and the original parsed usage retained; settle that actual
usage once as batch waste. Unknown-usage outcomes still use lost settlement.

Both recorded steps contain their exception boundaries: arbitrary exceptions
and their context never reach the journal or logs. A malformed result is
reconciled on the exact original lease; it is not accepted or used to release
the grant. Unknown or transient verification errors keep the grant held and
retry the same verification rather than authorize another model call.

This replaces the monolithic receive-and-verify step rather than adding a separate
recovery store. Earlier unpublished WP1 journals remain unsupported; the WP8
fresh-generation database gate and future compatible `DBOS.patch` rule remain.

## Tests and Murphy rows

- On real DBOS with disposable SQLite and fake workers, block authentication
  after a DONE result is recorded, kill the controller, mark the worker dead,
  restore authentication, and prove the original result and usage are accepted
  with exactly one worker start. Prove no unverified result was applied.
- A killed age decrypt followed by a successful decrypt does not rerun the worker;
  conclusively malformed or digest-mismatched output is rejected.
- A real local store distinguishes a missing file from a transient stat EIO.
- Missing or invalid DONE outputs with nonzero usage yield a ref-free infra
  result, book actual usage as waste exactly once across crash/replay, and do
  not apply the invalid reference.
- A lost worker with an invalid checkpoint still uses lost settlement.
- Inject private sentinel text through a malformed result and a verifier
  exception. Inspect the DBOS journal and logs for the sentinel; the grant stays
  held pending safe reconciliation or verification.

Targets Murphy rows 5, 18 and 51; closes none without the real final exam.
