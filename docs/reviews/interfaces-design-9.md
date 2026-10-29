**PASS**

BS3-1 and the round-3 Major and nit findings are closed by the section "Increment 1 rewrap layout and scope (round 3 clarification)" (`docs/designs/batch-service.md:514-539`). Increment 1 is ready to implement. I edited nothing and ran no compilers or cloud commands; the only things I ran were read-only checks against the migration plan JSON.

**BS3-1 is closed:**
- **Layout:** each rewrap gets one fixed directory at `sealed/generations/<case>/key-<old-key-sha256>/`. It holds exactly four files: `casekey.age` (wrapped to founder + VM), `original-card.json` (byte-for-byte), `migration.json` and `manifest.json`. It has no `archive.age` and no projected card.
- **What `migration.json` records:** the plan digest, the old key digest, the digest and size of every entry in `archives[]` (unchanged), the recipients, and the validation booleans.
- **Replay:** an entry is skipped only after its output manifest digests and the old key digest verify.
- **Founder check:** the new wrapper's founder unwrap must equal, byte for byte, the in-memory unwrap of the old wrapper.
- **VM check:** qualification unwraps with the VM's scoped identity and decrypts every listed archive to the end of the file. The projected-card check is explicitly not applied to rewrap entries, which removes the line-358 mismatch.
- **Tests:** the throwaway-key tests cover:
  - a single-stanza key becoming a dual wrapper, with both identities recovering identical bytes;
  - the new key opening the unchanged archive, with the original key and archive bytes unchanged;
  - a VM-only input read from the cache;
  - replay skipping a completed rewrap;
  - `card_bound_absent`: original card preserved, projected `bound_archive.status=absent`, and the entry cannot be activated.

**The design matches the plan JSON** (`docs/reports/batch-service-migration-plan-20261030.json`):
- The 16 `rewrap_key` entries all have the same fields: `key_sha256`, `key_size`, `archives[]` with name, sha256, size and source, `card_path`, `card_sha256` and `local_path`. These are exactly what the layout and `migration.json` need.
- No prefix appears twice, so "one generation per prefix" is well-defined.
- The VM-only entries (for example c7d405) have `local_path` and `card_path` under `~/.cache/unbug-bench/batch-migration-inputs/<key-sha>/`, which matches the cache-input test.
- The `card_bound_absent` entry (9d2b0e) has `active_source:false`, its card points at the absent 4982654d…, and the available checkpoint is 651038ab…, which matches the test.

**The other round-3 findings are closed:**
- **M3-a:** increment 1 adds `sealed/generations/**/archive.age` to `.gitignore`. The ignore file itself is still unchanged, which is expected before code exists.
- **M3-b:** increment 1 migrates only and leaves `case_recipient` untouched. Dual wrapping for new cases ships with increment 2's manifest wiring, before B is enabled. A founder-only key created after the freeze needs a new explicit plan.
- **Nit on line 35:** "priority" is gone; it now reads "job authority from interfaces §8".
- **Nit on lines 263/273:** the stanza count is now supplemental. If the founder unwrap fails, that entry exits 1 and is reported as VM-unrestorable, and every other entry still completes.

**Gates kept:** increment 3 still needs its holder/restore predicate and release-migration addendum reviewed before coding. Increment 4 still needs its pinned Codex refresh probe and scoped credential addendum reviewed (lines 508-512). This PASS does not make either ready. I did not re-review the umbrella design or interfaces §8, and found nothing that contradicts them.

**One small non-blocking nit:** in the plan, `archives[]` lists the same digest once per host, so a prefix on both hosts appears twice. The implementation should decrypt and record each unique digest once. This changes nothing in the design.
