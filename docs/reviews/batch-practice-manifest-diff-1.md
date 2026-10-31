**Verdict: PASS.** I found no blockers and no Major findings. There are six Nits, and none of them blocks merge.

The branch is honest blocked preparation. The committed policy cannot be loaded. Preflight checks the data and exits 3; it never returns 0. The README contains no launch or serve line you could paste and run.

This was a read-only goldfish DIFF review (Mode REVIEW, zoom_out and implementation_readiness, implementation-readiness-standard), covering `f41ce52..049eb3b`. I changed nothing in the checkout, started no workers, made no paid calls, and did not push, merge or delegate. My only writes were throwaway copies in `/tmp`, which I deleted. `git status` was clean before and after.

## What I checked myself

**The release is retained and its pins match.**
- `/tmp/unbug-b3-release-bc33fe52…` exists, and all six files hash to the values in `release-pins.json`.
- I did not rebuild it. `batch.build` requires `commit == HEAD` and a clean tree, so a rebuild needs a new worktree, which the read-only rule doesn't allow. I checked it read-only instead:
  - All 768 hashes in `source-manifest.json` match the git blobs at `bc33fe5`.
  - The decompressed `public-source.tar.gz` matches that manifest exactly.
  - The `batch-release.json` commit is `bc33fe5`, and its `host_files` match `bc33fe5`.
  - `deploy.py` differs from `bin/qualified-release.py` only in its `PINS` block. `install-source.py` differs from `tools/install_source.py` only in its three substituted constants.
  - No `docs/` file is in the source, and no `factory/`, `bin/`, `tools/` or `tests/` file changes from `f41ce52` to `HEAD`. So the pins and the fingerprint are current.

**The policy cannot be launched (design-1's blocker B1).**
- `policy_load` compares `root` with `str(ROOT)` before anything else (`factory/key_holder.py:120`), so the sentinel root refuses by construction.
- Field by field against `docs/reports/stream-b-practice-policy-20261031.json`, only `root`, `code_sha256`, `batch.release` and `batch.sha256` differ, exactly as the design says.
- The recipient is the policy recipient `age17aef…`, not the manifest's restore recipient.
- If someone edits `root` back to a real path, a second barrier still applies. `bind` → `batch_money.manifest` verifies the release at `/home/user/.unbug-control/releases/b3-bc33…`, and nothing is installed there.

**The preflight contract (B2 and B3).** I ran it:

| Case | Exit |
|---|---|
| Real checkout and release | 3, with `PREPARATION VALID — LAUNCH BLOCKED`, the seven blockers and the two expected differences |
| Release copy with one byte appended to `deploy.py` | 1, `pins stale: release files changed` |
| Missing release | 1 |
| Release given as a symlink | 3 (it resolves correctly) |
| Relative checkout path | 1 (see Nit 1) |

- The committed policy is checked for refusal first.
- The translated copy changes exactly two keys, the code proves that, and the copy is only ever written to a temporary directory.
- Every exception either maps to exit 1 or ends in an uncaught traceback, which also exits 1. No path returns 0.
- The `preflight.py` hash matches the one in `docs/reports/batch-practice-manifest-preflight.json`.

**MJ1 (one checkout's data against another's code) is fixed.**
- Preflight requires `root == here.parents[2]`, imports from `root/factory` first, and checks that `key_holder.ROOT.resolve()` equals that root (`docs/practice/b3/preflight.py:28-34`).
- The translated `root` is written as the resolved path.
- The design report records the wrong-checkout case exiting 1.

**MJ2 (the build needs the real restore inventory) is fixed.**
- The design (lines 179-180) and the README (lines 37-42) both say to use a worktree of this repository and treat a missing inventory as a hard stop.
- The preflight report records the inventory tests as 4 passed.

**The arithmetic is correct.**
- Practice: $19.99 case + $0.01 probe = $20 models, plus $5 infrastructure = $25.
- Item 8:
  - Scenario caps 10/10/5/15/15/25/10 add to $90.
  - Alpha (scenarios 1–4) is $40 and beta (5–7) is $50.
  - Beta halves are 7.50/7.50, 12.50/12.50 and 5/5.
  - Worker slots 3/2/1/2/4/6/2 add to 20, and 20 × $0.40 + $2 = $10, so the total is $100.
  - Execution minutes add to 70.
- Preflight enforces the stream-d source hash.
- The A dependency facts check out at `d7539d1`: small is $10 and medium is $15, with context 1,000,000 and output 32,768. `d7539d1` is not an ancestor of `HEAD`, as the design says.

**The documented commands are real.**
- `batch.py build|verify --root --release --sha256` exists.
- `key_holder.py status|launch --batch --job --checkpoint` exists.
- `bin/unbug status` goes through `batch_status`.
- The `boat-call` subcommands `list --json`, `delete <id> --yes --json` and `deletion status <id> --json` are already used in `bin/boat-launch-guards.sh:194-200`.
- `unbug-key-holder.service` exists.
- The launch step is written as prose only. The delete command fails safely when `WORKER_ID` is unset, because of `${WORKER_ID:?…}`.

**Suite evidence is real.**
- The log's compressed and uncompressed sha256 values match the report.
- The log ends `160 test scripts run; 0 failed.`
- It ran at `e832997`. The only later change is six added checks in `preflight.py`, which is outside the suite, and the current preflight hash is the one in the evidence.

**Scope is honest.** No Murphy row is closed and `docs/murphy-register.md` is untouched. All Item 8 pins and inputs are null with `launch_ready=false`. The three blocker lists are identical, and preflight enforces that. The probe is marked not executable until A supplies an enforced cent-level bound.

## Blockers

None.

## Major

None.

## Nits

1. **Exit code for relative paths** (`docs/practice/b3/preflight.py:25`). A relative path exits 1, but the design treats bad arguments as a usage error, which should exit 2. It is still a non-zero exit, so it fails closed.
2. **Release retention in `/tmp`** (`release-pins.json` `release_directory`). macOS clears `/tmp` on reboot, so "retained" is not durable. Preflight then fails closed, and the release can be rebuilt deterministically. Add a sentence to the README saying the copy is disposable.
3. **Unchecked values** (`docs/practice/b3/preflight.py:57-70`). Preflight never checks that `policy.batch.release` equals `…/releases/b3-<build_commit>`. It also never checks that scenarios 1–4 have zero replacement money or that the alpha/beta split is 40/50. All of these are correct in the committed bytes.
4. **Restart command in step 7** (`docs/practice/b3/README.md:94`). `systemctl restart unbug-key-holder.service` is paste-ready inside the held sequence. It is not a launch, but it would be safer labelled "live acceptance only, after the step-1 prerequisites".
5. **Headroom figures** (`docs/practice/b3/README.md:65`). $1.344639 and $6.344639 are $0.000001 under the exact values of 10 or 15 minus 8.655360. They err on the safe side, so this is harmless.
6. **Review record hygiene.** `docs/reviews/batch-practice-manifest-design-1.md` and `-2.md` include the prompts and progress narration along with the reviews.

**Pass/fail: PASS.** The preparation is safe to merge as blocked preparation. Live launch still waits on the B, B2, A, E and D prerequisites, and the final release and policy need a fresh review.

## Elephant disposition
PASS accepted. No blockers or Major findings. Optional nits left unchanged; no blocker fix is self-verified. The /tmp release copy is disposable and can be rebuilt at its pinned commit; absence fails preflight. Runtime paths remain unchanged. No launch, merge or push performed.

