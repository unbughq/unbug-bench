**Verdict: PASS.** The commit range 2077e52..HEAD changes only docs, and all six diff-6 findings are fixed in both designs and the report. Nothing in the new text contradicts the earlier contract. I found no Blocker or Major issues and one Nit. I edited nothing and ran only `git`, `grep` and `sed`.

## How each diff-6 finding was fixed
1. **Root-count caps and lookups (Major 1): fixed.** Both designs now name the cap in `check_manifest` (`batch_money.py:44`) and the one in `key_holder.policy_load` (`key_holder.py:126`). They also name the four places where a derived job is looked up directly:
   - `batch.bind` (`batch.py:138`)
   - `key_holder.serve` (`:559`)
   - `batch_money.channel/authorize` (`:94/121/142/144`)
   - `job_config.install` (`:69`)

   The exact equality check between `manifest.jobs` and `policy.jobs` (`batch_money.py:73`) is explicitly kept, and the frozen config shape is unchanged.
2. **How the settled checkpoint gets out (Major 2): fixed.** Both docs now pick option (a). If the exhausted owner's total was unknown at launch, the worker settles, writes a checkpoint and exits without a model call. B collects and acknowledges that checkpoint, and diagnosis runs on the next ordinary same-owner relaunch. The worker makes this decision from its authenticated restored state and D's projection. B gets no new mode or config field, and "no settlement-only mode" still holds. The test plan in `batch-service.md` now includes this checkpoint, exit, acknowledgement and relaunch sequence.
3. **Priority class (Nit 3): fixed.** An exhausted resume with an unknown total is in class 1 (settlement). One with a known total is in the exhaustion/diagnosis class. A blocked request keeps its FIFO place but eligible requests can pass it. The two docs say the same thing.
4. **Suffix and policy validation (Nit 4): fixed.**
   - Root job names may not end in `-r<digits>`, and that includes `-r01`.
   - Derived ordinals are positive decimals with no leading zeros, so a root J derives J-r1, then J-r2.
   - `check_manifest` in increment 2b will check the exact `replacement_policy` keys and types `{schema:1, enabled:bool}`.
5. **Report wording (Nit 5): fixed.** The line now reads "settle before any further model call", and the report points to diff-6 / interfaces-design-13.

## Earlier contract still holds
- **Conservative rules for an unknown total:** the same owner, the same revision and the same or a lower commitment, with the full old hold kept. New money, revisions, replacements, diagnosis and extensions stay blocked until the total is known. Stale A→B→A refuses.
- **Diagnosis:** it reuses the ordinary same-owner relaunch, and B consumes D's eligibility and pending-diagnosis projection without re-deriving them.
- **Replacements:** one is queued immediately per original that did actual work, a denied reservation counts as zero work, and nothing waits for diagnosis.
- **Limits:** no hidden cap on chain length; only the cumulative money bound, the deadline and normal capacity limit derived work.
- **Gating:** derived and diagnosis work stays disabled behind the concrete 2b proof/API addendum. Nothing is enabled and no Murphy rows are closed.
- **Code:** nothing under `factory/`, `tests/` or `tools/` has changed since 19289c8, so the earlier code PASS and suite result carry forward.

## Finding
**Nit: one more root-only lookup in the holder is not named.** Affects interfaces §"Replacement derivation" and the matching `batch-service.md` paragraph.
- The parenthetical for `key_holder.serve` names only `policy['jobs'][name]` at `:559`.
- The same function has a second lookup at `factory/key_holder.py:538`: `row.get('policy_job') in policy['jobs']`. It runs when the holder restarts and resumes orphaned reservations.
- If it is left as is, every derived job's orphaned reservation is refused as "reserved launch policy or routing changed".
- The docs already name `key_holder.serve`, so a careful implementer would probably find it.
- **Minimal fix:** add `:538` to that parenthetical, or say "all `policy['jobs']` lookups in serve".

Save this as `docs/reviews/batch-service-diff-7.md` and `docs/reviews/interfaces-design-14.md`.

---

Elephant response: PASS accepted. Fixed the remaining nit by explicitly naming orphan-resume policy_job membership along with all policy['jobs'] lookups in serve; no code change. Full suite138scripts0failed, log SHA2565096b1725028449403e174fdd0894eeb894f02e0f13e31de104d5fb49941debc. No code/test/tool changes since19289c8. No rejected findings, VM mutations, enablement or Murphy closures.

