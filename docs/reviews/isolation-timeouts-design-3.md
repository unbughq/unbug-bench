## Goldfish design review 3: `docs/designs/isolation-timeouts.md`

**Mode:** REVIEW. I read the three personas, review rounds 1 and 2, the canonical `ENGINEERING.md` and `murphy-register.md`, and the code the new rollout section cites. I made no edits, ran no cloud commands and decrypted nothing. Save this text verbatim to `docs/reviews/isolation-timeouts-design-3.md`.

## Verdict: PASS

N1 is resolved. I found no open blocker. B1–B5 stay fixed, since the sections that fixed them are unchanged. The remaining findings are nits. Scope is not re-expanded.

## N1: trusted-launcher rollout

| Check | Result |
|---|---|
| The launcher fingerprint change is stated | Yes. Lines 249–252 say it changes, and that the change is to the bound code bytes, not the approval property. |
| No policy bypass | Yes. "No old approved policy is rewritten or allowed to bypass `code_sha256`." This matches `key_holder.policy_load` (`:116`) and the two live ops (`:479`, `:540`), which refuse on any mismatch. |
| Who regenerates the policy, and when | Specified (lines 255–260). After the four phases merge together and reviews pass, the parent regenerates `code_sha256` with `key_holder.fingerprint` on the final deployed checkout. The same job authorizations are kept, and the concrete policy goes to the founder before holder unlock. This satisfies ENGINEERING §1, which requires founder sign-off on a security-property change. |
| Pending and in-flight work | Specified (lines 260–263). The old holder and checkout keep managing their live workers. Old reservations resume only there. New-policy launches use a distinct frozen reviewed checkout. A live controller's checkout is never overwritten. |
| Phase ordering | The four phases merge together. The parent merges E before the later streams. |
| Registration of `bin/processes.py` | Correct. It goes in `TRUSTED_FILES` because `boat-spend` imports it. That also puts it in `HOST_FILES`, so restore staging copies it. It also goes in `WORKER_BENCH`, so workers install it. |
| `runner_supervisor.py` | Correctly left to `WORKER_GLOBS`, since it runs on the worker. `restore_bundle.launcher_files` only audits `$root/` and `$here/` references. `launch.sh` reaches it as `~/factory/...`, so it does not trip the "undeclared restore launcher input" check. |
| Boat prerequisite (M-B) | Resolved. The pin is stated as check-only. The deployer must run `BOAT_NO_UPDATE=1 /usr/local/bin/boat --version` on the VM and see 1.0.85 before enabling the checkout. `control/setup.sh:48` only prints the version, and the download URL has no pin. The design says this stays open and that the Mac receipt asserts nothing about the VM. |

## M-A to M-E

| # | Status | Basis |
|---|---|---|
| M-A | Answered | Lines 273–277. Never `killpg` the caller's group or session. A shared diagnostic child is killed by PID plus descendant PIDs. The test runs the opt-out in a separate subprocess and asserts the owner survives. |
| M-B | Answered | See the Boat prerequisite row above. |
| M-C | Answered | `TimeoutExpired` is raised and `gate_attempt` records `runner_error:TimeoutExpired` as an operational stop. A real public-card gate test is required. |
| M-D | Answered | G13/G14/G15 strategy cache signatures and G11/carry-over identity rerun. This matches `run.py:1397`. |
| M-E | Answered | `args`, detach and credentials stay inside the setup subshell. Only `bench-sha`, `setup-status` and the existing receipts persist. The parent keeps serial and ID ownership. |

The round-2 nits are also handled. The garbled line 104 was replaced. The reason-enum writers are named: the supervisor alone writes `timeout` and `cancelled`. The double TERM from `collect.sh` is justified. `guard_exit` gets the held-VM rule: all IDs must be deleted before `--finish`. That rule needs removing the `|| [ -z "$UNBUG_LAUNCH_STATE" ]` branch at `boat-launch-guards.sh:258`. The `.deleted` markers are written in both state modes (`:192`, `:203`), so the rule works in both.

## Nits (optional)

1. **Policy `root`.** `policy_load` also checks `policy['root'] == str(ROOT)`. A new frozen checkout has a new root, so the regenerated policy must carry that root as well as the new `code_sha256`. One clause in line 256–260 would say so.
2. **Cross-generation admission.** The new reservation ledger only sees new-generation launches. Old-generation checkouts never write it, so they hold no reservations in it. During the overlap, new admissions are checked against the current balance and not against the old generation's un-accrued estimates. This is consistent with "single-control-host guarantee only; row 17 stays open", but a sentence would say it plainly.
3. **Parked VMs.** `guard_exit` marks a parked VM `.deleted` (`boat-launch-guards.sh:192`), so its reservation releases while the VM lives until its paid hour ends. The provider TTL and the parked-hour bound keep this small. Accepting it in one line would be enough.

## Murphy row accounting

| Rows | Review |
|---|---|
| 31, 44, 46, 52 (target closure) | Plausible given the real-artifact tests. Row 31 closes on the test only, and the design no longer overclaims the VM pin. |
| 17, 18, 42, 43, 49 (partial) | Correctly left open. |
| 28, 29, 30, 32, 37, 45, 50 | Correctly left open with reasons. |

Proceed to implementation. Closure of rows 31, 44, 46 and 52 still needs the diff goldfish to confirm each test proves its row on real artifacts.

I did not write `docs/reviews/isolation-timeouts-design-3.md`, because you said no edits. I can write it if you want.


---

Elephant disposition

PASS accepted. Root and code_sha256 must both match the final deployed checkout policy. Cross-generation wallet coordination remains open (17); parked Hetzner servers bypass the Boat wallet ledger. No blocker remains; no blocking finding was rejected.
