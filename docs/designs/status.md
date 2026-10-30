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
   `pending`, `launched` or `failed`, plus the batch manifest's job list.
   - **launched:** the job was launched, and no card has been collected
     for it since.
   - **stopped:** a card has been collected for the job's latest launch.
2. **Worker liveness:** `boat-call list`, read once per run.
3. **The live stage of running cases:** `progress.json`, read from each
   running worker with one read-only `cat` over the existing Boat SSH. It is
   a public file, so it holds no case content. `stages[s].updated_at` of a
   stage still `running` is when that stage started.
4. **Collected cards:** `sealed/<case>.scorecard.json`, for stopped cases.
   A card is used only when its `sha256` equals the journal's latest
   collected generation for the job. Otherwise it is stale and ignored.

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
   - After that come counts of running, waiting, rejected, stopped and
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
The pointer's generation and manifest_sha256 must match that journal entry.
Never use dictionary order, file mtimes or archive filenames as chronology.
Ambiguous generations with no verified selector are unreadable, not guessed.
Current-pointer publication and launch metadata are later dispatcher obligations.
Status does not write them or enable their production.

The read adapter also accepts the umbrella journal's optional fields state,
worker_id, pending_since and collected_generation. state launched with no
collected_generation means running. A collected_generation means stopped;
otherwise a core pending entry's own verified snapshot is its collected card.
For a running row its generation (unless fresh) is the last collected card.
An absent last card for a genuinely fresh launch displays — for spend, rounds
and calls without an unreadable-card warning. pending_since is an ISO UTC time;
its absence alone never fires launch stuck. pending/failed rows with no card
show that state; missing required snapshot/card is unreadable.

Read the snapshot manifest and its pinned public scorecard bytes without
decryption or re-hashing large ciphertext archives. The public card must match
the selected case, collected ciphertext sha and release. Never fall back to a
flat card with an unrelated generation. With journal authority unchanged by a
read-only command, absent or malformed sources become unreadable.

Use one bounded boat-call list --json request per invocation (30 seconds).
Require sandboxes[] with unique string id values and pageInfo.hasMore == false;
an incomplete page is boat unreadable, never worker gone. Pagination remains the
service inventory's responsibility. For each running worker confirmed present,
use exactly one bounded read-only boat-call ssh <id> cat of
~/sealed/<case>.progress.json. Missing worker_id is unknown, never worker gone.
Transport/schema errors are rendered as fixed unreadable labels, without stderr
or arbitrary source text. Known operational stop labels are mapped to plain
words; unknown labels show unknown stop, check case (never print free-form text).
Allow only public_progress's operational stage names. Concurrent running stages
are all listed, and the oldest valid running start determines duration/check case.

Use the existing real public-card corpus for sealed/rejected/old-card tests.
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
