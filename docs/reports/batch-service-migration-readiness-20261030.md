# Founder migration command readiness, 2026-10-30

The existing reviewed command's read-only preflight passes again after rebase
onto cfe616f. This qualifies the founder-side command, not VM activation or
unattended batch lifecycle. No identity was supplied; no output generation,
original, pointer or VM file changed.

Run from the B worktree (requires Python3.11+, age, age-keygen and caffeinate):

```sh
cd /Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5
tools/migrate-legacy-checkpoints.sh \
  --plan docs/reports/batch-service-migration-plan-20261030.json \
  --plan-sha256 bac461d88e3b7f413c28ea55a5e70aa83a1fe56b336153d965ac23c3e1707aa6
```

Add --dry-run to repeat the successful preflight. The real command shows the
pinned inventory:30 archive prefixes,48 variants (3,251,961,841 bytes),16 key
rewraps and1 absent card binding. It needs3,644,279,178 bytes free and estimates
1257 seconds on Mac, plus493 seconds for later agent-owned VM verification.
It asks once for the founder age identity in the terminal with echo hidden;
never put the identity in chat. It keeps originals and active pointers unchanged,
then reports migrated/failed/skipped. Rerun the exact command after partial
failure; complete verified outputs are skipped. No real-key run was attempted.

The existing plan deliberately names the original Mac sealed inventory and the
verified ciphertext cache; running from this worktree does not change those
frozen paths. Real migration writes only the immutable output store named by
that plan. VM unwrap/R2 proof and activation follow separately; the absent-card
case cannot become current. No case is launched or implicitly imported.

Preflight log SHA256: 1b876d13ad9a161c0699fdc4fa431628ab451ae4ed5528f33eee03d1303208ca.
Reviews already approving this command: batch-service-design-4.md and
batch-service-diff-2.md. No new implementation or Murphy closure. Live spend:
$0 model / $0 incremental infrastructure. Reviewer-agent usage unmeasured.
