# Preflight design review 2 (final round)

Goldfish: fresh Claude (claude-opus-5-5) general-purpose subagent, read-only, with no memory of round 1. Personas: zoom_out, design_critic, implementation_readiness; Mode: REVIEW. Standards: heilmeier, implementation-readiness. Design: docs/designs/preflight.md at a5a005c.

## Verdict: FAIL. Four blockers, all small text fixes; the direction stands.

### Round 1 blockers
- B1 resolved: `image_startup` is gone and stop 10 is deferred to `t3/batch-service-control-vm`. The branch and its report sections exist.
- B2 resolved: the Codex gate now uses resolved roles. Every slot in both rotation files gives openai (`codex/gpt-6.1-sol`) a role, so rotation defaults always pull in Codex. One claim about line 514 is wrong (N2).
- B3 partly resolved: the checks now run inside `dispatch` before `dispatch_started`, with no report file and no window. New B1 remains.
- B4 resolved: the design uses `router_delivery.pack`, with caveats in N4 and new B2.
- B5 resolved: the decisions file has a path and schema, the caps stay in `LIVE`, and min() is adopted. The repin is still unstated (N9).
- B6 resolved: the step 2/3 actions are kept and the checks split into A and B. One coverage loss: new B3.
- B7 resolved: stop 9/10 evidence is cited, the dependency on the unmerged branch is stated, and `new-preflight-5` waits for live qualification. Row 31 is now closed falsely: new B4.

### Answers
1. `TEMPFAIL` is a no-op exit at `batch_holder.py:321`, so the operation stays pending. `key_holder.py:454` sleeps 60 s, and `reconcile` (`batch_holder.py:452-457`) respawns dispatch. That gives a fixed 60 s retry with no backoff and no cap. It costs $0: each attempt does a bundle decrypt, a Boat `list`, a router `status`, an OpenRouter `/credits` read and an R2 read, and writes a new log file (`key_holder.py:558`). That is not a storm, but the hold reason is never recorded (N5). The real problem is that the existing terminal refusals in `dispatch` fire before the hold (new B1).
2. `pack` inside dispatch is safe. It reads a 0600 config file and makes one `status` RPC. `status` (`model_router.py:308-315`) only runs the lease-expiry housekeeping that every RPC runs, and the packed output is discarded. Caveats in N4 and new B2.
3. The args are available: `$args` is in scope at `launch.sh:149`, `:514` and `:654`, and resume re-execs the original argv (`control_resume.py:60-74`). The design's claim that 514 can't resolve is false (N2). Failing closed on unparseable args is the right fallback.
4. Root SSH matches how the VM is administered: `bin/control-vm:130-137,170` uses `user='root'`, `control/setup.sh:2` says "Run by bin/control-vm over root SSH", and the 2026-11-03 repair used root SSH. The check needs the same SSH options (N6).
5. Over-built and not-real items: phase B `boat_cli` is redundant (N1), the row 31 replay test duplicates the existing BoatTests (new B4), and the Codex "real refusal" replay can't be a real artifact (N10).

### Blocking
B1. Existing terminal refusals in `dispatch` pre-empt `PreflightHold` for credentials (stop 8). `secret_labels` (`batch_holder.py:783`) raises `ValueError` on decrypt failure, and the label check at `:788-789` raises `ValueError('request_refused')`. Both land in the catch-all at `:832-838`, which marks the operation `failed`/`preflight_refused` before any phase B check runs. So stop 8 inside dispatch still kills the operation, and phase B's `credentials` re-check adds nothing. Fix: phase B's `credentials` replaces the `secret_labels` call and the label check at `:783-789`, and both raise `PreflightHold`. Keep the recipient check (`:781`) and the fingerprint check terminal. Add a test in which an undecryptable bundle through the real `dispatch` leaves the operation pending.
B2. `r2_openrouter` has no defined mechanism, and the obvious one never passes. Router `status` reports credit as `null` until the first paid call: `paid_account` is written only inside paid-reserve (`model_router.py:465`), and `credit_reader` is called only for `paid_reserve` (`:274-277`). A fresh run would fail the check every time, which is a permanent hold. The other route is `model_router.available_credit()` with the bundle's `openrouter-key`, but `dispatch` holds no decrypted bundle (`secret_labels` runs `tar -tf` only). `login_lifetimes`, `pack` and R2 also need the full contents. The R2 object to read is unspecified. Fix: decrypt the bundle once in dispatch, in memory, and derive the labels, `codex-auth.json`, `openrouter-key` and `r2-env` from it. Read credit with `available_credit()`, fail on `None`, and report min(`LIVE` cap, credit). Name the R2 read (for example a HEAD on the batch prefix).
B3. Deleting step 2's "ledger" verification leaves no replacement. `practice-run.md:28` lists "stale or depleted paid ledger" as a pre-worker abort. No A or B check replaces it, so it would first surface at the first paid call, after a worker exists. ("Hashes" is still covered by the fingerprint check at `:774` and `batch.verify` at `launch.sh:62`.) Fix: have `router` also assert that `status['paid']` is well-formed with `outstanding_usd == 0`. Otherwise keep "ledger" in step 2.
B4. Row 31 would be closed falsely. It is already closed by `test_isolation_timeouts.py` BoatTests, which include mismatch refusal. Its only gap is "VM install pin remains a deployment prerequisite". The phase B call site already exists (`batch_holder.py:792-798` plus the guard at `bin/boat-call:48-53`). The root cause is untouched: `control/setup.sh:39` downloads the latest prod Boat CLI, and the 2026-11-02 report confirms the endpoint returned 1.0.88. An offline replay proves nothing new. Fix: close row 31 only at live qualification of phase A `boat_cli`. Better, pin `setup.sh` to the exact `boat-cli-v1.0.85` asset with its SHA-256 (`5d7933a2…`, from the report).

### Nits
N1. Phase B `boat_cli` is redundant: dispatch already runs `boat-call list` through the version guard, and a mismatch already returns `TEMPFAIL`. The stop-6 evidence shows dispatch_started false and the operation pending. Drop it.
N2. The line 514 premise is false: resolve normally there and fail closed only on unparseable args. Line 514 is unreachable for batch runs (`launch.sh:505`).
N3. Specify the `codex_login.py` interface:
- `$args` is a shell-quoted string, so the call needs `eval "set -- $args"` and then `-- "$@"`.
- Use `parse_known_args`, because batch args carry `--factory-job-config` and similar.
- Honour `--rotation-table` and `FACTORY_ROTATION`.
- `practice_preflight.roles()` can't be reused as is: it raises on a missing flag and on `codex/`. That would let the "no `--strong-calibrator`" test pass by being unresolvable rather than by resolving to Codex, so the test should assert that a Codex role was resolved.
N4. Run `pack` on the bundle as filtered at `launch.sh:320-324`: `pack` refuses `._` names, and the raw bundle carries `r2-env`. The risk is low, since `setup-secrets:95` sets `COPYFILE_DISABLE`.
N5. Say what the hold looks like: print the `PreflightHold` reason to stderr, where it lands in the per-spawn log, and note the fixed 60 s retry. `batch_status` already flags "launch stuck".
N6. `deploy_access` should reuse `bin/control-vm`'s `ssh_options()`: the `~/.ssh/unbug-bench-hcloud` key, `IdentitiesOnly` and the per-server `known_hosts`. A bare `ssh -o BatchMode=yes root@…` can fail on the host key or pass with a different key. Also write "install via root SSH (`bin/control-vm`)" into practice-run step 2, or `new-preflight-5` has a check but no fix.
N7. Line references are off: the `dispatch_started` write is at 822 (not 812), the `MoneyWait` catch at 830, the failed-marking at 832-838, and the `secret_labels` / `boat-call` calls at 783 / 792.
N8. Define "fresh admission". "Fresh admission only" contradicts "resume and replacement use the same checks". Say it covers every `dispatch()` before `dispatch_started`, including checkpoint and replacement launches, and excludes `resume_controller`.
N9. Square the exit codes 0/1/2 with the existing `code()`, which returns 1 or 3. Say that the decisions file joins `pins()`/`files()`, which means a repin at step 0.
N10. The "real refusal" replays aren't real artifacts: the report keeps labels only, so the Codex replay needs a JWT made up for the test. Say so.
N11. `credentials` must build its label set the way `dispatch` and `launch.sh` do: the Claude label from `launch_accounts`, the OpenCode label defaulting to `opencode-go-key`, and the router names added by `pack`, not required in the bundle.

Reviewed `docs/designs/preflight.md` at `a5a005c` against the code in `/Users/bugsincode/Developer/ub-preflight`. Nothing was edited, run or spent.

## Elephant resolution (parent decision at the 2-round cap)

All four blockers are accepted. Each comes with an exact fix, and none changes direction, so I resolved them in revision 3 without a third design round. The diff goldfish must confirm each of B1–B4 in the implementation. N1–N11 are adopted, except that N9's exit codes keep the existing `code()` convention: 1 means fail, 3 means unproved/needs_founder, and 0 means all pass.
