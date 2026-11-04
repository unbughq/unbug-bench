# Goldfish design review 3: authenticated bytes (diff-10 Codex follow-up, re-review)

Reviewer: fresh goldfish with no history, run as a separate local `claude -p` process (model
claude-opus-5-5, the same model family as the writer, because no other family was available
to this job). It had read-only tools: Read, Grep, Glob, and git show/diff/log. Personas: zoom_out,
design_critic and implementation_readiness. Standards: heilmeier-standard.md and
implementation-readiness-standard.md. Mode: REVIEW. Scope: the "Authenticated bytes (diff-10,
Codex)" paragraph at WIP commit `5cb5fb6` (after the design-2 fixes), both regression tests, and
whether the design-2 blockers were fixed. Its reply is reproduced verbatim below. The elephant's
dispositions follow it.

---

**Verdict: PASS.** No blocking findings remain. I left four nits.

I could not run the tests: the sandbox wanted approval for the command. So the pass and fail claims below come from tracing each subtest through the code by hand, at 7de75d9 and under the described change.

**Problem statement.** It is correct. On both paths, `prepare` hashes one read of the ciphertext (`factory/statement_round.py:103` for history, `:114` for candidates). Then `replace_rejected` reads the file again at `factory/registry.py:109`, and `reserve` reads it a third time at `:51` (called from `:132`). `transfer.py:98` replaces the file in between. The interleaving the design describes (`docs/designs/registry-pending-promotion.md:108-117`) is real on both paths. On 7de75d9 both paths release a historical-only entry when `bound` is true (`registry.py:123-124`).

**Smallest shared fix.** Passing the same bytes to `import_historical`, `replace_rejected` and `reserve` removes reads rather than adding guards, and it covers both paths. The candidate path also gets a digest check, `card.statement_sha256 == digest` (`:125-130`). With it, the candidate's digest, binding and rejected list all come from one parse of the card. That closes the gap where the card and the ciphertext are both swapped. The history path already reads the card once (`statement_round.py:95-105`), so it needs no extra rule.

**Properties preserved.**
- **Ciphertext preservation:** promotion still keeps the stored ciphertext (`registry.py:65-66`, `:89-93`).
- **Rejection authentication:** the conditions at `registry.py:120-124` are unchanged; only where the `bound` input comes from changes.
- **Reservation fencing:** the `expect` check (`registry.py:127-128`, `:206-208`) is unchanged.
- **Duplicate-screening visibility:** predecessors are still computed from every live entry (`registry.py:79-80`).

The design states all of this at `:131-134`.

**Earlier review (design-2).**
- **B1 (card read twice):** fixed. The design adds the digest rule at `:125-130`. `test_candidate_card_must_name_the_offered_digest` (`tests/factory/test_registry_promotion.py:285`) fails on 7de75d9: `bound` is true there, d1 is released and c3 is stored under d2, so no `ValueError` is raised. Under the change, `bound` is false, so `reserve` refuses with "different content" (`registry.py:74-75`) and the entry is left unchanged.
- **B2 (assertion that could never pass):** fixed. The `objects/` non-existence check was dropped. The oracle is now the entry check `(d2, sha(c2))`.

**Tests.** I traced all four subtests of `test_release_and_reserve_consume_the_authenticated_bytes` (`:249`): history and candidate paths, each with the swap hooked at `replace_rejected` and at `reserve`.
- **On 7de75d9:** each subtest stores c3 under d2, so the entry assertion fails.
- **Under the change:** the swap has no effect because the bytes were already read. `swapped == ["case-py"]` still holds, and each subtest stores c2.
- **Determinism:** the interleavings are authored and deterministic, and the test asserts the three ciphertexts are distinct.
- **Count:** the file has 21 tests, matching `:103`.

**Carve-out.** I checked base (`ea04d84^`). Its `replace_rejected` releases a complete screening or building entry using the rejected list from `prepare`'s own fresh read of the card, and `reserve` reads the path again. So "a TOCTOU base also has" is accurate. The change only narrows it, because the bytes are now read once.

**Murphy.** Correct. This race was found in review, not seen in a real run, so `docs/ENGINEERING.md` §2 requires no new row. new-registry-pending-promotion-1 correctly stays open with no real-writer evidence (`:149`).

### Findings

1. **NIT: the carve-out names only one of the two swaps that still reach base's unbound release.** `registry-pending-promotion.md:142-148` describes a swap of "the ciphertext alone". A swap of both the card and the ciphertext against a complete screening or building entry also falls through to base's unbound release. The candidate's `rejected` list comes from `statement_round.py:112`, which is not gated on `bound` or on the new digest check. In that case base releases d1 and stores c3 under d2. That is the same as base, and the worker's own check, "verifies the restored statement against the reservation" (`statement_round.py:69-70`), catches it. Say so in one sentence, so a reader does not take "ciphertext alone" to be the whole residual exposure.

2. **NIT: the design does not say where the single read happens.** `:118-124` says `prepare` "reads each ciphertext once" but not where. It could be when building `ciphertexts` (`statement_round.py:86-88`), or just before `bound` is computed (`:103`, `:114`). Either is correct, because `bound` compares the card with whatever bytes are held. Naming one spot, for example "replace the path values in `ciphertexts` with their bytes", removes a small choice the implementer would otherwise make.

3. **NIT: one assertion in the new test cannot tell the two cases apart.** `tests/factory/test_registry_promotion.py:278` checks that the entry's object holds c2's bytes. Every retained ciphertext, c2 and c3 included, is already an object in the copied registry, and the file is named by its digest. So this assertion only confirms what the entry check (`:277`) already proved. It is harmless; removing it or noting this would help a future reader.

4. **NIT: the second test models the outcome of the race, not its timing.** `test_candidate_card_must_name_the_offered_digest` hands `prepare` a card naming d3 together with the caller's d2. It never shows the card being swapped after the caller read it. That is enough to prove the new digest rule, and the test's comment says it is authored state. The design calls both tests "interleavings" (`:136-141`), and "authored state" would describe this one more exactly.

---

## Elephant dispositions

PASS, with no blocking finding open. All four nits were taken before implementation:

1. **Taken.** The carve-out now says a swap of both the card and the ciphertext also reaches base's
   unbound release for a complete screening or building entry, because the candidate `rejected`
   list is not gated on `bound`. It names the worker's own verification (`statement_round.py:69-70`)
   as the remaining check, as on base. This is still a carve-out, not a fix.
2. **Taken.** The design now says where the single read happens: once per case, in the history loop
   and in the candidate loop, before `bound` is computed.
3. **Taken.** The redundant object-bytes assertion was removed. The entry check `(d2, sha(c2))` is
   the oracle.
4. **Taken.** The design now calls the second test the authored state the race leaves behind, and
   the first a hooked interleaving.
