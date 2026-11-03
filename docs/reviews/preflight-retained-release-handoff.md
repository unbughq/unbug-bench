# Preflight retained-release evidence handoff

## Candidate and scope

Prepared branch: `t3/preflight-retained-release-evidence`. Merged the existing
`c93f91eb4ddc98f38d47ee784b47cb3c6aa96d7d` into integration base `f9a97ea` without
conflicts. No implementation changes beyond that existing branch. Root owns
integration; this branch is not merged into `factory-simplify`.

The accepted encoded-input finding is fixed in shared `router_delivery.pack`:
base64 input over 16 MiB is refused before config reads or RPCs, matching the
CLI's bounded stdin rule. The existing 13 MiB selected-member dispatch regression
requires TEMPFAIL, pending state, `dispatch_started=false`, and no launcher spawn.
The earlier 186-script pass predates that fix and is not final-candidate evidence.

## Read-only retained-artifact audit

See `preflight-retained-release-audit.json` for the exact paths, original commits,
record digests, policy pin matches, inventories, and changed host files. Searched
tracked release/policy records and existing local release trees under this prepared
checkout, `/Users/bugsincode/Developer/ub-preflight`,
`/Users/bugsincode/Developer/unbug-bench`, `/Users/bugsincode/.t3/worktrees/unbug-bench`,
and `/private/tmp`. No secrets were read; only public release records and selected
release-binding fields of retained policies were inspected. No release was built,
rewritten or repinned for this audit.

Five complete batch releases were found in `/private/tmp`. Each digest matches
its independently saved policy, and real `batch.verify(directory, digest)` passes.
Real `batch.verify(directory, digest, current_root)` refuses all five with
`host differs from batch commit`:

- `6ac450e`: 44 host files, 11 missing, 23 changed; its batch-release record is
  byte-identical to the tracked stream-B retained record.
- `bc33fe5`: 44 host files, 11 missing, 22 changed; matches tracked B3 policy.
- `3a50896`: 51 host files, 4 missing, 21 changed.
- `02f3bc9`: 53 host files, 2 missing, 20 changed.
- `b75c9b4`: 53 host files, 2 missing, 18 changed.

The current host contract has 55 files. The two missing files in the newest
53-file releases are exactly `factory/practice_preflight.py` and
`factory/model_runtime.py`. Removing these from the fingerprint would neither
repair the changed host hashes nor satisfy the accepted trust boundary.

## Precise remaining evidence blocker

Round 2/2's B2 remains accepted and unresolved; the verdict in
`preflight-diff-2.md` stays FAIL. `new-preflight-2` stays open. Existing dispatch
tests still honestly describe their generated current release as implementation
coverage, not independently retained-release regression evidence. No review 3
was started and no accepted review was rerun.

Needed: an independently retained complete compatible public batch release:
`batch-release.json`, `deploy.py`, `install-source.py`, `source-manifest.json`,
`public-source.tar.gz`, and `worker-release-manifest.json`, together with its
independently saved policy/pin digest and unchanged manifest. The record must
contain exactly the current 55 host paths and match the candidate host bytes;
all payload hashes must verify. Then replay the existing real-dispatch hold
regressions with that saved release and pinned digest (without calling
`batch.build` to manufacture the regression fixture). Preserve provenance and
limit any necessary recipient/fingerprint adaptations explicitly as the existing
tests do. No compatible artifact was found in the audited local evidence.

## Fingerprint consequence for root/founder

`launch_manifest.TRUSTED_FILES` now includes `factory/practice_preflight.py`
(dispatch preflight executes in the holder) and `factory/model_runtime.py`
(Codex role resolution executes via `select_models`). Consequently either file's
byte change alters `key_holder.fingerprint`; a policy pinned before this addition,
or before a later change to either file, is refused by the existing fingerprint
checks. Future authorized installation must carry both files in the release,
recompute the policy code fingerprint/release pins, and obtain the existing
founder unlock/acknowledgement. That acknowledgement is pending; this offline
handoff neither requests nor grants live authority. No unlock or repin performed.

## Validation and limits

Touched tests passed using `BENCH` set to this checkout: `test_preflight.py`
28 tests plus four import-time support tests; `test_router_delivery.py` 5;
`test_batch_holder.py` 60; `test_control_vm.py` 22. `git diff --check` passed.
Next, one full suite on the committed final candidate with `uv run --with numpy --with scipy python -B tests/run.py`.
Exact final SHA and observed results are returned in the handoff message; full
suite output is retained locally outside tracked source so recording it does not
change the tested commit. Root must validate its merged tree under ENGINEERING.md.

No provider/cloud qualification, model calls, deployment, paid runs, workers,
secrets access, unlock, push, main changes, sibling practice/startup-smoke edits,
scoreboard edits or additional launch paths were performed.
