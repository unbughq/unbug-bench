# Worker router delivery — offline increment

Make a launched batch worker reach the existing shared router with normal TLS
verification, without exposing its token. Prove the real launch command delivers
its required inputs before another live attempt. Cost: $0 cloud/model; one offline
implementation cycle. No live action, repin, or practice restart in this increment.
Base factory-simplify is merged (already contained at start); source 3a50896.
Today no FACTORY_ROUTER_* reaches workers, so the first factory model call fails
with router unconfigured. The old test hid this by dropping vm_creds and discarding
the push-secrets tar. Revision 2 addresses design review 1 in full.

## Changes and deletions

1. Add factory/router_delivery.py, a small host credential-pack helper. Its input
   is the existing decrypted credential tar on stdin and a host RAM configuration
   at /run/unbug-bench/router-client.json. Deployment creates that file in RAM only,
   mode 0600, using the SAME URL/token as the single shared router service; no new
   router, ledger or per-batch spending allowance. At live step 2, one deployment
   operation generates the shared token once in process memory, writes router.env
   and router-client.json together under RAM-backed /run/unbug-bench (root owns
   service env, launcher user owns client JSON), and starts/restarts the router
   before clients. It loads OpenRouter credentials in RAM from the existing bundle;
   no token crosses the Mac or appears in shell argv. These volatile files are
   recreated by that explicit deployment operation after a control-VM reboot;
   this patch adds no credential persistence or reboot supervisor.
   UNBUG_ROUTER_CLIENT_FILE can
   select another file (public synthetic test fixtures); only the path is retained
   across control_resume. Never write the token on the Mac or into launch state.
   Exact JSON keys: schema:1, url, token, ca_pem. Reject duplicates, nonregular or
   linked file, wrong owner/mode, oversized input, empty/control-character token,
   non-HTTPS URL, userinfo/query/fragment, invalid CA certificate. No diagnostic
   may include file contents, provider output or exception text.
2. Only for batch_release and UNBUG_RESUME_LAUNCH != 1, pack the already-selected
   tar immediately after launch.sh's selection/filter command (currently line 324),
   before its required-secret loop and before guard_init/new. Leave
   held_secrets_b64, held_secret_labels and codex_login_gate inputs unchanged.
   Append factory-router-url, factory-router-token and factory-router-ca.pem to
   $secrets AFTER applying FACTORY_SECRETS. Require all three in the for-need loop;
   add exactly three cases to the vm_creds case statement. Reject a conflicting
   tar member; never overwrite one. Preserve one selected Claude label per worker
   and no exam token. Existing bin/push-secrets delivers to worker RAM, 0700/0600.
   The helper also makes one authenticated POST /status with {} over verified TLS
   (5-second timeout, bounded response, no proxy or redirects) before packing.
   Require HTTP 200 and valid status response; discard it. This admits no lease or
   paid request. A bad token, CA, hostname, unreachable endpoint or redirect refuses
   before guard_init and before a VM exists. Error output is a fixed label only.
   On UNBUG_RESUME_LAUNCH=1 do not read/pack/probe host client config: no secret push
   occurs and the existing worker reuses its RAM files. Still append the three
   router names to vm_creds for batch resumes so missing worker RAM fails safely.
3. The existing vm_creds prefix exports FACTORY_ROUTER_URL and
   FACTORY_ROUTER_TOKEN by reading those RAM files on the worker, not interpolating
   their contents into a host command or argv. Export FACTORY_ROUTER_CA_FILE as the
   public RAM CA-file path. Apply the same prefix to fresh and resumed workers.
   Do not export a global SSL_CERT_FILE: that would change Anthropic/OpenRouter
   trust. model_router._rpc creates its normal default SSL context, optionally
   adds FACTORY_ROUTER_CA_FILE, and uses it for this router call only. Hostname
   verification and certificate verification stay enabled. Existing environment
   clients without a private CA keep default trust. Reject redirects for router
   RPC so its bearer token cannot be forwarded to a different endpoint. Rename
   and reuse _NoCreditRedirect; use ProxyHandler({}), HTTPSHandler with
   ssl.create_default_context() then load_verify_locations(cafile=...) on worker
   or cadata=ca_pem on host. Factor the same request function for _rpc and host
   /status proof; preserve the existing localhost HTTP test allowance for _rpc,
   while production host config strictly requires HTTPS.
4. batch_holder.dispatch must pass only UNBUG_ROUTER_CLIENT_FILE (a path) into
   the sanitized launcher environment; control_resume includes that path in its
   existing persisted allowlist. Neither holds a serialized router token.
   Add router_delivery.py to launch_manifest.TRUSTED_FILES only. Its code runs
   only on host. Rebuild the holder fingerprint in integration fixtures; all
   launch/runtime edits require new parent-approved release pins after merge.
   Supersede batch-service.md's unimplemented router.url manifest field: this
   shared RAM deployment config is the URL source, not a second manifest field.
5. At model_runtime.py's model-process env construction, filter FACTORY_ROUTER_*
   after merging os.environ and c.model_env, so neither caller can leak router
   authority to Claude/OpenCode/Codex subprocesses. Test a CLI sentinel environment
   capture on gated and ungated paths. Files in /dev/shm/secrets remain readable
   by the same Unix user: this preserves the existing proportionate isolation,
   not a claim of adversarial separation from a same-user tool.
6. Add a full-command integration exam without the shortcuts in BOTH ssh and exec: execute every
   received worker command in synthetic HOME, mapping the ENTIRE /dev/shm prefix
   before execution (including bare /dev/shm/secrets), /home/user and hardcoded
   /usr/local/bin/opencode,codex to local doubles. Never touch developer /dev/shm.
   Only sudo loginctl administration may short-circuit. Driver versions and
   worker_release qualification use real validators and edge executables; no
   patched run.py/authority/metadata/transport. Supply --bench-workers 1.

## Input audit and end-to-end exam

Use a normal holder-dispatched batch with NO --dry-run: real launch.sh,
control_resume, qualified release install/verify, push-secrets, job_config and
runner entry, using public retained inputs and synthetic credentials. CLI doubles
for opencode/claude/codex return pinned versions/help and fail actual generation
with a nonzero exit, after recording only safe environment assertions. Docker
and provider network boundaries are local doubles; no real model/VM/network.

Use real model_router.Server/Store, temporary SQLite, and enable_tls with a
throwaway localhost certificate. Capacity permits the first bounded model lease;
on Linux the CLI double exits nonzero. On macOS the Linux-only paid gate
refuses route_feature_unsupported after the real router lease, so provider_preflight ends with
terminal_stop=provider_preflight_failed, then the ordinary seal/collect/deletion
path runs. This is a delivered-but-failed provider exam, not a case pass. The
router requests/lease row must exist and carry the manifest deadline; the actual
acquire schema has NO batch/job fields, so do not invent such columns. Assert
batch/job in authenticated config and final job_money/receipt bindings, and cover
model_router.metadata with the real installed config in a focused consumer test.
The Linux model double asserts no FACTORY_ROUTER_* token was inherited;
focused gated/ungated process-boundary tests cover this on macOS too. The old
public interruption/money-contract exam retains its explicitly narrower runner
double and is not cited as delivery evidence. Runtime can
retry within its existing bound; all retries remain synthetic and bounded by the
outer test timeout. No production token, home, account or cloud endpoint is used.

Wrong CA, wrong hostname, wrong token and redirect are focused request tests;
real Server/Store handles successful authenticated requests. A minimal redirect
HTTP edge tests rejection. Exercise paid_reserve/paid_settle through the same
TLS client with synthetic ledger input/credit-reader edge, with no upstream call.
Deletion mutation checks must kill pack omission, push member omission, vm_creds
export omission and CA-load omission. No monkeypatch of authority or runner.

| Input | Actual producer/consumer and assertion |
|---|---|
| Router URL/token/CA | host pack → real push-secrets → vm_creds → real _rpc to local HTTPS Server/Store; authenticated request succeeds; wrong CA/hostname fails; sentinel token absent from host logs/state/argv and public artifacts |
| Batch/job/deadline | authenticated factory-job.json → job_config.install → case attributes → model_router.metadata; equal manifest, not copied environment. FACTORY_BATCH_ID/JOB_ID/DEADLINE are fallback inputs, unnecessary with authenticated attributes; forged environment cannot override them |
| Job money/release/case/generation | existing holder config SHA, qualified source and verified_config; refuse changed config before model admission |
| Claude/OpenCode/OpenRouter/Codex | real archive selection and worker environment; only selected Claude token, no exam token, codex auth JSON and login expiry check retained |
| R2 | host r2-env parsed for collect/publication; absent on worker; presigned-object transport edge only. Check publication replay's existing _r2_env path too |
| Case secrecy/sealing | founder identity stays host; worker gets scoped case key only on restore; existing recipients and registry/collection inputs preserved |
| Runtime | PATH/HOME, CLI paths, account state, run/grace limits, config path/hash and installed public files reach actual worker entry |

Keep an explicit audit table in docs/reports/worker-router-delivery.md with
observed checks and remaining limitations. Any further same-kind missing input
found by this exam is fixed here; a policy/architecture change outside delivery
returns to the parent rather than being hidden in a test double.

Unit exams: valid pack; missing/malformed config refuses before Boat creation;
duplicate/conflicting names refuse; secret never in error output; path survives
restart without contents; fresh/resume exports; real TLS success and wrong
CA/hostname/redirect failures. Test token values are public sentinels only.
Focused tests in tests/factory/test_router_delivery.py and the real-launch
integration test. Full canonical suite with unique log and source-bound record.

## Review and risks

At most two fresh design reviews and two fresh diff reviews; Claude opus-5-5,
one retry only for a network failure. After round 2 any blocker returns in three
lines. Save every review verbatim. No self-verification of review blockers.
Risk: an edge double that discards shell exports would recreate the evidence gap;
the end-to-end test must fail when delivery/export/TLS loading is removed.
Risk: deployment must keep host RAM client config and router service token/CA in
sync; malformed/missing config refuses before creation, not after spending.

Murphy rows touched: 51 (restart), and new-worker-router-delivery-1
for the missing router transport observed during offline practice preparation.
Add the new row as open; no rows close from synthetic transport evidence.
No live worker failure is claimed. Founder approval covers this offline change;
parent merges, then authorizes repin/resume separately.

## Parent-approved after round 2

Use one worker RAM-secrets constant in factory/worker_secrets.py, default
/dev/shm/secrets, with UNBUG_TEST_WORKER_SECRETS as the single offline-exam
override. Import it in model_router, job_config, account_handoff and run; audit
other worker readers too. No override is propagated by production dispatch.
The exam uses its own TMPDIR and explicit FACTORY_CLAUDE_BIN. Real age is required
(skip loudly if unavailable). npm, apt-get, curl and sudo except loginctl are
fail-closed edge doubles. No shared host /tmp or real /dev/shm is touched.
Before router exports, test -s on all three worker files, including resumes.
Dispatch passes UNBUG_ROUTER_CLIENT_FILE only if set, otherwise helper default.
Append names to $secrets on resume without packing/probing/need-checking host
client config. No third design review; implementation and at most two diff rounds.

Implementation audit: the legacy key_holder.serve batch dispatch also builds a
sanitized environment. It now passes the optional client path by the same rule.
The CLI cloud-image edge maps hardcoded executable paths only; its Python audit
hook refuses real /dev/shm or shared /tmp/factory accesses. TMPDIR isolates runtime
CLI/config scratch paths. The synthetic R2 credentials exercise host parsing only,
not actual publication authentication.

The gate-smoke preallocation source list must also include worker_secrets.py,
since account_handoff imports it. Historical evidence schemas come from their
retained producer, not the evolving control_resume environment allowlist.
