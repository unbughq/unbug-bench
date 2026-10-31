> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Pricing

> Cost per hour of each sandbox size, what a plan includes, what the wallet pays, and prices compared to E2B, Modal and Daytona.

## Cost per hour

You pay per second, only while a sandbox runs. A stopped sandbox costs no machine time.

> [!WARNING]
>
> **A stopped sandbox keeps its disk for 14 days.** Then boat deletes the data, and the sandbox cannot resume. To keep a disk longer, save a [saved snapshot](https://docs.boat.dev/snapshots/templates.md) before day 14. Read [Keep a stopped sandbox longer than 14 days](https://docs.boat.dev/snapshots/stop.md#keep-a-stopped-sandbox-longer-than-14-days).

| Size | Per hour | CPU | RAM | Disk |
| - | - | - | - | - |
| `small` | **\$0.018** | 2 vCPU | 4 GB | 51 GB |
| `default` | **\$0.036** | 4 vCPU | 8 GB | 51 GB |
| `large` | **\$0.072** | 8 vCPU | 16 GB | 111 GB |
| `xlarge` \* | **\$0.200** | 16 vCPU | 32 GB | 251 GB |

\* `xlarge` needs the \$100 plan or higher. Subscribe from [Dashboard > Billing](https://boat.dev/dashboard?tab=billing), then pass `--type xlarge`. You do not need to contact us.

* `default` is the size that other providers call medium.
* Start with `default`. Use `small` for light scripts. Use `large` or `xlarge` for big builds or many containers.
* No size has a GPU.
* "Disk" is the space for your own files. The OS and the pre-installed tools are not in it.
* One `default` sandbox that runs a full month (730 h) costs \$26.
* Every size is a full Linux virtual machine with the same tools, snapshots, hosting and desktop. Only the machine changes.

`default` costs \$0.036 an hour. E2B and Daytona charge \$0.331 an hour for the same machine (9x). Modal charges \$0.760 (21x). Read [Compared to others](#compared-to-others).

Pick the size when you create a sandbox. To change it, stop the sandbox, then resume it with a new size. A fork can also take a new size.

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat new --type small
boat stop bx_23456789
until [ "$(boat info bx_23456789 --json | jq -r .sandbox.state)" = "stopped" ]; do sleep 2; done
boat resume bx_23456789 --type large
```

## Included at no cost

* Automatic snapshots of your sandboxes, with no count limit. boat keeps them while a sandbox runs and for **14 days after it stops**. Then it deletes them.
* [Saved snapshots](https://docs.boat.dev/snapshots/templates.md#automatic-and-saved-snapshots) included with your plan: **10 for every \$20 of plan per seat**, never fewer than 10. A saved snapshot has no auto-deletion date. You cannot save one during the free trial.
* Network traffic. boat does not bill egress.
* A public IPv6 address on every sandbox, and outbound IPv4. The IP address can change when a sandbox resumes.
* [Public URLs](https://docs.boat.dev/hosting) for the ports of a sandbox.

## Plans

A plan is a monthly price that your card pays. **It is not a fee.** Every dollar comes back as VM time at the rates above. Example: the \$20 plan includes 555 hours of `default` and lets you run 100 sandboxes at the same time.

Your first plan starts with a 7-day [free trial](https://docs.boat.dev/free-trial.md). A card is required.

### Plan limits and included

| Plan | Run at once | Included starts per min / hour / day | VM time included | Saved snapshots included |
| - | - | - | - | - |
| \$20/mo | 100 | 12 / 60 / 200 | 555 h of `default` (\$20) | 10 |
| \$100/mo | 300 | 30 / 210 / 840 | 2,777 h of `default` (\$100) | 50 |
| \$500/mo | 1,000 | 65 / 420 / 1,680 | 13,888 h of `default` (\$500) | 250 |
| \$2000/mo | 2,000 | 90 / 600 / 2,400 | 55,555 h of `default` (\$2000) | 1,000 |

* Create, fork and resume each count as one start. Above your included starts, a start costs \$0.03 to \$0.07. Read [Extra starts](https://docs.boat.dev/limits.md#extra-starts).
* Included VM time expires at the end of the billing period. boat does not carry it over.
* **Seats**: an organization pays the plan price once per seat. A 5-seat organization on the \$20 plan pays \$100 a month. Each seat adds the plan's included amounts. It adds the full limits on the \$2000 plan, and 20% of them below. Read [Seats, limits and caps](https://docs.boat.dev/organizations/seats-and-limits.md).
* boat raises limits only on custom plans above \$2000 a month. [Contact us](https://docs.boat.dev/support.md) for a custom plan.

### Overage, paid from the wallet

boat uses the included amounts first. Then the wallet pays.

| Overage | Price, paid from the wallet |
| - | - |
| VM time past the included time | \$0.036 per hour of `default`. `small` \$0.018, `large` \$0.072, `xlarge` \$0.200 |
| Saved snapshots past the included count | \$0.056 per snapshot per day (\$1.68 for 30 days) |
| [Extra starts](https://docs.boat.dev/limits.md#extra-starts) | \$0.03 to \$0.07 per start |
| [AI credentials proxy](https://docs.boat.dev/ai-credentials.md#pricing) | \$1 for each day it is on, plus \$1 per 1,000 requests |

* Add money with **Pay** or **auto top-up**. A payment of \$200 or more gets a bonus of 2% to 25%. Read [Wallet](https://docs.boat.dev/billing.md#wallet).
* Saved snapshots and the AI proxy also charge while your sandboxes are stopped. Delete a saved snapshot to stop its charge.
* For an empty wallet, read [Running out](https://docs.boat.dev/billing.md#running-out).

All limits, their error codes and how to raise them are on [Limits and errors](https://docs.boat.dev/limits.md).

Change plans from [Dashboard > Billing](https://boat.dev/dashboard?tab=billing) or with `boat billing plan 100`. A change applies at once. Read [Card, invoices and plan changes](https://docs.boat.dev/billing/plan-changes.md).

## Compared to others

![One default sandbox per hour, boat versus other sandbox providers](https://mintcdn.com/ariana-1e97e6c3/qYEPg6P4ACx7GhnX/images/pricing-vs-others.svg?fit=max\&auto=format\&n=qYEPg6P4ACx7GhnX\&q=85\&s=2b5f462304616367fbbc0c60c98cfeec)

This table prices the same machine on E2B, Modal, Daytona and other sandbox providers, at full use and their public list prices. The sizes are the ones in the table above.

| \$/hour | `small` | `default` | `large` | `xlarge` |
| - | - | - | - | - |
| **boat** | **\$0.018** | **\$0.036** | **\$0.072** | **\$0.200** |
| Novita | \$0.117 (6x) | \$0.233 (6x) | \$0.467 (6x) | \$0.933 (5x) |
| Freestyle | \$0.132 (7x) | \$0.264 (7x) | \$0.529 (7x) | \$1.06 (5x) |
| exe.dev † | \$0.140 (8x) | \$0.280 (8x) | \$0.560 (8x) | \$1.12 (6x) |
| E2B | \$0.166 (9x) | \$0.331 (9x) | \$0.662 (9x) | \$1.32 (7x) |
| Daytona | \$0.166 (9x) | \$0.331 (9x) | \$0.662 (9x) | \$1.32 (7x) |
| Blaxel † | \$0.166 (9x) | \$0.331 (9x) | \$0.662 (9x) | \$1.32 (7x) |
| Cloudflare † | \$0.180 (10x) | \$0.360 (10x) | \$0.720 (10x) | \$1.44 (7x) |
| AWS AgentCore † | \$0.217 (12x) | \$0.434 (12x) | \$0.867 (12x) | \$1.73 (9x) |
| Islo | \$0.300 (17x) | \$0.600 (17x) | \$1.20 (17x) | \$2.40 (12x) |
| Deno Sandbox † | \$0.300 (17x) | \$0.600 (17x) | \$1.20 (17x) | \$2.40 (12x) |
| Fly.io Sprites † | \$0.315 (18x) | \$0.630 (18x) | \$1.26 (18x) | \$2.52 (13x) |
| Runloop | \$0.317 (18x) | \$0.634 (18x) | \$1.27 (18x) | \$2.53 (13x) |
| Vercel Sandbox † | \$0.341 (19x) | \$0.682 (19x) | \$1.36 (19x) | \$2.73 (14x) |
| Modal | \$0.380 (21x) | \$0.760 (21x) | \$1.52 (21x) | \$3.04 (15x) |
| Railway † | \$0.417 (23x) | \$0.833 (23x) | \$1.67 (23x) | \$3.33 (17x) |

† exe.dev: Cloud Pool rate; Cloudflare: active CPU only; Vercel Sandbox: active CPU only; Blaxel: CPU included in the RAM price; Railway: active CPU and used RAM only; Fly.io Sprites: active CPU and used RAM only; AWS AgentCore: active CPU and used RAM only; Deno Sandbox: active CPU only.

### "Active CPU" billing

Some providers bill only the CPU time that your code uses. They bill RAM in addition. Some bill the RAM that you reserve. Others (‡) bill the RAM in use. Their claim is "you will rarely max the box". This is what it means for you:

* **You cannot know the price before you run.** The same job costs a different amount each time. Builds, test suites, browsers and agents use mostly CPU.
* **RAM bills while you are idle.** Reserved or in use, you pay for it every second that the sandbox runs.
* **They do not publish what their users use.** So you cannot check what "rarely max the box" saves you.

The table above prices them at full use. That is the only rate they publish. boat has one price per size, per hour. You know it before you run anything.

We publish our usage. This table shows how much CPU and RAM boat sandboxes used over the last 30 days. Each column prices that usage at the list rates of one provider.

![One default sandbox per hour at real boat usage, boat versus active-CPU providers](https://mintcdn.com/ariana-1e97e6c3/YRKQLhWfx1vmU_pI/images/active-cpu-vs-others.svg?fit=max\&auto=format\&n=YRKQLhWfx1vmU_pI\&q=85\&s=d421a90b4b32dad6fe0f1fde8815fbbb)

| Sandbox | **boat** | AWS AgentCore ‡ | Cloudflare | Fly.io Sprites ‡ | Railway ‡ | Vercel Sandbox | Deno Sandbox |
| - | - | - | - | - | - | - | - |
| quietest 1%: CPU 0.37% busy, RAM 14.77% used | **\$0.036** | \$0.012 (0.3x) | \$0.073 (2.0x) | \$0.053 (1.5x) | \$0.083 (2.3x) | \$0.171 (5x) | \$0.201 (6x) |
| median: CPU 8.79% busy, RAM 18.89% used | **\$0.036** | \$0.046 (1.3x) | \$0.097 (2.7x) | \$0.091 (2.5x) | \$0.129 (4x) | \$0.215 (6x) | \$0.235 (7x) |
| average: CPU 11.11% busy, RAM 22.97% used | **\$0.036** | \$0.057 (1.6x) | \$0.104 (2.9x) | \$0.112 (3x) | \$0.158 (4x) | \$0.226 (6x) | \$0.244 (7x) |
| busiest 1%: CPU 92.06% busy, RAM 36.1% used | **\$0.036** | \$0.357 (10x) | \$0.337 (9x) | \$0.384 (11x) | \$0.456 (13x) | \$0.641 (18x) | \$0.568 (16x) |

‡ bills RAM used, not RAM reserved.

A sandbox that is almost idle can cost less with a provider that bills only busy CPU and used RAM. From the median sandbox up, boat is the cheapest.

Are your sandboxes idle most of the time? Then stop them, and resume them when work arrives. Use `boat stop` / `boat resume`, or the API. A stopped sandbox costs nothing and keeps its disk for 14 days.

## Performance

We ran the [hpc-sandbox-benchmarks](https://github.com/AnicetNgrt/hpc-sandbox-benchmarks) suite on the 4 vCPU / 8 GB machine of every provider. This is our `default` size. The main job is a Node.js build and test loop: bundle, lint, test, repeat. For the full results, read the [2026-08-24 leaderboard](https://github.com/AnicetNgrt/hpc-sandbox-benchmarks/blob/provider/ascii-box/docs/results/2026-08-24-cpu/leaderboard.md).

![The same Node.js build and test loop, 1,000 runs, time it takes per provider](https://mintcdn.com/ariana-1e97e6c3/qYEPg6P4ACx7GhnX/images/perf-vs-others.svg?fit=max\&auto=format\&n=qYEPg6P4ACx7GhnX\&q=85\&s=8c2cb140187a0a4b98ef3f076737a4b1)

| 4 vCPU / 8 GB | Runs per second | Seconds per 1,000 runs | \$/hour | \$ per million runs |
| - | - | - | - | - |
| **boat** | **27.7** | **36** s | **\$0.036** | **\$0.36** |
| Daytona | 18.6 | 54 s (1.5x slower) | \$0.331 | \$4.95 (14x) |
| Vercel Sandbox | 13.0 | 77 s (2.1x slower) | \$0.682 | \$14.61 (40x) |
| E2B | 11.2 | 89 s (2.5x slower) | \$0.331 | \$8.19 (23x) |
| Freestyle | 9.6 | 104 s (2.9x slower) | \$0.264 | \$7.62 (21x) |
| Modal † | 9.6 | 105 s (2.9x slower) | \$0.760 | \$22.07 (61x) |

That boat row is the machine every sandbox runs on.

† Modal: default runtime, cpu=4 in Modal units (the guest sees 4 CPUs; billed as 4 Modal cores) + 8 GiB. Its beta VM runtime did 15.1 runs per second. Priced as Modal bills that machine.

Measured on 2026-09-29: Vercel Sandbox · 2026-08-24: boat, Freestyle · 2026-07-23: Daytona, Modal, E2B. Rows from different runs are indicative, not a like-for-like race.

* The boat row is our standard machine, on AMD Ryzen 9 9950X hosts. Each sandbox is still a full virtual machine.
* We measured it with the same suite on 2026-08-24.
* Values are medians over several machines per provider. The 95% intervals are within ±20% of the medians.

## Worked examples

| You run | Per month |
| - | - |
| One `default` sandbox, 8 hours a day, 22 days | 176 h × \$0.036 = **\$6.34**, covered by the \$20 plan |
| One `default` sandbox 24/7 | 730 h × \$0.036 = **\$26**: the \$20 plan plus \$6 from the wallet |
| 50 `default` sandboxes, 4 hours a day, 22 days | 4,400 h × \$0.036 = **\$158**: the \$100 plan (300 at once) plus \$58 from the wallet |
| 200 `small` sandboxes, 1 hour each, once | 200 h × \$0.018 = **\$3.60**, covered by any plan |

## For the API

`GET /limits` gives the plan and the wallet:

| Field | Means |
| - | - |
| `wallet.balanceDollars` | Money in the wallet. Below zero when you owe. |
| `planIncluded.vmHours`, `planIncluded.vmHoursRemaining` | Included VM time of this billing period, in hours of `default`. `periodEnd` is when it resets. |
| `overagePrices` | The overage prices above. |

Each size uses VM time at its own rate:

| Size | Hours of `default` per hour of run time |
| - | - |
| `small` | 0.5 |
| `default` | 1 |
| `large` | 2 |
| `xlarge` | 5.56 |

* `boat usage <id>` and `GET /sandboxes/{id}/usage` give the bill of one sandbox. The size is already applied.
* `creditBalanceHours`, `packBalanceDollars` and the other `pack…` fields are deprecated. Read `wallet` and `planIncluded`.

For what happens when the wallet is empty, read [Plan, wallet and running out](https://docs.boat.dev/billing.md). For team plans and caps, read [Organizations](https://docs.boat.dev/organizations.md).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.