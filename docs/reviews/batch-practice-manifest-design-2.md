Act as the review sub-agent for this task.

Fresh read-only goldfish design re-review. Read tools/egm/agents/zoom_out.md, design_critic.md, implementation_readiness.md first; Mode REVIEW; standards heilmeier-standard.md and implementation-readiness-standard.md. Review docs/designs/batch-practice-manifest.md including final concrete contract and docs/reviews/batch-practice-manifest-design-1.md objections. Assess blocker fixes independently. Only read referenced files; no writing, workers, calls, push, delegation. User explicitly approves $25 practice plus separate cent-level Claude probe and $100 item8 within existing subscriptions/OpenRouter credit no topups, but this task is preparation only. Return full review and pass/fail.

Checking the design's claims against `key_holder.policy_load` and `batch.verify`.

I checked the design against the code it relies on: `key_holder.policy_load`, `fingerprint`, `batch.build`, `verify` and `bind`, `batch_money.manifest`, `launch_manifest`, the historical practice policy and the inventory check that runs during a build.

## Goldfish design re-review: `docs/designs/batch-practice-manifest.md` (design-2)

**Verdict: PASS.** All three blockers from design-1 are fixed, and I confirmed each fix in the code. There are no new blockers. Two Major findings should be added to the design text before implementation, and the diff review should check them.

This was a read-only review. I wrote nothing, started no workers, made no calls, pushed nothing and delegated nothing. Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier and implementation-readiness.

### Blocker fixes, each checked on its own

**B1 (the policy could be launched through the legacy path): FIXED.**
- `policy_load` first compares `policy['root']` with `str(ROOT)`, at `factory/key_holder.py:120`. It raises an error before it reads any other field. A root of `/BLOCKED/b3-not-approved-for-launch` therefore makes the committed file fail to load by construction.
- Every launch-capable loader goes through `policy_load`: `key_holder.py:476` and `:800` (serve), `batch_holder.py:771`, `coordinator.py:270`, `account_handoff.py:154`, and `restore_bundle.py:343`.
- The only loader that skips it is `coordinator_inventory` snapshot, which uses `read_public` and is read-only.
- The design now says plainly that the flags are not safety barriers (lines 21-22). Preflight checks first that the committed policy is refused (line 145, check 4).
- One limit remains, and the design accepts it: anyone who edits the single `root` field to a real path makes the file loadable, because `code_sha256` is current. That is fine for preparation pins, and the design says final launch needs a new review.

**B2 (preflight had no contract): FIXED.**
- The arguments are now specified.
- The checks are listed in order, from 1 to 5.
- A valid run exits 3, an error exits 1 and a usage error exits 2. It never exits 0, so no wrapper can read it as "go".
- A valid run prints `PREPARATION VALID — LAUNCH BLOCKED`.
- The gaps between the old manifest and the future live one ($20 vs S+$19.99, accounts [2] vs [2,1]) are reported as expected differences, not as failures and not silently.
- The README cannot contain a launch line that could be pasted and run.
- It is clear where the arithmetic checks live: inside preflight, not in a new test harness.

**B3 (policy fields and the translated copy were undefined): FIXED.**
- Every field now has an exact value or a stated source.
- The recipient is pinned to the policy `recipient` (`age17aef…`). The design names the manifest `restore_recipient` (`age1ae6f…`) and says it is not used. Both match the historical policy and design-1.
- The translated copy changes exactly two keys, `root` and `batch.release`. Preflight compares the two objects after setting just those keys aside.
- The translated `policy_load` gives a real check. It calls `batch.bind` (`batch.py:140`), which calls `batch_money.manifest`. That function verifies the release against the root, the manifest bytes and source-manifest hash, that the jobs match the policy, and that the restore recipient matches `control-recipient.txt`.

**The Majors and Nits from design-1 are resolved:**
- M1 and M2: the two founder approvals and the probe approval are now quoted in the design. This task's instruction confirms them.
- M3: the build commit, the `/tmp` release directory kept outside the repo, the commit order, how the reviewer rebuilds, and "stale pins" as the intended fail-closed result are all stated.
- M4: schemas are defined.
- M5: there is a plain objective and a timeline.
- M6: the live manifest is required to use `[2,1]` and a commitment of `S+E` with E ≤ 19.99.
- N1–N4 are addressed.
- I also confirmed that `docs/` is outside `BATCH_SOURCE` (`launch_manifest.py:99`) and outside `TRUSTED_FILES`. Committing the pins and policy after the build therefore cannot change the release or the fingerprint.

### Major (not blocking; add to the design before implementation)

**MJ1. Preflight could check one checkout's data against another checkout's code.** (Lines 147-149, check 4.)
- `key_holder.ROOT` comes from the location of the imported module file. `policy_load` compares it to the policy's `root` as an exact string.
- Preflight reads committed data from beside its own file, but it takes the checkout root as an argument. The design doesn't say which tree the factory modules are imported from.
- If the two differ, preflight validates one tree's data against another tree's code. It could also fail on symlinked paths, such as `/tmp` → `/private/tmp` on macOS.
- **Fix:** have preflight import `factory/` from the checkout argument. Require that `Path(arg).resolve()` equals both the import root and the repo that contains preflight. Write `str(resolved)` into the translated `root`. If they don't match, exit 1.

**MJ2. The build depends on the real restore inventory, and the design doesn't say so.** (Lines 166-169.)
- `batch.build` runs `test_restore_inventory.py --require-inventory` (`batch.py:62-64`). That check raises an error when no real ciphertext inventory exists in this checkout or in the Git common checkout.
- So the reviewer's "rebuild at build_commit in a clean checkout" only works where that inventory can be reached.
- **Fix:** state that the build and the reviewer's rebuild happen in a worktree of this repository. State that a missing inventory is a hard stop, never worked around or faked.

### Nits

- **N1.** Line 20 says "exact host trusted fingerprint", but line 138 says `fingerprint(checkout)`. Use the checkout wording in both places.
- **N2.** Checks 2-3 partly repeat what check 4 already does through `bind` → `batch_money.manifest`. Keep them, because `manifest()` reduces every failure to `money_wait`, and running them first gives clear "pins stale" messages. Say that this is the reason for the duplication, and don't write a second version of the manifest checks.
- **N3.** In the `release-pins` schema, name the six files: `batch-release.json`, `install-source.py`, `source-manifest.json`, `public-source.tar.gz`, `worker-release-manifest.json` and `deploy.py`.
- **N4.** Line 81 says "inert runtime policy and a non-loadable policy". The phrase is repeated, and "inert runtime" is the wording design-1 objected to. Say "non-loadable policy" once.

### Heilmeier and readiness

- **Heilmeier:** the objective, current practice (the inert 6ac450e preparation), the new approach, impact, risks, cost ($0 offline), timeline and exams are all answered. The rest of the document is still dense with insider shorthand, but the plain objective paragraph meets the bar.
- **Readiness:** the files to create, the policy fields, the schemas, the preflight checks and exit codes, the commit and build order, and the test plan are all specified. MJ1 is the one remaining decision left to the implementer.

### Honest preparation vs. something that looks runnable

- **Honest:** the policy cannot be loaded and preflight proves it. Preflight never exits 0. The README holds no launch line. Item 8 pins and inputs are null with `launch_ready=false`. The probe is marked not executable until A provides an enforced cent-level bound and a receipt path. A's $10/$15 profiles are treated as dependencies that aren't in this base. No Murphy row is closed. The approved $25, the cent-level probe and the $100 are recorded as limits that need B, B2, A and E proof, not as launch authority.
- **Unsafe:** none remain.

**Pass/fail: PASS.** Add MJ1 and MJ2 to the design text; the diff review should confirm both.

## Elephant resolution
MJ1/MJ2 and N1–N4 incorporated before implementation. No findings rejected.

