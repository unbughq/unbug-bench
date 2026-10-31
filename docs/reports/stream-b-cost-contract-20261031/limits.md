> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Limits and errors

> Every boat limit per plan: sandboxes at once, included starts, extra starts, and command and output caps. The error codes, how to retry, and how to raise a limit.

A start is free up to your included number. Above it, a start costs money. Above the maximum, it fails. Create, fork and resume each count as one start.

## Limits per plan

| Plan | Sandboxes at once | Included starts per minute / hour / day | Maximum starts per day |
| - | - | - | - |
| [Free trial](https://docs.boat.dev/free-trial.md) | 2 | 5 / 25 / 75 | 75 |
| \$20 | 100 | 12 / 60 / 200 | 1,200 |
| \$100 | 300 | 30 / 210 / 840 | 5,040 |
| \$500 | 1,000 | 65 / 420 / 1,680 | 10,080 |
| \$2000 | 2,000 | 90 / 600 / 2,400 | 14,400 |

* boat counts starts over the last 60 seconds, 60 minutes and 24 hours. There is no reset date.
* A stopped sandbox does not count against "at once".
* For organizations, read [Seats, limits and caps](https://docs.boat.dev/organizations/seats-and-limits.md).
* To see what you have left, run `boat limits`.

## Extra starts

A start above your included number is an extra start. It needs a first payment.

| Start | Price | Per day on the \$20 plan |
| - | - | - |
| Included | Free | 1 to 200 |
| Up to 1.5 times included | \$0.03 | 201 to 300 |
| Up to 2 times | \$0.05 | 301 to 400 |
| Up to 6 times | \$0.07 | 401 to 1,200 |
| Above 6 times | Fails | 1,201 and up |

* The prices apply per minute, hour and day. A start pays the highest of the three.
* The maximum per minute is 3 times, not 6.

Your wallet pays first. With an empty wallet, [your invoice](#extra-starts-on-your-invoice) pays if you turned it on. If neither pays, the start fails.

**boat never queues a start.** A failed start does not run later. Send a new call after `nextStartAt`. Only [`runs-on: boat` jobs](https://docs.boat.dev/ci#what-happens-at-a-limit) can wait.

### Extra starts on your invoice

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat billing extra-starts on
boat billing extra-starts off
```

* It is off by default. A trial, a past-due account, or a plan set to end cannot use it.
* The cap per seat per month is \$80 on the \$20 plan, \$400 on the \$100 plan, and \$1,500 above.
* If your plan ends first, your wallet pays what is left and can go negative.
* In a script, add `--yes` to accept the terms.

### In the API

`GET /limits` returns:

| Field | Means |
| - | - |
| `nextStartDollars` | Price of the next start. `null` when it would fail. |
| `startLimitsWithWallet` | The maximums. `null` when extra starts are not available now. |
| `overagePrices.startBrackets` | The price table. |
| `startWindowFull` | Only while a limit is full: `window`, `limit`, `freesAt`, `paidBy` (`wallet`, `invoice` or `null`), `message` (the text the CLI prints) and `help` (the same text in parts). |
| `planNudge` | Only when the next plan fits your last 30 days better. `text` has the sum. boat can send it by email once a billing period. Turn that off in [Alerts](https://boat.dev/dashboard?tab=alerts). |

## Other limits

| Limit | Value |
| - | - |
| Auto-stop | Default 1 hour. Maximum 30 days, or off. Trial: 2 hours maximum. |
| Sizes | `xlarge` needs the \$100 plan or higher. The trial has no `large` or `xlarge`. `boat limits` shows the sizes that you can create now. In the API: `machineTypes` in `GET /limits`. |
| Disk of a stopped sandbox | Kept 14 days after the stop, then deleted. Email on day 11. |
| Saved snapshots | 10 included for every \$20 of plan per seat, never fewer than 10, per account or organization. Each one more costs \$0.056 a day from the wallet. No maximum. They never expire. |
| Command that waits for its result | API: default timeout 30 s, maximum 600 s. For longer work, run it detached. No maximum with `boat exec --timeout 0` (CLI) or `run_command` / `runCommand` (SDK). |
| Output of a waiting command | 8 MiB per stream |
| Command output kept per account | 10 MiB compressed per hour (about 50 MiB of text) |
| Output of other processes | 64 KiB/s per process, plus 10 MiB compressed per hour per account |
| Prompt attachments | 12 files, 25 MB per file, 64 MB in total |
| Webhooks | 10 per account |
| API keys | Lifetime 90 days by default, 365 days maximum, or never expires (`--ttl never`) |
| API requests | 10,000 per 60 seconds from one IP address |

For the command limits, read [Background commands](https://docs.boat.dev/long-running-tasks/background-commands.md) and [Command history and logs](https://docs.boat.dev/long-running-tasks/command-history.md).

## Errors and what to do

| Status | Code | Cause | What to do |
| - | - | - | - |
| `429` | `rate_limited` | A start limit is full. The start did not run and does not queue. The body has `window` (`minute`, `hour` or `day`), `limit`, `cause` (`trial`, `plan`, `cap` or `ceiling`), `nextStartAt` and `retryAfterSeconds`. | Pick an option in `message`, or send a new call after `nextStartAt`. At cause `ceiling`, only a bigger plan or more seats help. |
| `429` | `limit_reached` | The plan's "at once" limit is full. | Stop a sandbox, or raise the plan. |
| `429` | `member_limit_reached` | The organization owner capped how many sandboxes you run at once. | Stop one, or ask the owner to raise your cap. |
| `429` | `trial_compute_limit_reached` | The trial used its 25 hours. | [End the trial](https://docs.boat.dev/free-trial.md#end-the-trial-early). |
| `429` | `IP_RATE_LIMIT_EXCEEDED` (in `code`) | More than 10,000 API requests in 60 seconds from one IP address. An open stream counts once, when it opens. | Wait the `retryAfter` seconds in the body. Watch the `RateLimit` header to slow down before this. |
| `402` | `billing_required` | The included time is used and the wallet is empty, or the account or organization has no plan. | Open the `billingUrl` in the body. Add money to the wallet, or start a plan. |
| `402` | `team_member_cap_reached` | You used your per-member usage cap in the organization. | Ask the owner to raise it. It resets with the billing month. |
| `403` | `trial_machine_class_not_allowed` | `large` during the trial. | Use `default`, or end the trial. |
| `400` | `trial_auto_stop_required` | No auto-stop, or more than 2 hours, during the trial. | Set an auto-stop of 2 hours or less. |
| `409` | `snapshot_data_expired` | The sandbox stayed stopped for 14 days. boat deleted its data. | You cannot resume it. Next time, save a [saved snapshot](https://docs.boat.dev/snapshots/stop.md#keep-a-stopped-sandbox-longer-than-14-days) before day 14. |
| `503` | `no_ready_machine` | You asked to [fail fast](https://docs.boat.dev/machines/fail-fast.md) and no machine is ready. Nothing started or counted. | Retry after `retryAfterSeconds` (5). |
| `503` | `out_of_capacity` | boat is out of machines for a short time. Running sandboxes are not affected. | Retry after `retryAfterSeconds` (120). |

### Retry rules

* Read the wait from the body: `retryAfterSeconds` on a `503` and on `rate_limited`, `retryAfter` on an IP limit. `rate_limited` and the IP limit also send a `Retry-After` header.
* Every API answer carries your IP limit in two headers ([IETF RateLimit fields](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/)). `r` is the number of requests you have left:

```
RateLimit-Policy: "ip";q=10000;w=60
RateLimit: "ip";r=9412;t=60
```

* A start that fails with `rate_limited` does not count as a start.
* Send an `Idempotency-Key` header on create and fork. A retry with the same key never makes a second sandbox or spends a second start.
* The CLI does not retry. It prints the limit message and exits with an error.

## Raise a limit

| You need | Do this |
| - | - |
| More starts or more sandboxes at once | Move to a bigger plan: `boat billing plan 100`, or [Dashboard > Billing](https://boat.dev/dashboard?tab=billing). The change applies at once. |
| More of everything, for a team | Move to a bigger plan first. On the \$2000 plan, buy seats on an [organization](https://docs.boat.dev/organizations/seats-and-limits.md): each seat adds the full limits and included time. |
| More time, same limits | Add money to the wallet (`boat wallet pay 50`) or turn on [auto top-up](https://docs.boat.dev/billing.md#auto-top-up). |
| More starts for a short time | Use [extra starts](#extra-starts). |
| More than the \$2000 plan gives | boat raises limits only on custom plans above \$2000 a month. [Contact us](https://docs.boat.dev/support.md) for a custom plan. |
| Trial limits gone | Pay the first plan. Read [Free trial](https://docs.boat.dev/free-trial.md). |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.