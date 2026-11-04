# Goldfish design review 2: authenticated bytes (diff-10 Codex follow-up)

Reviewer: fresh goldfish with no history, run as a separate local `claude -p` process (model
claude-opus-5-5, the same model family as the writer, because no other family was available
to this job). It had read-only tools: Read, Grep, Glob, and git show/diff/log. Personas: zoom_out,
design_critic and implementation_readiness. Standards: heilmeier-standard.md and
implementation-readiness-standard.md. Mode: REVIEW. Scope: the "Authenticated bytes (diff-10,
Codex)" paragraph of `docs/designs/registry-pending-promotion.md` at WIP commit `3da05d8`, plus
the regression test added before the fix. Its reply is reproduced verbatim below. The elephant's
dispositions follow it.

---

**Verdict: FAIL**

I reviewed in Mode: REVIEW, using the zoom_out, design_critic and implementation_readiness personas against heilmeier-standard.md and implementation-readiness-standard.md. I could not run the test file because the command needed approval, so the test finding below comes from reading the code and checking the retained registry on disk.

The problem statement is correct. The interleaving it describes is real at `factory/statement_round.py:103,107,115`, `factory/registry.py:51,109` and `factory/transfer.py:98`. Reading the ciphertext once and passing the same bytes on is the right minimal shape: it deletes code rather than adding guards. Two problems block it.

1. **BLOCKING: the candidate path still checks the bytes against a card read twice.** The design says "Nothing after authentication reopens the file", but on the candidate path the scorecard is reopened as well as the ciphertext.
   - **Where the digest comes from:** the `digest` passed in as `candidates[case]` comes from the caller's card read: `prepare_restore` at `factory/statement_round.py:42,49`, or `factory/coordinator_inventory.py:148-150`.
   - **Where `bound` comes from:** `prepare` reads the card again at `factory/statement_round.py:110-111`, and `bound` and `rejected` come from that second read (`:112,114`).
   - **Why this matters:** collection replaces `*.scorecard.json` through the same per-file `transfer.py` `os.replace` (`factory/collect.sh:75,78`). So the card and the ciphertext can each be swapped independently.
   - **Interleaving:** the caller reads card G2 (d2, binds c2). Collection then swaps in the c3 ciphertext and card G3 (d3, binds c3, rejected [d1, d2]). `prepare` reads G3 and c3, so `bound` is true and `rejected` contains d1. `replace_rejected` releases the historical-only d1 and stores c3 under d2. No card ever bound c3 to d2, which is the same defect the external finding describes.
   - **History path is fine:** there the digest, the binding and the rejected list all come from one card read (`:95-105`).
   - **Smallest shared fix:** on the candidate path, `bound` must also require `card.get('statement_sha256') == digest`. Better, read the card once and take both the digest check and the binding from that one parse. The design should state this, and the test should cover it.
   - **Effect on the carve-out:** the "Left as is" paragraph argues that a swap after `prepare_restore` "yields `bound=false`". That only holds if the card is not swapped too, so the carve-out needs this fix to be true.

2. **BLOCKING: one assertion in the new test can never pass.** `tests/factory/test_registry_promotion.py` (in the new test, after `kept = self.entry()`) asserts that `reg/objects/<sha(c3)>.age` does not exist.
   - c3 is `sorted(SEALED.glob(...))[4]`, which is `sealed/case-20261017T125556Z-18681d.statement.age` with sha `808a6a13…62cc`.
   - That object is already in `sealed/statement-registry/objects/`, which `setUp` and each subtest copy into `tmp/reg`. I confirmed it with `ls … | grep -c` → 1.
   - So the assertion fails both before and after the fix. That contradicts the design's claim that the test "passes after the fix (c2 stored, c3 never enters `objects/`)".
   - **Fix:** drop that assertion and rely on the entry check (`cipher_sha256 == sha(c2)`). Alternatively, pick a c3 whose digest is not among the retained objects, and assert that before the swap.
   - **The other oracles are sound:** the authored hook at the entry to `replace_rejected` / `reserve` gives a deterministic interleaving, and the entry and snapshot assertions distinguish before from after.

3. **NIT: the carve-out is worded more strongly than it needs to be.** "Closing that would change base behaviour" overstates it.
   - `prepare_restore` already refuses a card whose `statement_cipher_sha256` does not match the ciphertext (`factory/statement_round.py:71-73`).
   - `prepare` could apply the same check to the bytes it already holds: refuse when the card carries `statement_cipher_sha256` and `bound` is false.
   - That would only refuse inputs base already refuses when its own check wins the race, and it would close the window for complete screening or building entries too.
   - If you keep the carve-out, say "a TOCTOU base also has", not that closing it would change behaviour.

4. **NIT: implementation readiness.** The design should say exactly how a call tells bytes from a path. For example: `isinstance(ciphertext, (bytes, bytearray))` means bytes, anything else is `pathlib.Path(...).read_bytes()`, and the age-magic and digest checks run on those bytes.
   - It should also say that `import_historical` passes the bytes through unchanged.
   - It should say whether `search_receipt` (`factory/registry.py:136`) is deliberately left reading a path. It is outside this finding, but a sentence avoids the implementer having to decide.

5. **NIT: two preserved properties are unstated.** The design keeps ciphertext preservation (`factory/registry.py:65-66,91`), fencing (`:127-128`, the transition's `expect`) and duplicate-screening visibility (`:79-80`), because only where the bytes come from changes.
   - It does not say so explicitly.
   - Add one line confirming that `promote` still keeps the stored ciphertext rather than the offered bytes, and that the `transition` fence is unchanged.

6. **NIT: the Murphy statement is correct.** This is a review-found race, not a failure seen in a real run, so no new row is required (`docs/ENGINEERING.md` §2). new-registry-pending-promotion-1 correctly stays open with no real-writer evidence. The "(20 tests)" count is consistent with the one test added.

---

## Elephant dispositions

1. **BLOCKING, fixed.** Confirmed. The candidate digest comes from the caller's own card read
   (`prepare_restore`, `coordinator_inventory.prepare_admission`), and `prepare` reads the card
   again. The design now requires candidate `bound` to also have `card.statement_sha256 == digest`,
   so the digest, the binding and the rejected list come from one parse. New test:
   `test_candidate_card_must_name_the_offered_digest`, which fails on 7de75d9 ("ValueError not
   raised"). The carve-out now depends on this rule.
2. **BLOCKING, fixed.** Confirmed: all 45 retained ciphertexts are already objects in the retained
   registry. The assertion was dropped. The test now checks that the entry's object holds c2's
   bytes.
3. **NIT, taken.** The carve-out is now worded as "a TOCTOU base also has". It also names the reason
   it is left alone: refusing in `prepare` would add a refusal for
   `coordinator_inventory.prepare_admission`, which base does not have.
4. **NIT, taken.** The design now states the `isinstance(ciphertext, bytes)` rule, that `import_historical`
   passes bytes through, and that `search_receipt` is left as is.
5. **NIT, taken.** The design now has a "Preserved" bullet covering promotion keeping stored bytes,
   the unchanged fence, and predecessors.
6. **NIT.** No change needed.

Re-reviewed in `registry-pending-promotion-design-3.md`.
