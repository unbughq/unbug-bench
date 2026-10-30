PASS. The merge resolution of `factory/model_runtime.py` keeps every Stream A and Stream D requirement you listed. I found no blockers and no majors, only five nits. I changed no files. Full review below for `docs/reviews/stream-d-merge-a-diff-1.md`.

---

# Goldfish diff review: merge 3e6a367 (Stream A gate isolation into Stream D diagnosis)

**Mode:** REVIEW
**Personas:** `tools/egm/agents/zoom_out.md` (Skeptical Architect) and `tools/egm/agents/implementation_readiness.md` (Implementation Readiness).
**Standards:** `tools/egm/document_standards/zoom-out-standard.md` and `tools/egm/document_standards/implementation-readiness-standard.md`.
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, HEAD `3e6a367`. Parents are `ea2e9cd` (Stream D) and `d0be3c9` (Stream A); their common ancestor is `9701f56`.
**What it was reviewed against:** no new design was written; the merge used the ENGINEERING step-2 small-fix exception. So it is reviewed against its commit message. The existing `docs/designs/stream-d-worker-dispatch.md` is the diagnosis contract, in particular the section on the loopback wall and diagnosis environment (around lines 395–420).

## Verdict: **PASS**

There are no blockers and no majors. The five nits below are optional.

## What I checked

### Combined resolution in `factory/model_runtime.py`
Compared against both parents with `git diff ea2e9cd 3e6a367` and `git diff d0be3c9 3e6a367`.

**Stream A requirements, all present:**
- **`runtime_prices`:** `opencode_config` imports `token_prices.runtime_prices as price`. The old local `PAID_PRICES` helper is gone (lines 152–163).
- **Gate owns the config for `GATED_OPENROUTER` routes:** `OPENCODE_CONFIG` is set only when `model not in GATED_OPENROUTER` (lines 558–559). For gated routes, `model_call_gate.openrouter_environment` writes `OPENCODE_CONFIG_CONTENT` inside `enforce`.
- **Separate config, data and cache directories on every call:** `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_CACHE_HOME` are set under a fresh `mkdtemp` folder for every opencode call. The folder is chowned to the user when there is one. This replaces D's old `XDG_DATA_HOME`-only handling.
- **Per-user gate access:** the call is `enforce(..., user=user)` (line 628). `_wall_access` inserts the UID-owner loopback rule into the `factory-<user>` chain.
- **Per-route usage:** `empty_usage(lease.route)` is kept from A.

**Stream D requirements, all present:**
- **Clean environment:** `diagnosis_environment` runs before driver dispatch. It keeps PATH, LANG and LC_ALL, sets HOME and TMPDIR to the pilot's home, and passes only the one selected transport key. For gated OpenRouter that key is `OPENROUTER_API_KEY` (`lease.account == 'openrouter-key'`, which matches `model_router.py:107`). `enforce` reads that key to build the gate, and `openrouter_environment` does not pass it on to the child, which gets only the gate token.
- **Explicit sudo whitelist:** after `enforce` has replaced `env` in place, the runtime rewrites `cmd[1]` to `'--preserve-env=' + ','.join(env)`. The whitelist is therefore built from the gate's final environment, not the one that existed before the gate. Every variable the gate authors makes it through sudo: `OPENCODE_CONFIG_CONTENT`, `OPENCODE_PURE`, the three `OPENCODE_DISABLE_*` flags, the three XDG directories, HOME and TMPDIR. This is the specific risk named in the brief (the gate replacing the environment after the sudo command is built), and the resolution handles it correctly. `cmd[1]` is always the sudo flag here: `diagnosis` requires `user == 'pilot'`, so the command always starts with `sudo`, and the later `sh -c` insertion goes after the user name, not before index 1.
- **No EXA or web tools:**
  - EXA is not added before the gate for diagnosis.
  - The gate adds `OPENCODE_ENABLE_EXA='1'`, and the runtime removes it again after the gate.
  - The gate-authored config is patched to `webfetch: deny` and `websearch: deny`.
  - Claude diagnosis still gets no WebSearch or WebFetch in `--tools`.
  - Codex keeps `web_search="disabled"` and `--preserve-env=CODEX_HOME,PATH`.
- **`diagnosis_loopback`:** kept, and nested inside `enforce`, so its rules are removed before the gate's listener closes, as the design requires.
- **`model_join`:** cleanup (`diagnosis_task._quiet`) is kept.

**Interaction with the gate:**
- **Preconditions:** I traced what the real `enforce` requires on a diagnosis call: the route is `GATED_CLAUDE` or in `GATED_OPENROUTER`; the platform is Linux; `/etc/opencode` does not exist; all three XDG variables are set; and the transport key is present. The runtime sets the XDG variables before the gate, and `diagnosis_environment` keeps the right key, so these hold.
- **Request validation:** the gate checks request bodies only, with local function tools only (`model_call_gate.py:389–393`). It never inspects `OPENCODE_CONFIG_CONTENT`, so the runtime patching the permissions after the gate cannot trip it.
- **Codex diagnosis is rejected by both parents:** `enforce` raises `unbounded_route` for a codex diagnosis route. That is not a regression from this merge. `ea2e9cd` already allowed only `GATED_CLAUDE`, and `d0be3c9` allows `GATED_CLAUDE` plus `GATED_OPENROUTER`.

### Strengthened `IsolationPolicyTests` (`tests/factory/test_stream_d_dispatch.py:655–720`)
- **Fake gate:** it asserts `user == 'pilot'`. It also asserts that no file-based `OPENCODE_CONFIG` reaches the gate for gated routes. It then calls the real `openrouter_environment` and replaces the environment in place, as the real `enforce` does.
- **Assertions on the final opencode environment:**
  - no ambient key, including `OPENROUTER_API_KEY`, `OPENCODE_API_KEY` and `OPENCODE_ENABLE_EXA`;
  - exact `permission` of `{task, webfetch, websearch}`, all deny;
  - the gate token is the API key, with base URL `127.0.0.1:12345/api/v1`;
  - `enabled_providers == ['openrouter']`;
  - `OPENCODE_PURE` and the three disable flags are set;
  - the three XDG folders share one parent;
  - the sudo whitelist is exactly the set of keys in the final environment.

  These assertions would fail if any of the brief's failure modes came back: a stale whitelist, EXA leaking through, missing XDG variables, or an ambient key reaching the child.
- **D's loopback rules:** they are still asserted to be in place (net +2) while the model runs.

### Focused offline tests I ran (no live models, cloud or decryption)
`uv run --with numpy --with scipy python -B tests/factory/<file>.py`:
- `test_stream_d_dispatch.py`: 45 tests, OK
- `test_model_runtime.py`: 3 tests, OK
- `test_stream_d_runtime.py`: 26 tests, OK
- `test_model_call_gate_wall.py`: 8 tests, OK
- `test_model_call_maxima.py`: 21 tests, OK

## Findings

### Blockers
None.

### Majors
None.

### Nits

1. **Severity: Nit (zoom-out, delete before adding).** *Scope:* `model_runtime.diagnosis_loopback` (lines 199–214) and its use at line 637, versus `model_call_gate._wall_access`.
   - A now inserts a UID-owner ACCEPT rule for the gate port (`-o lo -d 127.0.0.1/32 --dport <port>`) at position 1 of `factory-pilot`. That rule covers the same thing as D's direct rule.
   - D's conntrack ORIGINAL rule is only needed for redirected or NAT'd flows, which a direct `127.0.0.1` connection does not create.
   - So the pilot's diagnosis path now gets two or three permit rules for one port, from two components using two mechanisms (`self.command` and a direct `subprocess.run`).
   - Keeping it is correct for this merge, because the D design contract and the brief require it. I recommend a follow-up design change that deletes `diagnosis_loopback` in favour of A's `_wall_access` and updates the design section near line 405.

2. **Severity: Nit (zoom-out, right placement).** *Scope:* `model_runtime.py:629–636`.
   - The runtime decodes and re-encodes the gate-authored `OPENCODE_CONFIG_CONTENT` to add the web denies, and removes EXA after the gate set it.
   - It works, but two components now own the final shape of the config. A cleaner fix is a `web=False` (or `diagnosis=`) argument on `openrouter_environment`/`enforce`, so the gate builds the diagnosis config once and the runtime only rebuilds the sudo whitelist.
   - Not required for this small-fix merge.

3. **Severity: Nit (dead code).** *Scope:* `opencode_config(..., diagnosis=...)` (lines 152, 166) and `model_runtime.py:558–559`.
   - Since A, `enforce` rejects every route that is not `GATED_CLAUDE` or in `GATED_OPENROUTER`. A non-gated opencode route writes its `/tmp/factory-*.json` config and then raises `unbounded_route`.
   - That makes the `diagnosis` branch of `opencode_config` (web deny, no `OPENCODE_API_KEY_BASE_URL`) unreachable in production; only mocked tests reach it. It also repeats the deny that is applied after the gate.
   - This came in from A, and the merge carried D's argument onto it. It is a candidate for deletion in a follow-up.

4. **Severity: Nit (robustness).** *Scope:* `model_runtime.py:636`.
   - `cmd[1] = '--preserve-env=...'` relies on the command layout implicitly. It is safe today, because diagnosis always has a user and so the command always starts with `sudo`.
   - A one-line guard (`assert cmd[:2] == ['sudo', '--preserve-env']`) before the rewrite would fail loudly if the command layout ever changes.

5. **Severity: Nit (test coverage).** *Scope:* `IsolationPolicyTests`.
   - The test swaps in a fake `enforce`, so it does not exercise the real `enforce`'s preconditions (Linux, `/etc/opencode`, XDG, token) or A's real `_wall_access` firewall rule alongside D's loopback rules.
   - Those parts are covered on their own (`test_model_call_gate_wall.py` for the wall, and code reading for the preconditions), but no single test runs both together.
   - This is acceptable for an offline unit test. The behaviour on a real VM stays unproven until a native run.

## Readiness against the commit message
The commit message names every retained piece: `runtime_prices`, separate XDG state, gate-owned OpenRouter config, per-user gate access, web restrictions and the sudo whitelist applied after the gate, and `diagnosis_loopback`. The code does exactly that, and nothing in the resolution leaves a design choice to an implementer. Holding back receipt guard 9ec3a12 matches the message (it is not in 3e6a367). The merge claims no Murphy closure, and none is implied.

## Scope and limitations
- **Reviewed:** the merge resolution of `factory/model_runtime.py` against both parents; how it uses `model_call_gate.enforce`, `openrouter_environment` and `_wall_access` at `3e6a367`; and the merge-adjusted tests in `tests/factory/test_stream_d_dispatch.py`, `test_model_runtime.py` and `test_stream_d_runtime.py`.
- **Not reviewed in depth:** the rest of Stream A's content (`token_prices.py`, the rest of `model_call_gate.py`, router maxima, launch guards, fixtures). It arrived unchanged from `d0be3c9` and was reviewed in A's own rounds.
- **Not run:** the full suite (running separately), and anything live, cloud, native-VM or decryption. I cannot confirm offline that sudo accepts a `--preserve-env=<list>` that includes HOME alongside `-H`, or that iptables behaves as described on the VM.
- **Not touched:** `.stream-d-next/`, which is untracked and left as found. No files were changed, and nothing was committed, pushed or merged.
- **Murphy:** no closure is claimed, so there is no closing test to check.

## Elephant response

Accepted PASS. No blocking finding was rejected. All five optional nits are
deferred: the brief requires both loopback mechanisms; moving config ownership,
deleting unreachable routes, and adding command-layout guards are separate work.
Native VM qualification remains unproven. No Murphy row closes.

The handback excludes 9ec3a12 because its own fresh review and full-suite pass
were still pending. It is preserved on stream-d-receipt-guard-held-9ec3a12.
The merge parents are ea2e9cd and d0be3c9.

## Full-suite validation

On merge 3e6a36778c21c59c39ac1d25c728fe582990769e, the prescribed command
`uv run --with numpy --with scipy python -B tests/run.py` completed with
**154 test scripts run; 0 failed**, exit 0. Production and test files remained
unchanged during the run. Launch guards and transfer tests passed.

Log: `/tmp/stream-d-merge-a-suite.log`. SHA-256:
`22f195f54e5e9f42f40f1139f302f4234cb42992a626326692f6ac21f9450863`.
The handback's final commit records this review and validation only.
No Murphy row closes and no native VM or runtime activation is claimed.
