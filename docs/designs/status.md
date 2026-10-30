# Batch status: `unbug status`

Owner: stream B. The founder asked for one command, not a dashboard or
alerts.

## What it is

`unbug status` is a single command on the control VM. The founder asks
Claude "status". Claude runs the command and summarises. The founder can
also run it directly.

## Data sources, in precedence order

1. **B's batch journal** decides whether a case is running or stopped. This
   is the per-`(case, generation)` state from `interfaces.md` section 4:
   plus the batch manifest's job list. The staged collection core exposes only
   collected, stopped entries. Roots/derived jobs with no entry are not collected.
   The holder addendum will extend the shared validator to supply launched,
   pending and failed lifecycle states; unsupported fields stay unreadable now.
   The rendering rules below cover that later lifecycle view too; they do not
   authorize inferring it from the present collection-only journal.
2. **Worker liveness:** `boat-call list`, read once per run.
3. **The live stage of running cases:** `progress.json`, read from each
   running worker with one read-only `cat` over the existing Boat SSH. It is
   a public file, so it holds no case content. `stages[s].updated_at` of a
   stage still `running` is when that stage started.
4. **Collected cards:** the public scorecard pinned by the selected immutable
   snapshot manifest, never legacy flat files. Its sha256 must equal the selected
   journal generation; its case and release must match. Otherwise it is unreadable.

## Output

1. **`Sealed X / N`.**
   - **Sealed** means the case's current card has all three:
     - `gates.G12 == "pass"`;
     - `failed_gate` is null;
     - `terminal_stop` is null or `complete`. Real sealed cards carry null.

     `G12` alone also passes on rejected cases, so it is not enough.
   - **Rejected** means `failed_gate` is set. Rejected cases are counted
     separately, and "rejected at G*" is on the known-stop list.
   - **N** is the number of target slots in the batch manifest.
   - After that come counts of running, waiting, rejected, stopped, not collected and
     unreadable cases.
   - **Waiting** means `terminal_stop == provider_wait`. It stays at zero
     until stream A writes that stop.
2. **Needs attention:** each flag shows the action to take. If nothing needs
   attention, it says "nothing needs you".
3. **One line per case:**
   - case;
   - stage;
   - time in that stage;
   - spend as `case_budget.spent_usd / limit_usd` as of the last card, or
     `—`. A running case therefore shows its last collected numbers;
   - rounds as `builder_rounds / recovery_config.rounds`, or `—`;
   - cumulative continuation_budget.calls as calls N, or calls — if absent;
     no denominator and no call-count near-limit rule;
   - stop reason in plain words.

A source that is missing or won't parse shows as `unreadable` and is
flagged.

If `boat-call list` fails, the whole batch shows `boat unreadable`, and no
case is flagged `worker gone`. A missing field shows `—` or `?`, and never fires a rule by itself.

## Needs attention

The thresholds are in one table at the top of the script.

| Rule | Data | Action shown |
|---|---|---|
| Journal says `launched`, but the worker isn't in `boat-call list` and no new card was collected | journal, Boat | `worker gone` |
| A running stage started more than 5 h ago (above the 4 h agent timeout) | live `progress.json` | `check case` |
| A stopped case's `terminal_stop` starts with `stress_review_unresolved:`, or is `freshness_unresolved` or `freshness_review_unavailable` | card | `needs ruling` |
| A stopped case's `terminal_stop` is not on the script's known list | card | `check case` |
| Spend ≥ 80% of `limit_usd`, or rounds ≥ 80% of `recovery_config.rounds` | card | `near limit` |
| Journal `failed` or `pending` for more than 30 min | journal | `launch stuck` |
| A source is missing or won't parse | — | `unreadable` |

These rules are added once their fields exist. Stream A writes the
provider-wait object on the card, and B owns the balance reads.

| Rule | Data | Action shown |
|---|---|---|
| `provider_wait.retry_after` passed by more than 30 min, with no relaunch | card, journal | `relaunch overdue` |
| `terminal_stop` is `provider_wait_unrecoverable` | card | `top up / re-login` |
| Boat wallet or OpenRouter credit under one day of need | `boat-call billing`, OpenRouter key info | `top up` |

`paused` and `complete` are on the known list. They are never flagged by
themselves. A rejected case is a normal outcome, so it is counted but never
flagged.

## Size and test

One small read-only module and command, plus one test file.

- **Stopped cases:** the test uses copies of real VM cards.
- **Running cases:** no saved real file has a stage in progress, so the
  running-stage and journal inputs are hand-edited from real files. The
  test says so.
- **Each rule:** the test checks that every rule fires.
- **Sealed versus rejected:** the test includes one real sealed card, one
  real rejected card, and one rejected card edited to carry a stop reason.
- **Old cards:** cards from before these fields existed produce no false
  flags. 266 of 297 real cards lack `case_budget`.

## Implementation against B's staged journal

Add factory/batch_status.py and executable bin/unbug; unbug status reads
the existing control home's policy and pinned manifest through
batch_money.manifest. --control-home selects a test/operator state directory,
default UNBUG_CONTROL_HOME or ~/.unbug-control. This command writes nothing,
dispatches nothing, decrypts nothing and closes no Murphy row. No VM install is
part of this increment. Activation later symlinks bin/unbug from the approved
release to /usr/local/bin/unbug, with the VM rollout record.

The collection core currently has no launch metadata or current pointers.
For each manifest root and recorded derived job, select the unique journal
entry, or the entry named by current/<case>.json when multiple entries exist.
The pointer must be a regular non-symlink JSON file with exactly generation and
manifest_sha256. Both must match that journal entry, whose case must equal the
pointer filename case.
Never use dictionary order, file mtimes or archive filenames as chronology.
Ambiguous generations with no verified selector are unreadable, not guessed.
Current-pointer publication and launch metadata are later dispatcher obligations.
Status does not write them or enable their production.

Reuse batch_service._load and resolve_job for the read adapter, after explicitly
checking journal.json exists. Open the existing batch lock read-only with shared
flock; never call batch_money.locked, which creates directories/files. Every
accepted core entry is stopped using its own snapshot. A root or recorded derived
job without an entry is not collected, gets that count bucket, and fires neither
worker gone nor launch stuck. Missing journal is unreadable for the batch.

The optional umbrella fields are NOT accepted by another parser. They remain
unreadable until the holder addendum extends the shared validator. The pure
formatter's running/pending/failed inputs and transport tests use explicitly
authored normalized lifecycle rows. Running rows use live progress, with prior
cards providing only last-collected spend/rounds/calls, never stopped-case rules.
Pending/failed rows likewise use cards only for those numbers; pending_since
is an ISO UTC timestamp and its absence never fires launch stuck. No card on a
fresh launch is normal. Connecting these normalized views to real launch entries
is a holder-integration obligation, not a production capability of the core.

Read the snapshot manifest and its pinned public scorecard bytes without
decryption or re-hashing large ciphertext archives. The public card must match
the selected case, collected ciphertext sha and release. Never fall back to a
flat card, even with a matching ciphertext generation. With journal authority unchanged by a
read-only command, absent or malformed sources become unreadable.

Use one bounded boat-call list --json request per invocation (30 seconds).
Require sandboxes[] with unique string id values and pageInfo.hasMore == false;
an incomplete page is boat unreadable, never worker gone. This is a known limit
for fleets larger than one page; pagination remains the service inventory's
responsibility. For each running worker confirmed present,
use exactly one bounded read-only boat-call ssh <id> cat of
~/sealed/<case>.progress.json. Missing worker_id is unknown, never worker gone.
Transport/schema errors are rendered as fixed unreadable labels, without stderr
or arbitrary source text. Known operational stop labels are mapped to plain
words; unknown labels show unknown stop, check case (never print free-form text).
Allow only public_progress's operational stage names. Concurrent running stages
are all listed, and the oldest valid running start determines duration/check case.

Test classification/rendering on unmodified saved public sealed/rejected/old
cards. None has the new release binding: transport/manifest/case/release tests
therefore use separate, explicitly authored operational snapshot bindings.
Explicitly authored journal/Boat/progress fixtures test running precedence,
missing/stale sources, every threshold, pointer ambiguity, rejected-with-stop,
and calls above a historical max_total_calls with no call alert or denominator.
A recording transport asserts one list and one cat per present running worker;
failed/incomplete inventory cannot make false worker-gone reports.

Implement provider_wait overdue/top-up-login rules when their existing card
fields are present. The wallet/day-of-need rule stays deferred: this increment
has no authenticated provider-balance adapter and must not infer cash from
account delta observations. No new dependency, balance probe or scheduler.
Nothing is deleted because no prior status command exists. Full suite and a
fresh batch-service diff review precede parent merge.

Calls: absent means —; present values must be nonnegative int (never bool),
otherwise ?. Known stops are null/complete, paused, provider_wait,
provider_wait_unrecoverable, provider_wait_deadline, money_wait,
retired_batch_bound, ttl_retired, total_call_limit, call_limit, stalled,
budget_exhausted, and provider_limit:* (plain provider limit).
Freshness unresolved/unavailable and stress_review_unresolved:* need ruling.
Any other stop, including free-form Budget ledger stopped text, displays
unknown stop and check case; arbitrary text is never echoed.
