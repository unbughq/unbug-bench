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

About 80 lines, plus one test.

- **Stopped cases:** the test uses copies of real VM cards.
- **Running cases:** no saved real file has a stage in progress, so the
  running-stage and journal inputs are hand-edited from real files. The
  test says so.
- **Each rule:** the test checks that every rule fires.
- **Sealed versus rejected:** the test includes one real sealed card, one
  real rejected card, and one rejected card edited to carry a stop reason.
- **Old cards:** cards from before these fields existed produce no false
  flags. 266 of 297 real cards lack `case_budget`.
