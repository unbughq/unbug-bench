## Verdict: PASS for the code and for the new B→D interface contract. Merging still needs the full suite to pass.

I found no blocking finding in either area. The code passes on its own merits, but the full suite has not finished. `/tmp/unbug-batch-increment1-rebased-tests.log` was still running when I checked (last section `tests/factory/test_silent_limit.py`). It had no FAIL, Error or Traceback so far, and had not yet reached `tests/tools/` (where the migration tests are). Under ENGINEERING §1 step 4, `uv run --with numpy --with scipy python -B tests/run.py` must end in PASS on this rebased tree before the parent merges.

**What I read:** the personas and both standards, ENGINEERING.md, `docs/reviews/batch-service-diff-1.md`, the full 92266d6..HEAD diff, every line of `tools/migrate-legacy-checkpoints.py` and the `.sh` wrapper, the corrections diff since 10301c5, the `run.py` context construction (L2650–2760), and D's `factory/job_authority.py` in t3-21bef30c. I ran no tests, compilers or crypto, and edited nothing.

### Findings from diff-1, checked against the code
- **B1, encoder failure: fixed.** `test_failed_encoder_cannot_publish_and_preserves_original`:
  - It swaps only the `age -e … -o` call for a real child that reads all its input and then exits 1.
  - The real decoder therefore finishes normally, so the code reaches the `encryption failed` branch at `:259-260` itself.
  - The test asserts `failed==1`, that every encoder exited 1, that the output root is empty (the stage is cleaned up), and that the original bytes are unchanged.
- **B1, recipient pins: fixed.** `test_each_recipient_pin_rejects_a_changed_plan` changes `founder_recipient`, `restore_recipient` and `vm_restore_recipient` one at a time, and each is refused at `:69-72`.
- **M1: fixed.**
  - The absent-card row with active set is refused at `:101-102` and tested.
  - A rewrap row whose old wrapper is encrypted to the VM key fails founder unwrap; the valid archive case next to it still migrates (`migrated=1, failed=1`), and no output exists for the failed case.
- **M2: fixed.** `estimate` (`:427-435`) now counts a row whose generation raises as pending. `run` then reports it as a failed entry. The test drives `main` itself with a damaged `archive.age` and gets exit 1, one prompt, and `VM-unrestorable` on stderr.
  - Side effect, which I judge correct: when one generation is damaged, the other pending rows of the same case also fail. The search for a sibling's key (`:402-408`) raises, so the code never creates a second case key for that prefix. This matches the one-key-per-prefix rule, and nothing is overwritten.
- **N1 fixed** (`:202-206`).
- **N2 fixed** (the count summary line at `:470-474`; the 1 s/key now sits in the Mac estimate).
- **N3 fixed** (`:290-292`).
- **N5 fixed** in both the wrapper and `main`.
- **N4** is carried forward as an obligation on qualification and the catalog.
- **N6** is accepted.

### Nits (optional)
- **N7. `load_plan` (`:76-90`)** stops a case from mixing key and archive rows, but does not stop two `rewrap_key` rows for the same case with different old keys. The frozen plan has 16 rows for 16 prefixes, so it is safe today. One `if key and row['case'] in cases` check would enforce the design's "one key per prefix" outright.
- **N8.** The dry-run summary line prints a count of key-rewrap entries, not of distinct key prefixes. The two are equal under N7.

### New interface contract (interfaces §8, "Worker installation and D's context"): shape approved
I checked the contract against D's consumer:
- `read(channel, launch_binding)` needs `c.job_money == c.authenticated_job_config['job_money']` as exact dictionary equality.
  - The contract keeps them as separate objects, and it advances the persisted copy to the holder's verified revision before D admits the case.
  - So equality holds only through an authenticated transition.
  - A tampered or stale `job-money.json` can only make D fail closed (`money_wait`). It cannot grant authority.
- `for_case` compares five context fields, and each has a defined source:
  - `batch_id`, `job_id`, `batch_deadline` and `source_generation` come from the verified RAM binding.
  - `case_id` is already set by `run.py:2662` from `--case-id`/`--resume`, and the installer checks case identity against the file.
- D's attribute names are unchanged, so D can implement against this contract now. Until the installer exists, `for_case` keeps refusing (`getattr` defaults lead to `money_wait`), which is the intended fail-closed state.
- **YAGNI:** one RAM file, two argv flags, one module and one history file. That is the minimum for "current authority from the holder, cumulative state from the checkpoint". There is nothing speculative in it.

The gaps below are things the increment 2 implementation must settle. They do not block approving the contract:
- **G1. Where `install` is called** in `run.py`. On resume it has to run after `c.work` is set and after the restore authentication (`founder_ruling.context` / `authenticate_gates`), and before `record_founder_decisions` or any model call. The contract only says "at context construction".
- **G2. The legacy-checkpoint import record** ("explicit manifest import record and authenticated cumulative-ledger migration") has no format yet. It needs one before any legacy case is first assigned.
- **G3. The installer must check** that the file's `case_id` equals the `c.case_id` derived from argv, and must refuse a missing `--factory-job-config` flag on authenticated batch jobs. The contract implies both but does not spell them out.
- **G4. Tests:** the increment 2 tests must use the real `job_authority.for_case`, not a stub, covering fresh install, a revision bump, a stale revision, and a same-revision replay that is not byte-identical.

### Set aside (not judged here)
- New-case dual wrapping, and the money authority, journal and store (increment 2).
- `job_config.install` and the launcher flags. They do not exist yet, and I do not claim they do.
- Removing `max_cost` emission, plus the real `run.py` and D wiring.
- VM copying and unwrap, R2, `vm_unwrap_verified`, qualification inventory, the catalog pointer switch, and rollback.
- Holder and restore predicate, launcher, TTL and release migration (needs a reviewed addendum first).
- Codex, status, D hooks, and the G10 and owner-wait end-to-end checks (increments 4/5; Codex needs a reviewed addendum first).
- Live practice runs and the real founder migration run.
- Closing any Murphy row. `new-batch-service-1`/`-2` stay open and the diff claims no closures.
- B8 cumulative waste cap: already adjudicated, not reopened.

**Merge condition:** a full-suite PASS on rebased HEAD 8b3ed75. I found no other blocker.


## Validation and carried obligations

Full rebased suite completed: 135 test scripts,0 failed, including13 migration
tests. The reviewed real plan also passed the actual .sh --dry-run with no
prompt or writes (30 prefixes/48 archives/3,251,961,841 bytes,16 rewrap entries,
1 absent binding). No real decryption/VM mutation/row closure.
N7/N8 optional generic-plan hardening deferred: this reviewed digest-pinned plan
has exactly one rewrap per prefix; every future plan is separately reviewed.
G1–G4 and inactive-generation selection are mandatory increment2 obligations;
installer and VM qualification still do not exist. No findings rejected.
