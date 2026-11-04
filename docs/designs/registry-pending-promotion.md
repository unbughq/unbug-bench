# Registry: pending candidate promotion (Murphy row 7)

**Problem.** `statement_round.prepare` imports every collected statement that is not
this wave's candidate as historical (`complete=false`, status `completed`). A candidate
of another handoff that is still pending is therefore imported as history first. When
its own handoff runs, `Registry.reserve` finds the existing entry and returns it
unchanged (digest known) or raises "different content" (digest unknown), so `export`
refuses it as historical-only. Reproduced on a copy of the retained public registry
`sealed/statement-registry` (37 historical-only entries): `reserve` and
`replace_rejected` give `complete=False`; `export` raises "historical-only".

**Change (`factory/registry.py`, ~12 lines).** In `reserve`, under the existing lock, a
non-historical call on a non-released, `complete=false` entry is a promotion when the
statement digest equals the stored one, or the stored digest is None and the
ciphertext digest equals the stored one. Promotion keeps the stored ciphertext, then
takes the normal new-reservation path: `expected_revision` check, predecessors
recomputed from all non-released entries, fresh reservation token, `complete=true`,
status `screening`. `replace_rejected` only treats a *complete* entry as a conflicting
previous; historical-only mismatches still raise in `reserve`.

**Why not "import only genuinely historical" (the other half of row 7's fix).** The
registry exists so later workers screen against earlier pending candidates
(`registry.py` docstring), and `same_worker_handoff` requires every collected
statement in the attestation. Pending candidates must stay visible, so the import side
stays and promotion is the fix. Row 7's first sentence is superseded.

**Mutual predecessors (accepted).** A pending candidate B imported as history is already
in the predecessor set of every later reservation (A). On promotion B's predecessors are
recomputed from all live entries, so A and B screen against each other. For a
near-duplicate pair both may be rejected and reselect. Over-rejection is the safe
direction for duplicate screening, and before this change B could not be admitted at
all. The tests assert both directions explicitly.

**Promotion guards.** Only entries with status `completed` and `complete=false`
(what `import_historical` produces). A missing stored ciphertext object refuses.

**Known remaining sub-case (not fixed): new-registry-pending-promotion-1.** A wave that
imports a pending candidate as history under a statement digest the registry has since
replaced (candidate reselected before its handoff) raises "different content" and fails
that wave. Same mechanism class, different cause; it needs its own design.

**Unchanged.** Mismatched statement or ciphertext, released entries, `historical=True`
calls, and historical-only entries nobody reserves still refuse to export. Screening
is untouched: a promoted candidate is compared against every other live entry.
Complete entries remain idempotent.

**Deletes.** Nothing; adds no new status, file or caller change.

**Tests.** `tests/factory/test_registry_promotion.py` (real registry/ciphertext copy,
threaded interleaving, `statement_round.prepare` two-wave flow, kept ciphertext, missing
object, negatives, stale revision). Fails on parent, passes on change.

**Murphy rows.** Row 7: implemented, and regression-tested against the retained real
registry and ciphertext through `statement_round.prepare`; not deployed or live-proven.
The register is not edited by this branch (root owns it); root may set row 7 `closed`
with `tests/factory/test_registry_promotion.py` as `Closed by` at merge.

## Addendum: reselection between history snapshot and handoff (new-registry-pending-promotion-1)

### Current rule

This subsection is the rule. The paragraphs after it are the design history and the review
follow-ups that led to it. Where they disagree, this subsection wins.

**Release.** `Registry.replace_rejected(case, digest, ciphertext, rejected, *, historical, bound)`
releases the previous entry only when all of these hold:
- it is not released, its digest is known and differs from the offered digest, and that digest
  is listed in `rejected`;
- its stored ciphertext differs from the offered bytes;
- a complete entry is in `screening` or `building`, and a historical-only entry is `completed`
  and `bound`.

`bound` means the caller's own card carries a `statement_cipher_sha256` equal to sha256 of the
offered bytes.

**Fencing.** The release is `transition(..., "released", expect=(status, digest, cipher))`,
checked under the lock. A changed entry raises "stale reservation", which is retried once
from a fresh read.

**Everything else goes to `reserve`.** The result is base's answer (return, promote, or refuse)
with two deliberate exceptions on the candidate path:
- invalid digest or non-age bytes are refused before any release;
- identical stored bytes under a new digest are refused, where base released and bound them
  (diff-5 B1).

**Callers.** `statement_round.prepare` routes digested history imports through
`replace_rejected(..., historical=True, bound=bound)`. It reads the history card's
`rejected_candidates` only when the card is bound and the list is well formed (a list of at most
3 dicts); otherwise it passes `[]`. A row without `statement_sha256` yields None, which never
matches. Digestless history still uses `import_historical`. Candidates
call `replace_rejected(..., bound=bound)` with their own card's list.

**Accepted gaps.**
- Release and reserve take the lock separately. A reservation for another case that lands in
  between omits this case. Pairwise screening still holds, because this case's later
  reservation recomputes its predecessors.
- A stale wave can resurrect the old digest in that gap. This only over-screens, and the next
  authenticated import releases it again.
- A failed `reserve` after a release leaves the slot released until it is retried.
- Unchanged from base: a candidate whose entry is in screening or building, with a legacy own
  card that has no cipher binding.

**Tests.** `tests/factory/test_registry_promotion.py` (21 tests). **Murphy.** The row stays open.
No retained real card carries `statement_sha256`, `statement_cipher_sha256` or
`rejected_candidates`, so the new branch runs only on hand-authored cards over the real registry
and ciphertext.

**Authenticated bytes (diff-10, Codex).** This is part of the rule.
- *Problem.* `prepare` authenticated one read of a collected ciphertext (`bound`, against the
  card's `statement_cipher_sha256`), then `replace_rejected` and `reserve` each reopened the
  path. Collection replaces that file with `os.replace` (`transfer.py:98`), so the bytes that
  decide a release, and the bytes that get stored, could differ from the bytes the card bound.
  Interleaving: Y's card binds c2 under d2, rejecting d1. The registry holds d1/c1 historical-only.
  `prepare` reads c2, so `bound` is true. Collection then swaps in c3. `replace_rejected` reads c3
  (differs from c1), so d1 is released, and `reserve` stores c3 under d2. Swapping between the
  `replace_rejected` read and the `reserve` read has the same result. Both the history path and the
  candidate path reach this, because both now release a historical-only entry on `bound`.
- *Change.* `prepare` reads each ciphertext once per case, in the history loop and the candidate
  loop, before it computes `bound`, and holds those bytes. It computes `bound` from those bytes and passes
  the same `bytes` to `import_historical`, `replace_rejected` and `reserve`. `reserve` and
  `replace_rejected` accept `bytes` (an `isinstance(ciphertext, bytes)` check) or anything else,
  which is read once with `pathlib.Path(...).read_bytes()`. The age-magic and digest checks run on
  those bytes, and `replace_rejected` passes its bytes on to `reserve`. The CLI still passes paths.
  `search_receipt` is left reading its path once: it is outside this finding. Nothing after
  authentication reopens the ciphertext.
- *One card read per decision.* The card is replaced by collection too (`collect.sh`), and the
  candidate digest comes from the caller's own earlier read of it. On the candidate path, `bound`
  therefore also requires the card that `prepare` read to name the offered digest
  (`card.statement_sha256 == digest`). The digest, the binding and the rejected list then come from
  one parse, as they already do on the history path. A swapped card that names another digest binds
  nothing, so it releases no historical-only entry.
- *Preserved.* Promotion still keeps the stored ciphertext rather than the offered bytes, the
  `transition` fence is unchanged, and predecessors are still computed from every live entry. Only
  where the bytes come from changes, plus the digest condition on candidate `bound`.
- *Deletes.* The second and third reads of the path.
- *Tests.* `test_release_and_reserve_consume_the_authenticated_bytes` runs the history and candidate
  paths, swapping the file (`os.replace` of another retained ciphertext) at the entry to
  `replace_rejected` and to `reserve`. `test_candidate_card_must_name_the_offered_digest` hands the
  candidate path a swapped card and ciphertext that bind c3 to d3 under the caller's d2. Both are
  AUTHORED and deterministic: the first is a hooked interleaving, the second the authored state that
  race leaves behind. Both fail on 7de75d9 (c3 stored under d2), and after
  the fix they pass: c2 is stored, or the swapped pair refuses with "different content" and leaves the
  entry unchanged.
- *Left as is (a TOCTOU base also has).* `prepare_restore` checks the candidate's
  `statement_cipher_sha256` on its own read, then `prepare` reads again. A swap of the ciphertext
  alone in that window yields `bound=false`, so no historical-only entry is released. A complete
  screening or building entry still takes base's unbound release and stores the newer bytes, as on
  base. The same holds when the card and the ciphertext are both swapped, because the candidate's
  `rejected` list is not gated on `bound`. In both cases the remaining check is the worker's own
  verification of the restored statement against the reservation (`statement_round.py:69-70`), as on
  base. Refusing in `prepare` whenever a candidate card carries a non-matching binding would close
  the window. It would also add a refusal for `coordinator_inventory.prepare_admission`, which calls
  `prepare` directly without base's check. That is a base-behaviour decision, so it is not made here.
- *Murphy.* new-registry-pending-promotion-1 stays open. This adds no real-writer evidence.

### History

**Problem.** A pending candidate Y reselects (c1 rejected, c2 selected) after the registry
last saw c1, either reserved by Y's earlier handoff or imported as history by another
wave. `statement_round.prepare` then imports Y's c2 as history for another wave X;
`reserve` raises "different content" and X's whole wave fails. Y's own handoff fails the
same way when c1 is historical-only (`replace_rejected` only released screening/building
entries).

**Change.** `Registry.replace_rejected` gains `historical=False`, and its release rule
covers a historical-only previous entry with a known digest: release only when that digest
is in the card's `rejected_candidates` (the same authentication as before; a None digest
never matches). `prepare` routes non-candidate history imports with a known digest through
`replace_rejected(..., historical=True)`, reading the history card's rejected list with the
existing bound of 3. With no digest it still calls `import_historical`. Everything after
the release is the existing `reserve` path, so c2 is stored, stays visible to X and every
later reservation, and Y's own handoff promotes it by the row 7 rule.

**Unchanged / refuses.** Unlisted or mismatched previous digest still raises "different
content" and leaves the existing reservation alone; screening visibility is never removed
for a candidate not named rejected by its own card; no reservation is reset otherwise.
Already-reserved candidates keep their fixed snapshot (later entries are not retrofitted).

**Tests.** `test_registry_promotion.py`: two-wave `prepare` for both starting states
(reserved, history), Y's own handoff after, and unauthenticated reselection refusals.
Fails on 271f4a87, passes now. **Murphy.** Fixes new-registry-pending-promotion-1 locally (row stays open, see diff-5 follow-up);
not deployed or live-proven; register untouched.

**Review follow-ups (diff-3, published as diff-2 on the follow-up branch).** `replace_rejected` validates digest and ciphertext before any
release and retries once on a concurrent "stale reservation" (the decision stays unlocked;
every race ends in success, retry or refusal). Legacy digestless historical entries cannot be
replaced by a reselected candidate (a None digest never authenticates a release); all 37
retained ones are finished cases. Tests add the direct own-handoff release and
malformed-input-before-release cases.

**Review follow-ups (diff-5).** The release is now a fenced compare-and-release:
`transition(..., expect=(status, statement_sha256, cipher_sha256))` re-checks under the lock
the values the unlocked decision read, so a same-token change (for example building →
completed) raises "stale reservation" and the single retry re-reads and refuses. This
replaces the diff-3 claim above, which did not cover that race. A release is also refused when
the offered bytes equal the stored ciphertext under a different digest (stale collected
ciphertext); `prepare` checks a history card's `statement_cipher_sha256` when present, as the
candidate path does. A history card's `rejected_candidates` is read only when it carries a
digest, and a malformed list authenticates nothing (the import then refuses or succeeds as
before instead of failing other waves). **Known gap (accepted):** release and reserve take the
lock separately, so a reservation for another case landing in between omits this case. Pairwise
screening still holds because this case's own later reservation (promotion or reserve)
recomputes its predecessors and includes that case. **Murphy:** new-registry-pending-promotion-1
stays open. No retained real card carries `statement_sha256`/`rejected_candidates`, so the
new branch runs only on hand-authored cards over the real registry and ciphertext.

**Review follow-ups (diff-6).** This supersedes the diff-5 sentence about `statement_cipher_sha256`.
A history import authenticates a release only when its card binds the collected bytes, meaning
`statement_cipher_sha256` is present and equals their sha256. A card without that binding (the
legacy shape, or a new seal beside an older card) authenticates nothing: `replace_rejected`
gets `rejected=[]` and returns or refuses exactly as base did, so it never fails the wave on
its own. Another seal of a rejected statement therefore cannot take the new digest. The
byte-identity guard stays as a second check. Gap sub-case (accepted): while a slot is
released, a wave holding a stale history card can re-import the old digest. That only
over-screens, and the next authenticated import refuses loudly instead of binding anything.
Asymmetry (unchanged from base): the candidate path still raises on a malformed own-card
`rejected_candidates`, because that card belongs to the case being handed off, not to
another wave.

**Review follow-ups (diff-7).** This corrects the diff-6 claim that the candidate path was unchanged: it
too reached the new historical-only release. The rule now lives in `replace_rejected`, so it
applies on both paths. A historical-only previous entry (never vouched for by a reservation of
this case) is released only when the caller passes `bound=True`, meaning its own card's
`statement_cipher_sha256` equals sha256 of the offered bytes, and only when the entry is
`completed` (never `known_public`). `prepare` computes `bound` for history and candidate cards.
Complete screening/building entries keep base behaviour. A pre-existing hole is left as it
was: a candidate from the reserved state with a legacy own card. Closing it would change base
behaviour and needs its own decision. More of the known gap: if `reserve` fails after a
release (a resurrected old digest, a corrupted object), the case stays released until it is
retried. Only content its own card named rejected has left screening, so this is safe.

**Review follow-ups (diff-8): the final rule.** `replace_rejected` releases only when one
predicate, `authenticated`, holds:
- the previous digest is known, differs from the offered one, and is listed in the caller's own
  card's `rejected_candidates`;
- the stored ciphertext differs from the offered bytes;
- a complete entry is in screening or building, and a historical-only entry is `completed`
  and `bound`.

When it holds, the release is fenced. Every input then goes to `reserve`, which gives base's
answer: return, promote, or refuse. `replace_rejected` never refuses on its own. This
supersedes the earlier follow-ups wherever they describe a refusal inside `replace_rejected`.
A history import whose bytes are stale (a new card beside the old c1) therefore leaves the
entry unchanged and does not fail the wave, exactly as on base. Correction to diff-6: if a
stale wave resurrects an old digest in a released slot, the next authenticated import
releases it again. It does not refuse.
