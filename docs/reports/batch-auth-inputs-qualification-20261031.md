# B2 input qualification result

Branch base: factory-simplify f41ce5219dadd7f09c245ee03707c0de69158129.
No worker was created, no case model call was made, no key was read and no store
or VM policy was changed. Reviewer-agent usage is separate.

The real migrated store is absent at the frozen plan output on the Mac and at
/home/user/unbug-bench/sealed/generations on the labelled control VM. The latter
has 46 flat legacy checkpoints and no control-home batch directories. The local
migration qualifier exited 1 with 64 missing planned outputs. See
batch-auth-inputs-live-20261031.json and batch-auth-inputs-migration-20261031.json.
This is a failed qualification, not an empty inventory pass. No VM unwrap or R2
binding was verified. No eligible authenticated checkpoint is established.

The exact proposed practice case namespace, case-b-practice-20261031-practice,
is clear on the real VM: all eight collection names, both generation namespaces
and the current pointer are absent. That proves namespace availability only.
A fresh empty input uses the existing holder launch with checkpoint=null; it does
not import the legacy dry-run archive. The new shared admission predicate checks
manifest, money/chain eligibility and namespace, and the holder checks again
before first dispatch. Offline tests qualify those decisions with retained real
ciphertext and explicitly authored batch bindings. They do not claim a live batch
ACK or prove account identity, cleanup, a reviewed release or remote publication.

Deployment handoff to B3: the qualification helper is a repository tool, not a
holder dependency. The current public BATCH_SOURCE selection excludes tools/;
B3 must include tools/qualify-batch-inputs.py in its reviewed deployment, or make
the matching reviewed source checkout available, before using the command below.
B2 did not edit B3's release pins or manifest or copy code onto the VM.

After B3 installs its reviewed policy, release and qualification helper, run from
that source on the VM:

```sh
python3 -B tools/qualify-batch-inputs.py \
  --policy /home/user/.unbug-control/policy.json \
  --home /home/user/.unbug-control --job practice
```

Exit 0/eligible=true means only input admission at that observed point in time.
launch_ready remains false. For an authenticated checkpoint, add --checkpoint
with its actual same-batch digest. The authoritative holder rechecks on launch;
do not use the report as a token or rename/import a legacy archive. An absent or
unreviewed policy is still a blocker; the prep policy was not repinned by B2.

After the founder migration creates real outputs, rerun:

```sh
python3 -B tools/migrate-legacy-checkpoints.py \
  --plan docs/reports/batch-service-migration-plan-20261030.json \
  --plan-sha256 bac461d88e3b7f413c28ea55a5e70aa83a1fe56b336153d965ac23c3e1707aa6 \
  --qualify
```

Even local_integrity_passed=true exits 1 and qualified=false until a separate
real VM unwrap and R2 binding qualification is recorded. This command is strictly
local integrity inspection and never prompts for an identity. Preserve both
historical checkpoint variants for case-20261017T125556Z-18681d. The available
checkpoint for case-20261017T114431Z-9d2b0e cannot stand in for its missing bound
archive. The tool neither activates pointers nor grants batch provenance.

Rows new-single-path-1, new-batch-service-1 and new-batch-service-2 remain open.
The new empty-namespace hazard new-batch-auth-inputs-1 also remains open: its
contract regressions are not a live incident closure.

Final validation: implementation 16f8159 passed the required full suite, 161
scripts, zero failures, three reported skips. See
batch-auth-inputs-suite-20261031T151828Z-b7422f94.json. Fresh diff review
../reviews/batch-auth-inputs-diff-2.md passed with no blockers; its nested-repository
Git-discovery finding is non-blocking and deferred. Final read-only store recheck
at 15:42:36Z still found both planned stores absent. No rows are closed.
