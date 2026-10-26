# Fingerprint and stop on drift

`bin/freeze` creates a local source snapshot, SHA-256 manifest and source archive.
It covers bench code, checker, traffic, guards, seed IDs, lockfile, development
scenarios and keys, claim scoring, Harbor definitions, arm prompts and protocol.
Source additions, removals, content and permission changes fail verification.
Every archived source member is also checked against the source manifest.
Dependencies/build output (`node_modules`, `.medusa`), caches and run results
are excluded; dependencies are represented by the lockfile and runtime image IDs.
Only explicitly supplied encrypted `.age` archives are copied; keys are never inputs.

On the judge machine, capture runtime identities without reading credentials:

```sh
rtk proxy bin/freeze-runtime \
  --image unbug-bench-medusa:latest \
  --image postgres:17.11-bookworm --image redis:7.4.8-bookworm > results/runtime.json
```

Record the separate Harbor box/judge image IDs on their actual host too. Locally
built images have content-addressed IDs even when they have no registry digest.
Use those identities for scored runs; tags alone are mutable. Archive/export the
images or store them in a private registry before deleting the only host copy.

```sh
rtk proxy bin/freeze create results/freeze/UNIQUE-ID \
  --runtime results/runtime.json --evidence results/calibration-summary.json \
  --archive sealed/APPROVED-CASE.tar.gz.age
rtk proxy bin/freeze verify results/freeze/UNIQUE-ID/manifest.json
rtk proxy bin/freeze run results/freeze/UNIQUE-ID/manifest.json \
  --sha256 TRUSTED-MANIFEST-HASH --check-images -- bin/checkpoint --scenario scenarios/dev/S0-null \
  --guard reference --runs 30 --stress
```

`run` verifies before and after the command and preserves its failing exit code.
It stops before a command when inputs have changed. A change during a command
invalidates that run. This is a trusted-operator integrity check, not protection
against an operator who replaces the verifier itself. Preserve the manifest
digest outside the mutable checkout and verify against that trusted digest.
`--check-images` compares image IDs on the actual runtime host before and after;
use it for scoring to catch mutable tags pointing to different images. A source
verification on another architecture can omit it, but is not a runtime check.

`harbor/run-audited.py` also copies task, proxy and responder sources into a
private temporary staging directory and hashes them before launching. Do not
bind live addon source into a scored proxy: mitmproxy reloads edited scripts.
The staged inputs remain outside the repository with the raw trial results.

## Local snapshot versus binding experiment lock

A local fingerprint is useful now, but it does not satisfy PROTOCOL section7.1
on its own. The bench repository currently has no commit. Before the first
scored attempt, the operator must also:

- Finish and identify the clean-room Unbug artifact and all baseline prompts/tools.
- Lock thresholds, model/CLI IDs, budgets, seeds, attempt count and stop rules.
- Select accepted sealed cases and include their encrypted archive hashes.
- Complete the prescribed pre-freeze red-team repetitions and independent review.
- Capture the exact deployed image identities, commit/tag the agreed inputs,
  and publish the manifest hash with an independent public timestamp.

Do not describe an infrastructure snapshot as a scored-experiment freeze.
No scored attempt or Claude practice run was started by the infrastructure checks.
