**FAIL** on both standards. The design is mostly there, but it is not ready to implement. The new contract (lines 122–360) closes most of round 1. What is left is the transaction order and the source-authority sequence, which still contradict each other, plus one accounting formula that undercounts known spend.

# Fresh review: `docs/designs/batch-holder.md` (round 2)

Mode: REVIEW. Standards: `heilmeier-standard.md` and `implementation-readiness-standard.md`. Roles: zoom-out, design critic, implementation readiness. Read-only; nothing was written.

## Round-1 findings

| ID | Status | Note |
|---|---|---|
| B1 files/phases/tests | Resolved | Lines 131–158 give the files, order and `launch_manifest` pin. |
| B2 schemas | Mostly resolved | Journal, operation, money, ACK, incident and outbox key sets are exact. Remaining gaps are under N1 below. |
| B3 async protocol | **Partly open** | See new B1 and B3. |
| B4 failed relaunch | Resolved | Retries deferred, and the narrowing of `batch-service.md:59-60` is stated (lines 208–211). |
| B5 call cap | Resolved | Lines 352–360 cover bind, `current_generation`, `policy_load` and `run.py` `recovery_config`, and override "max_calls stays". |
| B6 scoped key / gate | Resolved as a gate | `HOLDER_ENABLED` code constant, with the predicate listed (lines 162–166, 325–336). The predicate's content is wrong (new B2). |
| M1 retirement artifact | Resolved | Lines 258–265. |
| M2 failed predicate | **Partly open** | See new B3. |
| M3 journal format replacement | Resolved | Lines 215–219. |
| M4 legacy money | Resolved | Lines 70–71 and 271: schema1 always refuses. |
| M5 publication | Resolved | `bin/r2-presign` + urllib, an in-memory double, and an object key that supersedes `archive.age` (lines 312–321). |
| M6 status mapping | Resolved | Lines 242–248. |

## Blockers

**B1. Lock scope of reserve is undefined, and the obvious build deadlocks or races.** Lines 184–189 and 179–183.
- Line 183 says all reservation writes use `batch_money.locked`. Line 184 says reserve runs "checks … concurrency, obtains authority and freezes config, then writes the operation, then projects journal".
- `batch_money.authorize` (`batch_money.py:127`) takes `locked()` itself, and so does `batch_service.collect` (`batch_service.py:207`).
- If reserve holds the batch lock across `authorize`, the second `flock` on a new open file description in the same process blocks forever.
- If it doesn't, the concurrency, freeze, incident and "one unresolved per case" checks run in a different critical section from the operation write. The periodic scan, the `collect` command and dispatch children are separate processes that change those inputs between the two sections.
- The doc must state:
  - one critical section covering: re-read money, incidents/freeze, concurrency count, `authorize` (refactored to take an already-held lock), config freeze, operation write, journal projection;
  - the exact lock-held helper signatures;
  - the concurrency count source. Today `batch_live_reservations` counts legacy `RUNTIME/reservations.json` rows. For new operations, is it "state ∈ {pending, launched} ∧ ¬retired" over `batches/<batch>/reservations.json`?

**B2. Source advancement has no single owner or step, and the resume predicate contradicts itself.** Lines 81–90, 184–185, 205–207, 325–336.
- UUID5 binds `source_generation`, so the successor's operation ID needs the advanced source.
- Line 334 says config is frozen only after money source advancement. Reserve freezes config (line 185), so reserve must advance the money source.
- But line 333 says `batch.bind` and `launch.sh` both call "this resolver". Line 335 says the resolver "accepts the already-advanced source only for the same reserved successor operation", which implies the resolver advances or validates after reservation. `bind` runs in the accept loop *before* reserve (`key_holder.py:569-570`).
- Predicate lines 329–330 require "owner source-history excludes output" and "current authority source equals predecessor input". Once reserve has advanced the source (needed to freeze config), both are false when `launch.sh` re-checks. On the old-source side, the resolver then refuses the legitimate successor.
- Today `authorize` refuses any source change (`batch_money.py:141-147`), and the doc never says which function gets the source-changing branch.
- The doc must name:
  - the one writer that appends `sources` and bumps the revision (or keeps it on a null total);
  - when it runs relative to the operation write;
  - the resolver as a pure read with two exact predicate forms: pre-advance (bind/admission) and post-advance (`launch.sh`, bound to `operation_id`);
  - that `bind` never mutates money.
- This is the unsafe source-authority gap.

**B3. A pre-launch refusal in the dispatch child gets either stuck forever or retried forever.** Lines 176, 186–189, 194–199, 253–256.
- Moving cloud I/O out of the accept loop (line 190) pushes these checks into the child: Boat inventory and "case worker already exists" (`key_holder.py:606-620`), account selection (`launch_accounts` uses the holder's in-RAM `account_labels`), `attest_launch`, `current_generation`, TTL admit and fingerprint. The doc doesn't list which checks move or which stay in reserve.
- If the child refuses before Popen (`dispatch_started` false), line 253 cannot mark it failed, because no `launch.json` exists. So it stays pending and holds concurrency and money forever.
- Line 189 has the periodic scan "schedule an unstarted dispatch child". That re-spawns a child after every refusal: an unbounded implicit retry loop, which contradicts "retry deferred" (line 208).
- The doc must define:
  - the child's exact check list and order;
  - who selects the environment and accounts (the child can't see `account_labels` unless they're passed);
  - a positive pre-Popen failure record (for example the child writes `failed` with a fixed reason while holding `operations/<id>.lock` with `dispatch_started` false), and that this is the only failed path besides line 253;
  - that the scan spawns a child only for `dispatch_started` false with no recorded child exit.

**B4. The aggregate formula drops known spend after a null-total ACK.** Lines 74, 79, 274, 282.
- `previous.total_usd` is replaced by each ACK's nullable total. `collection_facts` accepts a null T after a known P, subject only to coverage ≤ held (`batch_accounting.py`, the `total is None` branch).
- Sequence: hold 5.00, ACK1 known total 6.00 (an overrun), then ACK2 null. The aggregate becomes `max(5.00, 0)` = 5.00, so 1.00 of known overrun stops counting toward the batch ceiling. That contradicts "counted in full" (line 79) and "Known overrun remains counted" (line 298).
- Fix by specifying either a monotone `known_floor_usd` per job, kept as the max of known totals and used in the aggregate, or a rule that a null total never replaces a known higher total in the aggregate input. Add both to the money schema at line 272.

## Major

**M1. Overrun has no definition, and its two cases disagree.**
- `collection_facts` refuses `total > held` only when P is null (`uncovered_total`, which becomes an incident and a batch freeze). With P known it doesn't check against hold at all.
- So the first over-hold ACK freezes the batch, while a later one is an ACKed "overrun". Define `overrun := known total > held_usd`.
- State whether the null-P case stays an incident.
- State whether "cannot advance authority" also forbids the same-revision null-total source advance at line 83. Today it reads as allowed.

**M2. Pointer before accounting leaves `current/<case>.json` on a refused candidate.**
- Lines 307–308 write and re-read the pointer, then run the ACK/accounting. A refusal therefore leaves the pointer naming an unACKed, incident-bearing generation. That stays safe only while every consumer requires an ACK.
- Either run `collection_facts` (it's pure) before the pointer write, or state that the pointer may name an unACKed candidate. Then add a status rule for that state (line 247 says "stopped" when output equals current, but output projects only after ACK) and a test.

**M3. The ACK record changes after it is created.**
- Line 279 sets `retirement` to null and fills it later. Line 281 says replay returns the saved ACK.
- Specify that `retirement` is the only field allowed to change, only from null to a value, under the lock, and that replay compares the ACK with `retirement` excluded. Otherwise the implementer has to choose.

**M4. Who records the dispatch child's exit is undefined.**
- Line 253 requires "dispatch child exit recorded by the holder". After a holder restart, the `Popen` handle is gone (`reap()` only knows `jobs`).
- Specify the record (a field name is missing from the operation schema at line 221) and what a restart means: no record, so pending.

## Nits

- **N1. Schema gaps:**
  - the reservations-file operation record isn't given; is it the same key set as the journal map row?
  - `release_sha256` versus the policy release (line 225) on a release change while an operation is pending;
  - the fixed label sets for refusal replies (line 175) and incident `reason` (line 287) aren't enumerated.
- **N2. Status lock:** line 203 says status reads under a "shared-lock". `batch_money.locked` is `LOCK_EX` only. Name the shared-lock helper.
- **N3. Prose and contract overlap:** line 122 says the contract "supersedes broad prose above", but lines 16–19 and 37–46 still contradict it (for example, "reservations.json as the durable operation authority" without its new path). Delete or shrink that prose so there is one source.
- **N4. Heilmeier:** answered adequately. Plain objective, cost (none), timeline (one increment), mid-term and final exams, and risks are present (lines 117–129). No finding.

## Scope and founder constraints

These all hold:
- Scope is increment1 only: holder lifecycle, ACK, source and current pointers. No live activation, no D dispatcher dependency, and no legacy booking. `DIAGNOSIS_ENABLED` stays false.
- There is no cumulative call cap, and dollar ceilings are paid-route only and router-owned (line 100).
- Legacy is retired by default, with cb5e2/14d35 set aside. Schema1 money and cards without `job_money` refuse (`legacy_retire`).
- No Murphy row is closed.

Close B1–B4 and M1–M4, then send it for a fresh review.

## Elephant response
All B1–B4, M1–M4 and nits accepted. Removed overlapping prose; added explicit lock-held helpers, single source writer and PRE/POST predicates, child failure/exit handling, monotone known floor, pre-pointer accounting and ACK mutability rules. Also documented the discovered covered-null restore constraint and disabled legacy batch same-worker restart. Fresh review pending.
