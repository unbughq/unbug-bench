## Verdict: BLOCKED

There is one blocking finding: tests the design names for increment 1 are missing. The migration code itself matches the design for every behaviour in scope that I traced, and I found no correctness or secrecy defect in it. The fix is a few small tests and changes no production code. Merge also still needs the full suite to PASS. When I looked, `/tmp/unbug-batch-increment1-rebased-tests.log` was still running (last line `tests/bench/test-launch-guards.py`), so there is no PASS yet.

**What I did:** I read the personas (`zoom_out.md`, `implementation_readiness.md`), both standards, `docs/ENGINEERING.md`, design sections L205–375 and L430–560, the full diff 92266d6..10301c5, and the helpers it reuses (`registry.atomic_json`, `registry.identifier`, `unlock_sealed_audit.write_private`/`decrypt_one`).

I also ran one read-only check that was neither a test nor crypto. It called `load_plan` on the frozen public plan `docs/reports/batch-service-migration-plan-20261030.json` with the pinned recipients from `factory/run.py` and `factory/control-recipient.txt`. The plan validates:
- 64 entries;
- 48 unique archive digests;
- 3,251,961,841 archive bytes;
- 30 archive prefixes and 16 rewrap-key prefixes, with no mixing;
- 45 active entries;
- the only case with no active source is `case-20261017T114431Z-9d2b0e` (`card_bound_absent`, `active_source:false`);
- the divergent checkpoint is inactive;
- `excluded` is empty.

`estimate()` gives 3,644,279,178 bytes of space, 1241 s on the Mac and 509 s on the VM.

---

### Blocker

**B1. Tests named for increment 1 are missing.**
- **Severity:** Blocker
- **Where:** `tests/tools/test_migrate_legacy_checkpoints.py`, against `docs/designs/batch-service.md` L437–439 ("Synthetic tests exercise streaming roundtrip, wrong key, corrupt archive, **failed encrypt**, immutable output replay, dry-run no prompt") and L375 ("**wrong founder/VM recipient**, plan mismatch").
- **Gap:**
  1. **Failed encrypt:** no test makes the `age -e` encoder in `reencrypt` exit non-zero or die. `test_enospc_and_interrupt_preserve_original` patches `write_private`, and that only touches the casekey stage. The branch at `tools/migrate-legacy-checkpoints.py:254-256` ("encryption failed") and its staging cleanup are never run.
  2. **Wrong founder or VM recipient in the plan:** `load_plan` refuses with `plan authority mismatch` (`:69-72`) when `founder_recipient`, `restore_recipient` or `vm_restore_recipient` differ from the pinned values. No test covers this. The existing test covers only a wrong plan digest and a wrong founder *identity* at run time.
- **Impact:** this is the security and authority boundary of the founder command. Both branches are untested, and the design lists them as acceptance tests for this increment. Under ENGINEERING §1, step 4 is not complete against the design.
- **Minimal fix:** add two small tests.
  - Patch `m.subprocess.Popen` so the `age -e … -o` call starts a command that exits 1, or kill the encoder after its first write. Assert `failed == 1`, an empty `output_root`, and the original bytes unchanged.
  - Call `m.load_plan` three times, with the plan's founder, restore and vm_restore recipient each swapped for a throwaway key. Assert `ValueError` each time.

### Major (not blocking; fix recommended)

**M1. Some refusal branches the round-3 clarification and the founder brief call out have no tests.**
- **Where:** `:101-102`, `:409-413`; design L520–533.
- **What:**
  1. "absent card cannot activate": `load_plan` refusing a `card_bound_absent` row with `active_source:true` is never tested. `test_absent_card_never_gets_a_current_binding` checks only what the projected card contains.
  2. "original founder unwrap failure fails that entry with exit1, reports VM-unrestorable and continues": the existing continuation test (`test_failed_entry_does_not_block_a_valid_sibling`) uses two archive rows. No test has a `rewrap_key` row whose old wrapper fails to unwrap.
- **Fix:** one `assertRaises` on `load_plan` with that row flipped to active. Plus a rewrap row whose old wrapper is encrypted to a different key, next to a valid archive row, asserting `migrated=1, failed=1`.

**M2. The real command and the replay test disagree on what a damaged generation does.**
- **Where:** `main` `:449` calls `estimate(plan, root, sha)`. That calls `existing()` and then `complete()` for every row *before* the prompt. `complete()` raises `ValueError` on any damaged generation, and also on one bound to a different plan.
- **Impact:** through `main`, one damaged generation (or a later delta plan touching an already-migrated case) stops the whole command with exit 2, "Invalid plan/preflight". The test (`test_archive_roundtrip_and_restart_keep_originals`, L122–123) calls `run()` directly and asserts that the same situation gives `failed == 1` while other entries continue. Both behaviours fail safe: nothing is overwritten. But the test does not describe the founder-facing command, and the founder-facing summary misreports why it stopped.
- **Fix:** either have `estimate` count a row that raises as pending (so `run` reports it as exit 1), or drive the corruption assertion through `main` and accept exit 2. Pick one and make the test match it.

### Nits

- **N1.** `unwrap` (`:202`): if `public(data)` raises because the unwrapped bytes are not a valid identity, `data` is not zeroed before the exception leaves. Wrap that call in a try/except that zeroes `data` and re-raises.
- **N2.** Dry-run output (`:453-455`) prints 64 per-entry lines and the totals. The design (L286–289) says it should *print* 30 archive prefixes / 48 variants / bytes, 16 rewrap prefixes and the absent-card exception. Those numbers can only be worked out from the lines. A one-line count summary would match the design and the "plain claims first" reading. The rewrap "1 s/key" also sits in the VM line, not the Mac line; it is harmless.
- **N3.** `complete()` does not check that the archive generation's directory name equals `manifest.files['archive.age']` / `record['archive_sha256']`. It holds in practice because only `publish` creates these directories by rename. Adding the check costs one comparison.
- **N4.** For inactive non-absent variants (the 7 inactive finals plus inactive checkpoints and the divergent checkpoint), `projected-card.json` sets `sha256` to that variant's new digest. The only thing marking it non-current is `migration.active_source:false`. Later qualification and the catalog must select by `active_source`; this is noted for increment 2 consumers.
- **N5.** The wrapper calls whatever `python3` is on PATH. `hashlib.file_digest` needs Python 3.11 or later, and `/usr/bin/python3` on macOS is older. That would fail closed with the generic exit 2 message. The other repo `.sh` wrappers do the same, so this is consistent; consider a version check.
- **N6.** On replay, `estimate` and `run` each re-hash every existing generation, about 3.6 GB twice. This is acceptable for a one-off command.

---

### Confirmed against the design

| Design requirement | Where in the code |
|---|---|
| Plan digest checked before anything else; founder and VM recipients pinned from `run.py` and `control-recipient.txt`; `vm_restore_recipient` equals both; founder ≠ restore | `:64-72`, `:442-445` |
| `output_root == mac_root/generations` | `:73-75` |
| One key per case prefix; no mixing of key and archive rows in a case; source digests unique; at most one active per case | `:76-105` |
| Before the prompt: every input opened `O_NOFOLLOW`, regular file and owner checked, size and SHA verified, card bytes and card→case/digest binding verified; descriptors kept open and reused for crypto; source re-hashed after crypto | `:109-135`, `:366-368` |
| Dry run: no TTY, no prompt, no lock, no outputs; disk check fails when space is short (tested) | `:456-460`, test L228–241 |
| Real run: TTY and `age`/`age-keygen` required; `RLIMIT_CORE=0`; umask 077; `GetPassWarning` treated as an error; exactly one hidden prompt (tested); stale `.migration-stage-*` removed only under a non-blocking root lock (tested) | `:438`, `:461-484` |
| Founder public key derived with `age-keygen -y` over stdin and compared to the pin before any decryption (tested, `decrypt` not called) | `:375-376` |
| Identity and keys reach `age`/`age-keygen` only on stdin; never in argv or env (tested by patching Popen, which also covers `subprocess.run`); no plaintext on disk | `:152-170` |
| Streaming: decrypt → relay → encrypt, with hash and count over the decrypted gzip stream, gzip+tar structure checked without extraction, gzip drained to EOF and CRC checked, relay drained, then decrypt exit 0, then encrypt exit 0, then fsync | `:221-258` |
| Staged archive decrypted again by the case key and by the founder to the same SHA and byte count; two stanzas on archive and casekey | `:259-262`, `:334` |
| Founder unwrap of the new casekey equals the in-memory key byte for byte | `:331-337` |
| Partial output after a decrypt failure is discarded (truncated-tail and killed-decrypt tests) | the stage is a `TemporaryDirectory` |
| Rewrap generation `key-<old-key-sha>/` holds exactly casekey, original card, migration.json and manifest; no archive and no projected card; archives de-duplicated by digest; `vm_unwrap_verified:false`; original key and archive bytes unchanged (tested, including a cache-sourced VM-only input) | `:345-348` |
| Archive generation `<case>/<new-ciphertext-sha>/`: original card byte for byte; projected card gets the new digest plus lineage; absent card keeps the old digest, gets `bound_archive:{status:absent}` and `active_source:false` | `:349-365` |
| Publish: manifest, fsync of members and stage directory, refusal if the destination exists, atomic rename, fsync of parent and grandparent; skip on replay only after the manifest, plan, source and card bindings verify; replay re-uses the wrapped key of a finished sibling regardless of plan order, never a fresh key | `:266-323`, `:380-404` |
| Deadline `max(1200, 2+ceil(bytes/262144))`; children killed and reaped in `finally`; SIGTERM/SIGHUP become `KeyboardInterrupt`; key and identity buffers zeroed; fixed error text with no exception detail; exit codes 0/1/2 | `:173-191`, `:480-497` |
| No pointer or `current` file written (tested); originals unchanged (tested) | |
| `.gitignore` covers `sealed/generations/**/archive.age`, including stage paths | |
| Reuse: `atomic_json`, `identifier` and `write_private` reused; the `decrypt_one` Popen/`pass_fds` pattern copied because `decrypt_one` itself extracts. I searched for an existing hash or directory-fsync helper and found none. | |
| `r2_upload`, live sealing, VM, cloud and model calls untouched | |
| No Murphy row claimed closed; `new-batch-service-1` and `-2` stay `open` | |

On zoom-out and YAGNI: the code size is driven by mechanisms the design requires. I found no speculative abstraction.

**Design and interface text in this diff.** These edits are consistent with ENGINEERING §3 as amended in a3bb9dc:
- `batch-service.md` L117–119 and `interfaces.md` §8: no fixed $15, B grants no extension eligibility, and D enforces count, package and progress.
- The appended "Stream D integration assertions": G10 checks tester and reviewer capacity, a shared pool needs two slots, zero capacity on either side creates no worker, waits and charges are reported and de-duplicated on replay, and real provider artifacts are required to close a row.

These add obligations for later increments and need no code in increment 1. They are checked here for consistency only. They are design text that the earlier design reviews did not cover, so the end-to-end review in increment 4/5 has to check them.

### Set aside as later increments (not judged here)

- New-case dual wrapping in `r2_upload.case_recipient` and the manifest wiring (increment 2).
- Money authority, journal and store (increment 2).
- Copying generations to the VM, the VM's own unwrap and full archive decryption proof, R2 PUT/GET, and setting `vm_unwrap_verified`.
- Qualification `--inventory-root` / `--migration-plan`, the atomic catalog-pointer switch, and rollback.
- Holder/restore predicate, launcher, TTL/worker recovery and release migration (increment 3, which needs a reviewed addendum first).
- Codex renewal, status, D hooks, and the G10 double-pool and owner-wait-charge end-to-end assertions (increment 4/5).
- Live practice qualification.
- Closing `new-batch-service-1`/`-2` and the other real-artifact rows (only real VM qualification can close them).
- Any founder-only wrapper created after the frozen survey (needs a new explicit plan; the M2 behaviour matters there).
- Actually running the founder migration.

**Merge condition:** fix B1, then get a full-suite PASS from `uv run --with numpy --with scipy python -B tests/run.py` on the rebased tree.


## Elephant response

B1 fixed: real encoder-exit1/drain test covers the encoder failure branch and
stage cleanup; three separately changed recipient plans fail pinned authority.
M1 fixed: absent+active authority refused; original-wrapper founder failure
allows a different valid case to complete. M2 fixed: estimate treats damaged
outputs as pending so run reports per-entry failure, with actual main/exit1
coverage. N1 zeroes invalid unwrapped key buffer; N2 adds explicit count summary
and correct split crypto time; N3 checks archive directory/content/record digest
agreement; N5 prints Python3.11 preflight requirement. N4 remains an explicit
qualification/catalog obligation, N6 accepted for this one-time command.
No findings rejected. Added D-requested worker delivery/context contract for
review with the follow-up, implementation remains gated to increment2.
