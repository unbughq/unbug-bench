**FAIL: 1 blocker, 1 major, 4 nits.**

I reviewed revision 2 of `docs/designs/worker-router-delivery.md` against the source at 28b18d0 in t3-ded79ec5 (files are cited at that commit). I used zoom_out, design_critic and implementation_readiness, with the Heilmeier and implementation-readiness standards and `docs/ENGINEERING.md`. I made no edits, network calls, provider calls or delegations, and read no secrets.

### Review 1 findings: all 12 resolved in the text
- **#1 `--dry-run`:** dropped. The exam now runs a normal holder-dispatched batch, and `provider_preflight` reaches `_rpc('acquire')` (`run.py:3390` → `model_router.py:636`).
- **#2 router double and end state:** decided. It uses the real `Server`/`Store` with `enable_tls`. The design correctly drops batch/job columns that don't exist: `acquire` stores only id/model/accounts/role/deadline (`model_router.py:329`). Checking the deadline in the `requests` row is feasible.
- **#3 ssh/exec double:** the design now asks for full `/dev/shm`, `/home/user` and `/usr/local/bin` mapping, `--bench-workers 1`, and deletion-mutation checks. Blocker 1 below shows that mapping shell text is not enough.
- **#4 where the pack goes:** placed exactly after the selection command (`launch.sh:321–324`) and before the for-need loop (`:325`). `held_secrets_b64` is left unchanged, the pack runs on fresh launches only, and resumed workers read their existing RAM files. This matches the source.
- **#5 token in model CLI env:** the filter sits after the merge at `model_runtime.py:567`, and both the gated and ungated paths are tested.
- **#6 token copied by hand:** a non-admitting `/status` probe runs before `guard_init`. This works: `status` is a read-only RPC (`model_router.py:308`), and `{}` passes the `0 < size` check. One deployment operation writes both RAM files.
- **#7–#12:** the redirect class is reused; trust is `create_default_context` plus `load_verify_locations`, with `ProxyHandler({})`; `router.url` is superseded; `TRUSTED_FILES` and the fingerprint rebuild are covered; Murphy row 28 is dropped and the problem statement added; `paid_reserve`/`paid_settle` are named.

### Blocker
**1. The end-to-end exam cannot reach its stated end state, and its "never touch developer /dev/shm" promise cannot hold.** Scope: item 6, and "Input audit and end-to-end exam" lines 89–107.
- The design maps paths by rewriting the shell command text. But the worker's Python code hardcodes the RAM directory, and no command rewrite reaches these:
  - `model_router.py:33` (`SECRETS`), read by `_credential_ready` at `:549`;
  - `job_config.py:188` (where `deliver` writes);
  - `account_handoff.py:24`;
  - `run.py:30` (`STATEMENTS_KEY`).
- What happens in practice: the first preflight lease is `opencode/minimax-m3.1-flash-free` on account `opencode-go-key`. `_credential_ready` then reads the real `/dev/shm/secrets/opencode-go-key`.
  - On macOS that file doesn't exist. The lease is denied as `credential_expiring` (`:639–642`) and the run ends as `ProviderWait`, not `provider_preflight_failed`.
  - On a Linux developer box it reads the developer's real RAM secrets.
- Item 6 also says only `sudo loginctl` may short-circuit. But the real `job_config.py deliver` would then write to the real `/dev/shm`, or fail on macOS.
- Fixing this needs a decision the design hasn't made. Two options:
  - **(a)** One worker RAM-directory seam that all four modules share. This touches production code and the holder fingerprint.
  - **(b)** Name the allowed edges explicitly: keep the existing redirect that runs the real `job_config.deliver` into a mapped path, accept the credential-wait end state, and drop the "never touch developer /dev/shm" claim for the parts that are not mapped.

  I lean towards (a): a single constant is less to maintain than a list of exceptions.

### Major
**2. The Claude CLI double has no stated location, and a miss falls through to a real network install.** Scope: lines 91–94 and item 6.
- Rotation slot 1 picks `claude/claude-opus-5-5` as the writer. So `verify_selected_drivers` calls `pinned_cli('claude')`.
- The worker command doesn't set `FACTORY_CLAUDE_BIN`, so `pinned_cli` looks at `/tmp/factory-claude-cli/bin/claude` (`model_runtime.py:34`, `:234`). If nothing is there, it runs `npm install -g` (`:236`), which is a real network call.
- `/tmp/factory-*.json` (`:168`) also writes into the shared host `/tmp`.
- **Fix:**
  - Have the exec double's environment set `FACTORY_CLAUDE_BIN` to the Claude double, as a cloud-image edge.
  - Put fail-closed PATH doubles for `npm`, `sudo` (apart from `loginctl`), `apt-get` and `curl` in the test.
  - Require real `age` on the test host; otherwise `run.py:3371` runs `sudo apt-get`.

### Nits
3. **Resumed workers with no router files don't fail loudly.** On a resume, `export FACTORY_ROUTER_TOKEN=$(cat missing)` exits 0 under `sh -c "set -eu"`. The worker then gets an empty token, which leads to `router_unavailable` and then `ProviderWait`, not a refusal. Either say that this is the accepted failure, or add `test -s` before the three exports.
4. **Item 4 doesn't say where `batch_holder.dispatch` gets the `UNBUG_ROUTER_CLIENT_FILE` value.** The options are the holder's own environment or the default path. State "pass it through only if set in the holder environment, otherwise the helper default."
5. **Item 2 says "append the three names to vm_creds" for resumes.** In the source, `vm_creds` is built by looping over `$secrets`. Say "append them to `$secrets` without the pack, the probe or the need-check."
6. **Heilmeier gaps:** the timeline ("one offline implementation cycle") and the Impact line are thin. They are acceptable for an offline increment.

### Scope and security honesty
- Accurate: same-user readability of `/dev/shm/secrets`, a batch-wide shared token, no persistence across a control-VM reboot, and the narrow claim on row 51.
- New Murphy row stays open: correct.
- No live action is claimed.

### Three lines for the parent (final round)
1. Blocker: the worker's Python code hardcodes `/dev/shm/secrets` (`model_router.py:33,549`, `job_config.py:188`, `account_handoff.py:24`, `run.py:30`), and shell-text mapping can't redirect it. So the exam ends in a credential wait, not `provider_preflight_failed`, and on Linux it reads the developer's real secrets.
2. Parent decides: (a) one shared worker RAM-directory seam in production code (my lean), or (b) named edge exceptions with a revised end state and a narrower safety claim.
3. Also fold in major 2 (`FACTORY_CLAUDE_BIN` in the exec double, plus fail-closed `npm`/`sudo`/`apt-get`/`curl` doubles); everything else in revision 2 is resolved.

## Writer disposition

Accepted findings; stopped after design round 2 as instructed. No third design
review, implementation, worker or live action. Parent decision required on the
shared worker RAM-directory seam versus explicit edge exceptions. Major 2 and
nits 3–5 are accepted for the eventual revision; no fix is claimed yet.

## Parent-approved after round 2 — implementation disposition

The parent selected option (a): one shared worker RAM-directory constant, default
unchanged, and one offline override. Implemented in worker_secrets.py and all four
consumers. Major 2 and nits 3–5 are implemented: explicit Claude executable,
fail-closed install edges, private TMPDIR, real-age prerequisite, missing resume
files refuse, conditional host client-path forwarding and resume name appending.
The brief Heilmeier text remains. No third design review and no live action.
Fresh diff review must verify these fixes; this disposition is not self-approval.
