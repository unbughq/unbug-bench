**Verdict: does not pass round 1.** There is 1 blocker and 5 majors. All of them can be fixed in the design text. I agree with the overall approach: a RAM pack on the host, the existing `push-secrets`, the worker reading the token from its own RAM, a TLS context scoped to the router, and `job_config` staying authoritative. I checked one gap and it is real: nothing exports `FACTORY_ROUTER_URL`/`TOKEN` today (`factory/model_router.py:486` is the only reader). So every model call in a factory job fails with "router unconfigured".

---

## design_critic / implementation_readiness

**1. Blocker: `--dry-run` never reaches the router.** Scope: "Input audit and end-to-end exam", lines 52–55, and table rows 65–66.
- In `run.py --dry-run`, `factory/run.py:3382` builds the fixture and skips `pick_models`, `provider_preflight` and `build`. The help text at `run.py:3206` says "no model calls".
- Because of that, `model_router.await_lease`, `_rpc` and `metadata()` never run. The design's headline evidence ("real _rpc to local HTTPS stub; authenticated request succeeds", and metadata reaching `model_router.metadata`) cannot be produced this way.
- `--dry-run` also skips a real input path: at `launch.sh:370` it skips the statements-key/selection-board export. So the input audit would quietly cover less.
- **Smallest fix:** run a normal holder-dispatched batch job, with no `--dry-run`. The first router call is `provider_preflight` → `run.opencode` → `model_runtime.py:364` `await_lease` → `_rpc('acquire')`.
  - Edge doubles: `opencode`, `claude` and `codex` executables on PATH (or at `FACTORY_*_BIN`) that print the pinned versions, so the real `worker_release.verify_driver` and `pinned_cli` pass. Also doubles for `docker`/`docker compose`.
  - Do not patch `run.py`.

**2. Major: the router double and the stop point are not decided.** Scope: lines 56–60 and 65.
- "Local HTTPS stub" leaves open what it returns. A canned JSON reply would be a fixture the test made itself (ENGINEERING §4, "Real artifacts").
- Nothing says how the real runner ends without a monkeypatch. That breaks the Zero-Decision Rule.
- **Fix:** use the real `model_router.Server` and `Store`: a temporary database, `enable_tls` with a throwaway localhost certificate and CA, and the sentinel token. Name the end state in the design. Either:
  - capacity 0 → `ProviderWait` → a `provider_wait` card; or
  - a granted lease plus a model double that exits non-zero → a named `terminal_stop`.
- Assert the router database row carries the authenticated batch, job and deadline from `factory-job.json`. That is real proof for the metadata row. Wrong CA, wrong hostname and redirect stay as focused `_rpc` unit tests against the same `Server`.

**3. Major: the ssh edge double still throws away credential delivery.** Scope: item 5 (lines 45–48) and line 58.
- Item 5 only redefines `exec`. But today the delivery hop is lost in ssh: `tests/integration/test_batch_launch.py:106` reads and discards the `push-secrets` tar.
- Its path mapping only rewrites `'/dev/shm/secrets/'` with a trailing slash. `push-secrets` uses the bare `/dev/shm/secrets` (`rm -rf … && mkdir`, `cd`). On a Linux developer box, running the real command would wipe the developer's real `/dev/shm/secrets`.
- **Fix:** say the ssh double runs every received command in the synthetic HOME, with the whole `/dev/shm` prefix mapped. Allow only these short-circuits:
  - `sudo loginctl` (worker administration);
  - worker-release qualification, if it stays an edge.
- The exec double must also map `/home/user` and `/usr/local/bin/{opencode,codex}` (hardcoded at `launch.sh:626` and `:774`) to the doubles.
- On macOS, `$(nproc)` in `workers_arg` (`launch.sh:346`) breaks the whole shell. Either put the supported `--bench-workers 1` in the job args or add an `nproc` PATH shim.
- The end-to-end test must fail if any one of these is removed: the pack, the `push-secrets` member, the `vm_creds` export, or the CA load.

**4. Major: where the pack goes in `launch.sh`, and the name checks, are not specified.** Scope: item 2 (lines 22–29).
- "After decrypting credentials" is ambiguous, and the choice matters:
  - If the pack runs at `:141`, it changes `held_secrets_b64` and `held_secret_labels` (`:153–154`, used by `account_handoff` plan/apply at `:569` and `:598`) and the input to `codex_login_gate`.
  - If it runs before `:314`, a persisted `FACTORY_SECRETS` (in `control_resume.ENVIRONMENT`) can silently drop the router names.
  - The `vm_creds` loop exits on any name it doesn't know (`:343`).
  - "Extend its three-name allowlist" doesn't say which list.
- **Fix:** only when `batch_release` is set, pack the already-selected tar immediately after `:324`. Append the three names to `$secrets`, add them to the `for need in …` check at `:325`, and add three `vm_creds` cases at `:335–343`. Leave `held_secrets_b64` unchanged.
- Say that the pack runs on the fresh-launch path only. With `UNBUG_RESUME_LAUNCH=1`, `push-secrets` doesn't run and resumed workers reuse their RAM files through `resume_creds=$vm_creds` (`:596`). A missing client file must not block in-place restarts.

**5. Major: the router bearer token reaches model CLI processes and transcripts.**
- `factory/model_runtime.py:567` builds `env = {**os.environ, …}`. The gated Claude and OpenRouter routes use allowlists (`model_call_gate.py` `ENV_KEYS` / `openrouter_environment`). The OpenCode Go and codex paths only strip some prefixes, so `FACTORY_ROUTER_TOKEN` would sit in the environment of the writer model's tool shell.
- The token is shared by the whole batch. Any holder can `acquire`, `finish` or `paid_settle` other workers' leases. A model that echoes its environment would also put the token into collected transcripts, which the design's sentinel check counts as public artifacts.
- **Fix:** drop `FACTORY_ROUTER_*` from the env built at `model_runtime.py:567` (one filter). In the end-to-end test, assert the model double's recorded environment does not contain the sentinel.
- State in the design that the files under `/dev/shm/secrets` are still readable by the same Unix user. That is the existing, proportionate posture.

**6. Major: the token is copied by hand, and a mismatch is found only after spending.** Scope: lines 13–15 and 92–93.
- `router-client.json` is a second hand-made RAM copy of the token already in `/run/unbug-bench/router.env`. The repo has no producer for either file, and both vanish when the control VM reboots.
- Host validation can't detect a wrong token. A mismatch shows up as a 403 at `provider_preflight`, after `boat new`. The design's own risk line says it must refuse "before creation, not after spending", and the design doesn't deliver that.
- **Fix:** have the pack helper make one authenticated, non-admitting TLS request to the configured URL with the configured CA before `guard_init`. Any non-200 means refuse with no VM created; a 403 for a malformed operation is enough to tell a bad token apart.
- Alternative: read the token straight from `router.env`, but only if the launcher user can read it. `stream-b-practice-blockers.md:76` says it is root-controlled, so the probe is the safer default.
- Name the one deployment step that writes both files together.

## zoom_out

**7. Nit: reuse the existing redirect blocker.** `_NoCreditRedirect` at `model_router.py:178` already blocks redirects. Rename it and reuse it for `_rpc`; don't add a second class.

**8. Nit: say exactly how the TLS context is built.**
- Use `ssl.create_default_context()` and then `load_verify_locations(cafile)`. Passing `cafile=` to `create_default_context` drops the system roots.
- Add `ProxyHandler({})` so an `HTTPS_PROXY` variable on the worker can't route router calls through a proxy.

**9. Nit: settle the earlier router URL field.** `docs/designs/batch-service.md:108` defines `router.url` in the batch manifest. No code implements it. Say this design supersedes it, so there aren't two sources for the URL.

**10. Nit: tighten item 4.**
- The helper goes in `launch_manifest.TRUSTED_FILES` only, not the worker release inventory.
- Editing `launch.sh`, `model_router.py`, `batch_holder.py`, `control_resume.py` and `TRUSTED_FILES` changes the holder `fingerprint` (`batch_holder.py:770`). The repin the parent already deferred is therefore required. The end-to-end test must pin the rebuilt fingerprint.

**11. Nit: Murphy rows and Heilmeier gaps.**
- This change does not touch row 28 (holder inventory bottleneck). Drop it, or say exactly what changes.
- ENGINEERING step 2 asks for "the problem". Add two lines: today no `FACTORY_ROUTER_*` reaches workers, so `_rpc` fails "router unconfigured" on the first factory-job model call; and `test_batch_launch.py:92–106` hid this by dropping the `vm_creds` prefix and discarding the secrets tar.

**12. Nit: what the audit found beyond the design.**
- `job_config.install` (`job_config.py:149–150`) does set `c.batch_id`, `c.job_id` and `c.batch_deadline`, so authenticated metadata already wins in `metadata()` (`model_router.py:505`).
- `model_call_gate.py:551` and `:613` (`paid_reserve`/`paid_settle`) are a second `_rpc` consumer and get the same TLS fix for free. Name them in the table.
- R2: `r2-env` is filtered at `launch.sh:320` and is only used on the host (`:124`, `:155–156`). That matches the table.
- No other worker-side reader of router, batch or R2 inputs turned up.

The validation list for the JSON file looks right for a trust boundary. Keep it, but `schema:1` plus four exact keys is enough; nothing more is needed.

---

I ran no workers, network calls, secrets or model calls, made no edits, and saved nothing. This is the full text for the writer to record as `docs/reviews/worker-router-delivery-design-1.md`.

## Writer disposition

All findings accepted and addressed in revision 2. The router acquire schema
stores a deadline, not batch/job fields: the revised exam checks the database
deadline plus authenticated job-money/receipt bindings and a focused metadata
consumer assertion, rather than claiming nonexistent database fields. No finding
is rejected. No implementation or live action preceded design review.

