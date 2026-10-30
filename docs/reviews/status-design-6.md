PASS

# Goldfish design review 6: docs/designs/status.md (de70d12..12539f9)

I reviewed as a fresh read-only subagent using the zoom_out, design_critic and implementation_readiness personas in Mode: REVIEW. I applied the heilmeier and implementation-readiness standards. I read only `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`. I made no edits, live queries, decryption or cloud calls.

**PASS.** The blocker and all three majors are fixed. The fixes introduce no new contradictions, and I found no new blockers or majors.

**Prior findings**

- **Blocker 1 (core pending vs launch pending vs no entry): fixed.**
  - Line 131 says every entry accepted by `_load` is stopped and uses its own snapshot. This fits the code: `factory/batch_service.py:108` admits only `state == 'pending'`, which is the collected state written at `:231`.
  - Lines 131–133: a root or recorded derived job with no entry goes into the `not collected` bucket. It fires neither `worker gone` nor `launch stuck`. The bucket is also added to the counts line at line 43.
  - Lines 17–21 and 151–143 make clear that launched, pending and failed belong to the future holder view. Production must not infer them. So the resume-row double reading is gone: the core has no umbrella rows.
- **Major 2 (second lenient parser): fixed.**
  - Line 128 reuses `_load` and `resolve_job`, with an explicit `journal.json` existence check. This covers `_load`'s silent default at `:91-93`.
  - Lines 135–136 refuse the umbrella fields.
  - Line 130 bans `batch_money.locked`. That ban is correct: `batch_money.py:110-113` runs `mkdir` and opens the lock with `'a'`.
  - Taking a shared `flock` on an existing lock opened read-only is valid alongside the writer's `LOCK_EX`.
  - `batch_money.manifest` and `batch.verify` are read-only, so the "writes nothing" claim holds.
- **Major 3 (contradictory card sources): fixed.**
  - Source 4 at lines 27–29 and the adapter text at lines 147–148 now agree. Status uses only the scorecard pinned by the snapshot, with no flat fallback, "even with a matching ciphertext generation".
  - The case and release must match. This mirrors `_snapshot` and `_card` at `:159-200`.
  - Source 1 no longer claims core `launched` or `failed` states.
- **Major 4 (real cards lack the release field): fixed.**
  - Lines 164–166 split the tests. Classification and rendering run on unmodified real cards. Release, case and manifest binding run on separate authored snapshots, and the test discloses this.
  - This is consistent with lines 97–105.
- **Nits 5–8: all addressed.**
  - Calls must be a nonnegative int, never a bool; anything else renders `?` (line 180).
  - The known-stop list is enumerated, including `provider_limit:*`, and free-form text is never echoed (lines 181–187).
  - The pointer must be a regular non-symlink file with exactly `{generation, manifest_sha256}`, and its case must match the filename (lines 120–122).
  - The one-page inventory limit is disclosed as a known limit (lines 152–154).
- **Original request: still met.**
  - Line 56: `calls N` or `calls —`, with no denominator and no near-limit rule on call count.
  - Line 76's near-limit rule covers only spend and rounds.
  - Line 169 tests a calls value above the historical max with no alert.
  - The PASS4 rendering, the sealed/rejected definitions, the 5 h rule, `boat unreadable` and the deferred wallet rule are unchanged.

**New nits (optional)**

1. **Lines 72 and 77 (rule table).** These rules use the words `launched` and `pending`, and every core entry literally stores `state: "pending"`. Lines 19–21, 131 and 141 already say this is not a launch state. A parenthetical in the table, such as "(holder lifecycle view only; core `state: pending` is collected)", would remove the last chance of misreading it.
2. **Lines 129–130.** The text doesn't say what happens when `journal.json` exists but the `lock` file is missing. The general rule at line 149, "absent sources become unreadable", implies the batch shows unreadable. Saying so in one clause would make that explicit.
3. **Line 133.** A batch before its first collection has no journal, so it shows as unreadable rather than as all jobs not collected. This fails closed and matches what review 5 asked for. Consider noting it as expected behaviour so the operator isn't alarmed.
4. **Lines 117–126.** The core writes no `current/` pointers, so any case with a second generation (a resume) shows unreadable until the dispatcher publishes a pointer. The design discloses this at line 125, and it is harmless while `DIAGNOSIS_ENABLED = False`. I note it only as a known staged limitation.

**Standards check**

- **Heilmeier:** the objective, the limits of the current core, the cost (one read-only module, no spend), the risks and the exams (lines 93–105 and 164–171) are all stated.
- **Implementation-readiness:** the target files, the reuse seams, the lock mode, the selection rules, the stop list, the calls typing and the test split are all fixed. No design choices are left to the implementer.

I made no edits. If you want the record kept, save this verbatim to `docs/reviews/status-design-6.md`.

---

Elephant resolution: PASS accepted. Table rules apply to normalized holder
lifecycle views only. Missing lock or journal reports batch unreadable, including
before first collection. Multiple generations without a pointer also remain
unreadable. These staged limitations are retained explicitly; no production
running view, enablement, spend or Murphy closure is claimed.

