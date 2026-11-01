**FAIL: 1 blocker, 0 majors, 6 nits.**

The spending changes and the frozen legacy disposition are correct, tested and honestly scoped. The blocker is in the runtime legacy check. It treats "the card has no `diagnosis_state`" as meaning "pre-new-schema case". But the current runner only writes `diagnosis_state` when a case is exhausted. So the check would permanently retire normal new-schema cases at their next resume, including every provider-wait resume.

---

# Goldfish diff review: `stream-b-blocker-resolution` (diff 1)

Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`. Worktree `t3-ded79ec5`, range `9b9e5e0..db58dcd`, reviewed against `docs/designs/stream-b-blocker-resolution.md` and design reviews 1 and 2.

What I read:
- the changed runtime: `bin/boat-spend`, `factory/batch_service.py` (`retire_legacy`, `plan`) and `factory/batch_holder.py` (`_source`, `reserve`, `_post`, `dispatch`, the provider-wait scan);
- `factory/diagnosis.py` (`record_exhaustion`, `exhaustion`, `_state`) and `factory/run.py` `finalize_accounting`;
- `factory/deployment_inventory.py` `scan_ledger`;
- all changed tests, the report, the retirement JSON, the suite JSON and log, the supersession notes and the diff-attempts record;
- `docs/designs/batch-service.md` §§ around lines 925–935 and 1326–1334.

## Verdict: FAIL

## What I checked and found sound

**Unknown liability is never released.**
- `--finish` and finish-replay both keep the ledger row, set `status=finished` and `actual_spend_usd=null`.
- Nothing deletes or zeroes a row, and `boat-spend` is the only ledger writer (`deployment_inventory.py` only reads it).
- Any other row refuses admission, whether reserved, finished or `reconciled_expired`, and whether or not it has expired. An injected `actual_spend_usd: 0` grants nothing.

**Refusal order and replay match the design.**
- The order is: completed reservation, then changed envelope, then unsettled liability, then estimate against balance/cap. The first three refuse without a billing call or a ledger write.
- On refusal, an existing spend record is kept byte for byte. A new one is written with `allowed=false` and null balances.
- An accepted same-key replay keeps the existing record. A missing record is rebuilt after a ledger-first crash.

**Ledger validation runs before both `--check` and `--finish`.** It requires integer version 1, string keys, a known status, and a non-bool usd that is finite and nonnegative. On failure it prints `invalid reservation ledger` and changes nothing. The 12 malformed variants are tested on both commands.

**Errors are safe.**
- `--finish` stores `balance_unavailable` and prints a fixed warning.
- The top level maps to fixed labels or `accounting unavailable`.
- `balance()` and the Hetzner pricing query capture stderr.
- A test checks that a provider diagnostic string never appears in output or records.

**Writes are durable.** File and directory are both fsynced for spend and ledger writes. Retirement directories are fsynced on creation, and the record itself goes through `atomic_json`.

**Planning retires before D.** `plan()` retires before the `DIAGNOSIS_ENABLED` gate, before stored facts and before `_project`. Tests cover known and unknown totals, pre-existing facts, a D call that must not happen, replay, unchanged journal bytes, and conflicting, symlinked and directory records.

**The holder refuses before money or transport.** `_source` refuses `legacy_retire` before `advance_locked`. A legacy successor reserved by older code is refused at dispatch with no transport or worker, and money is unchanged.

**The frozen disposition is exact.** I checked it independently:
- the inventory sha256 matches (`c59a0754…`);
- it has 43 Mac and 46 VM rows, matching the source inventory;
- every source key (`case`, `card_sha256`, `card_archive_sha256`, `casekey`, `casekey_metadata`, `files`) is kept, and nothing else is added.

**The deferrals are honest.**
- **Cleanup cost guarantees:** deferred to live practice. It first needs the provider ceiling or bounded-creation contract, or explicit founder re-approval. USD 5 is not relaxed.
- **Cumulative accounting:** deferred to live practice after the reviewed **Boat attributed settlement** increment.
- **Deployment qualification:** deferred to live practice after B2 and B3.
- **b275:** retire-only as a case. Its provider debt is a separate operator entry condition, and the report says plainly that code does not enforce it. No markers were fabricated.

**Supersession notes** are added to `stream-b-delayed-creation.md` and `isolation-timeouts.md`.

**No Murphy rows were closed.** The register is untouched.

**The suite record checks out.**
- The log hashes match: compressed `b9404f1c…`, uncompressed `88b5b83f…`.
- The tree of `31ec2d9` is `cf07b4c1…`, matching the record.
- `31ec2d9..db58dcd` changes only the result JSON, the log, the report and the attempts file.
- I re-ran `tests/integration/test_batch_launch.py` at `db58dcd`. All 6 tests ran and passed, and the rewritten single-worker test was not skipped.

**Nothing speculative was added**: no settlement import, reset path, supervisor or adapter.

## Blocker

**B1. The `_source` legacy check retires legitimate new-schema cases at resume, and the retirement is durable and terminal.**

*Scope:* `factory/batch_holder.py:158-159`, `factory/batch_service.py:292-314` (`retire_legacy`) and the design's "Revision 2" runtime source refusal.

**Why the test is wrong.**
- `retire_legacy` treats "no dict `diagnosis_state`" as legacy.
- The runner writes `diagnosis_state` only in `diagnosis.record_exhaustion`, and only when `exhaustion(card)` and `_trigger` hold (`factory/diagnosis.py:121-144`, called from `factory/run.py` `finalize_accounting`).
- `exhaustion()` returns False for `provider_wait`, `paused`, `ttl_retired` and `retired*` stops, and for any non-exhausted stop.

**What breaks.**
- A batch-launched new-schema card that stops for provider wait, a pause or a TTL interruption has `job_money` but no `diagnosis_state`.
- When its successor is reserved, `_source` writes `retirements/<case>/<generation>.json` and raises `legacy_retire`. This happens on the ordinary checkpoint path (`key_holder.py:466` → `reserve(..., req['checkpoint'])`) and on the provider-wait scan (`batch_holder.py:430` → `reserve(..., provider_wait=True)`).
- The provider-wait scan swallows the ValueError, so the case silently becomes terminal.
- The record cannot be undone: any differing record is refused as `retirement conflict`.

**Why it contradicts the rules.**
- It goes against the founder's scope: pre-new-schema cases only.
- It goes against the one-launch-path rule: a resume is a launch from a checkpoint.
- It goes against `batch-service.md:925-935`, which scoped the missing-`diagnosis_state` refusal to D projection planning and said "Existing independently authorized work is unaffected."

**Why the tests miss it.** The holder test cards are built with `diagnosis_state={}` ("Authored provenance for contract-only API doubles", `tests/factory/test_batch_service.py:79`). That value is not what the real runner produces, and `diagnosis._state` would reject it as invalid anyway. So the provider-wait and resume holder tests pass only because of an authored field. This is the "a fixture authored to suit the code under test proves nothing" case.

**Why there is no live harm yet.** `HOLDER_ENABLED` is false, so nothing is hit today. It is still a correctness defect, and it must be fixed before the holder is enabled.

**The design premise is also wrong.** Design review 2, nit N6, already observed that the inventory cases have no journal or ACK, so they can never reach `_source`. Anything that does reach `_source` was launched by the new holder under a pinned release. In practice, then, the runtime guard catches mostly legitimate cards.

**Fix guidance**, smallest option first:
1. Delete the `retire_legacy` call from `_source`. The frozen disposition already excludes every saved legacy case.
2. Restrict planning-side retirement to the context the original design scoped. That means an exhausted or `pending_projection`-eligible card with no `diagnosis_state`. Otherwise a non-exhausted new-schema entry would get a durable terminal record whenever `plan()` gains a caller.
3. Amend the design's runtime-refusal paragraphs to match.
4. Add a regression that pushes a card shaped like real runner output through `reserve` with a source. The card has no `diagnosis_state` and `terminal_stop` is `provider_wait` or an interruption. It must not retire and must write no `retirements/` record. Ideally the card comes from a real saved interrupted or provider-wait card.

The fix needs a fresh diff review.

## Nits

- **N1.** The `test_batch_launch.py` loop now accepts any failed process once `infrastructure liability unsettled` appears in any job log. Later assertions bound this (one `new`, 3 receipts, `processes[1:]` nonzero), but a per-process log check would be tighter.
- **N2.** `ValueError(__doc__)` for unknown arguments now prints `accounting unavailable`, so usage help is lost. Add a fixed `usage` label.
- **N3.** `read_ledger` uses plain `json.loads`, so duplicate keys silently keep the last one. `deployment_inventory.scan_ledger` already rejects duplicates with `unique_object`. Reusing that would stop a hand-edited ledger from hiding a liability row.
- **N4.** `deployment_inventory.scan_ledger` still totals only `reserved` usd. Finished rows are now unknown liability, so a scanner total could read as "no liability". At minimum, say so in its output or docs.
- **N5.** In `reserve`, the capacity and incident `MoneyWait` check runs before `_source`. A legacy source therefore records retirement only when capacity is free. It never advances money either way, and this is moot if B1 removes the check.
- **N6.** A fresh accepted admission (`previous is None`) overwrites an existing spend record at the same path. This could happen on a home whose ledger was missing, which is the b275 situation. Launcher paths are timestamp/PID-unique, so the risk is low; consider refusing or preserving.

## Scope honesty

- **Cleanup cost guarantees:** honestly deferred, with the provider-contract or re-approval prerequisite.
- **Cumulative accounting:** honestly deferred behind the named settlement increment. Same-home single admission is implemented and tested.
- **Legacy provenance:** the frozen disposition fully resolves the saved inventory. The runtime guard over-reaches (B1).
- **Deployment qualification:** honestly deferred to live practice after B2 and B3.
- **b275:** an operator entry condition, with the gap stated.
- No workers, paid calls, pushes or activation. Both gates stay off. No Murphy rows closed.

The branch is not merge-ready until B1 is fixed and a fresh goldfish re-reviews it.

## Elephant disposition

B1 accepted. Delete the holder-side call; restrict planning retirement to missing
diagnosis state plus the real diagnosis.exhaustion predicate. Add real-producer
non-exhausted resume/planning regressions and remove the authored empty diagnosis
state from provider-wait fixtures. Update design/report. No blocker rejected;
fresh review required. N4 documented; N5 removed with B1. Optional N1/N2/N3/N6
are not addressed in this blocker fix. No Murphy row closed.

