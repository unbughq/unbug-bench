# Worker router delivery — offline evidence

The launcher now packs the shared router URL, bearer token and CA into the
existing RAM credential tar. A verified, authenticated `/status` probe refuses
bad host configuration before creation. Worker RPC uses normal TLS validation
plus this CA, without proxies or redirects. Model subprocesses do not inherit
`FACTORY_ROUTER_*`. No real credentials, workers, cloud or model calls were used.

The parent approved the shared worker-secrets constant after design round 2;
there was no round 3. Its default remains `/dev/shm/secrets`. The single override
is for the offline exam and is not passed by production dispatch. Both holder
launch paths pass the optional host client-file path; only that path is persisted.
The host-only packer is excluded from the worker archive. The shared directory
module enters both the host fingerprint and worker qualification inventory.

| Input | Evidence | Limit |
|---|---|---|
| Router URL/token/CA | Real launch.sh selection, push-secrets, entire worker command, real HTTPS Server/Store and SQLite request; unit wrong token/CA/hostname/redirect refusals | Local throwaway certificates and public sentinel only |
| Worker RAM | Four Python consumers share one constant; cloud edge maps all shell RAM paths; Python audit hook rejects real /dev/shm and shared /tmp/factory access | Synthetic VM layout, not live deployment |
| Batch/job/deadline | Authenticated job_config.install and final job_money bindings; router request has manifest deadline; forged environment cannot override installed metadata | Authored batch bindings, no invented router batch/job columns |
| Selected credentials | Supervisor edge asserts Claude account-2 label, OpenCode/OpenRouter env, Codex file, statements key; exam token, account-1 token and R2 absent | Public synthetic credentials; no identity or subscription claim |
| R2 | Real host _r2_env decrypt/parse; excluded from worker archive | No actual R2 authorization or publication request |
| Model processes | Existing gated/ungated process-boundary tests inject router authority in both environment sources and assert it absent from CLI env | Same-user RAM file access remains possible by design |
| Resume | Actual launcher shell prefix with host config absent succeeds using worker RAM; deleting any router file refuses under set -eu | Prefix test, not a live controller restart |
| Paid RPC | Real HTTPS paid_reserve/paid_settle with real SQLite and synthetic credit/usage | No upstream payment or provider usage |
| Runtime/collection | Qualified release and CLI versions, config hash, supervisor, normal runner, collected provider_preflight_failed card, deletion receipt edge | Docker/workload/provider commands are doubles |

The new full-command integration test does not patch run.py, metadata, authority,
credential readiness or router transport. Its socket/SSH/provider/CLI edges run
inside a temporary HOME and TMPDIR. Real age is required; absence is an explicit
skip. Install commands fail closed. On macOS the Linux-only paid gate produces
`route_feature_unsupported` after the real lease, yielding
`provider_preflight_failed`; it does not execute a model CLI. On Linux the exam requires the
nonzero model executable edge; this host did not qualify that platform. Focused process-boundary tests cover filtering on
both platforms. The earlier public interruption test retains its runner double
and is not delivery evidence.

Negative controls remove the pack, token tar member, token export and worker CA
load in copied source only. The evidence JSON records each failed exam. An initial
export mutation accidentally commented out the rest of its shell line and hit
the outer timeout; the separate export record replaces it with a bare colon and
requires failure without timeout. Neither probe changes the working tree source.

The shared module required additions to explicit file-copy fixtures. The launcher
inventory test also verifies that only the shared constant, not the host packer,
is added to the worker archive. No Murphy rows close: row 51 remains qualified
only by its prior evidence; new-worker-router-delivery-1 stays open pending live
qualification.

After parent merge, repin before resuming. The live deployment must write the
router service env and client JSON together in control-VM RAM using one token,
install its certificate/CA, and start the service before launcher admission.
That deployment and the practice run remain stopped until parent authorization.

## First suite and corrections

The first canonical run at 607bf58 completed 174 scripts with two failures; its
record is non-qualifying. The historical-observation test incorrectly compared
its frozen 2026-10-31 fields with today's control_resume allowlist. It now reads
the literal field list from the retained probe using ast.literal_eval, without
executing it or changing any observation. The gate-smoke preallocation path also
needed to hash worker_secrets.py with its existing runtime dependencies; its
source-tampering test caught the omission. That list is now updated.

The final integration checks additionally require a missing host client config
to refuse before billing or creation (the holder still reads its fleet first),
and scan collected public JSON/text
artifacts for the public sentinel. The corrected token-export mutation fails in
19.16 seconds without timeout. Removing worker CA loading reaches the outer
96-second bound (router unavailable); the focused TLS tests independently prove
trust failure. These are offline negative controls, not live cleanup evidence.
