> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Plan, wallet and running out

> What your plan includes and what the wallet pays for overage. Pay and auto top-up, the bonus table, billing commands, per-sandbox cost, how to control spend, and what happens when the wallet is empty.

[Pricing](https://docs.boat.dev/pricing.md) gives prices and sizes. This page tells what your plan includes and what your wallet pays. For the card, invoices, cancel and refunds, read [Card, invoices and plan changes](https://docs.boat.dev/billing/plan-changes.md).

## Plans

Your money goes to two places:

| | Plan | Wallet |
| - | - | - |
| What it is | A monthly price that your card pays | One balance in US dollars, per account or organization |
| It pays for | Your limits, and the VM time and saved snapshots that the plan includes | Overage: use past the plan |
| At the end of the billing period | Included amounts reset. Unused VM time expires. | Nothing changes. The money stays until you spend it. |
| You add to it | `boat billing plan 100` | `boat wallet pay 50`, or auto top-up |

The wallet never pays the plan. Stripe always charges the plan to your card.

For every amount, read [Plans](https://docs.boat.dev/pricing.md#plans).

Example: a \$20 plan. You use \$25 of VM time in one month. The plan pays the first \$20 (555 h of `default`). The wallet pays \$5.

## Wallet

Each account and each organization has one wallet, in US dollars.

* It pays only for what you use above your plan.
* It can go below zero during the [grace period](#running-out). The dashboard then shows what you owe, for example `-$3.20`.
* Money in your personal wallet stays personal. It does not move to an organization.
* For an organization, only the owner can add money or change auto top-up.

### Pay

Pay adds money to the wallet one time. You need a plan first.

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat wallet pay 50
```

On the dashboard, open the [Billing](https://boat.dev/dashboard?tab=billing) tab, enter an amount and click **Pay**. Stripe Checkout opens.

* Whole dollars, from \$15 to \$100,000.
* The dashboard and the CLI show the bonus before you pay.

### Bonus

A payment of \$200 or more gets a bonus. Pay and auto top-up get the same bonus. The bonus grows evenly on a log scale, from 2% at \$200 to 25% at \$10,000.

| You pay | Bonus | The wallet gets |
| - | - | - |
| \$15 to \$199 | none | the same amount |
| \$200 | +2% | \$204 |
| \$500 | +7.4% | \$537 |
| \$1,000 | +11.5% | \$1,115 |
| \$2,000 | +15.5% | \$2,310 |
| \$5,000 | +20.9% | \$6,045 |
| \$10,000 | +25% | \$12,500 |
| \$100,000 | +25% | \$125,000 |

### Auto top-up

Auto top-up adds money when the wallet runs low, so your sandboxes do not stop.

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat wallet card               # add a card (Stripe)
boat wallet auto-top-up 500    # add $500 each time the wallet runs low
boat wallet auto-top-up off
```

On the dashboard, open the [Billing](https://boat.dev/dashboard?tab=billing) tab, choose an amount and turn on **Auto top-up**.

* Choose an amount from \$15 to \$100,000. Each top-up gets the bonus.
* boat charges your card when the wallet drops below 10% of the amount, and never below \$5. Example: with \$500, the charge comes when the wallet drops below \$50.
* It needs a saved card and a paid plan. It does not work during the free trial.
* With more than one card, boat tries them in order.
* After 3 declined charges in a row, auto top-up turns itself off. The owner gets an email. Fix the card, then turn auto top-up on again.

## From the CLI

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat billing                   # plan, renewal date, included time left
boat billing plan 100          # start or change the plan
boat billing portal            # card and invoices (Stripe)
boat wallet                    # wallet balance, auto top-up, cards
boat wallet pay 50             # add $50 to the wallet
boat wallet auto-top-up 500    # turn on auto top-up with $500
boat wallet auto-top-up off
boat wallet card               # add a card
boat billing extra-starts on     # pay per extra start on the next invoice, see Limits
boat billing extra-starts off
boat limits                    # included time left, starts left, sandboxes at once
```

Add `--org <org>` to run them on an organization: `boat --org acme wallet pay 50`.

### From code

The wallet routes are part of the account API that the dashboard uses. Its base is `https://boat.dev/api/boat`, not `$BOAT_API_BASE`. These routes are not in the [v1 API reference](https://docs.boat.dev/api/v1.md) and can change. The API key needs `account.admin`.

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
API=https://boat.dev/api/boat
curl -sS "$API/billing/wallet" -H "Authorization: Bearer $BOAT_API_KEY"
# -> { balanceDollars, autoTopUp: { enabled, amountDollars, triggerBelowDollars, quote }, graceUntil, cards }

curl -sS "$API/billing/wallet/quote?dollars=1000" -H "Authorization: Bearer $BOAT_API_KEY"
# -> { dollars: 1000, bonusPercent: 11.5, bonusDollars: 115, creditedDollars: 1115 }

curl -sS -X POST "$API/billing/wallet/pay" -H "Authorization: Bearer $BOAT_API_KEY" \
  -H "Content-Type: application/json" -d '{"dollars": 1000}'
# -> { url, quote }   open url to pay in Stripe Checkout

curl -sS -X POST "$API/billing/wallet/auto-top-up" -H "Authorization: Bearer $BOAT_API_KEY" \
  -H "Content-Type: application/json" -d '{"enabled": true, "amountDollars": 500}'

curl -sS -X POST "$API/billing/wallet/cards" -H "Authorization: Bearer $BOAT_API_KEY"
# -> { url }   open url to add a card
```

* For an organization wallet, add `teamId` (the id or the name): in the query on `GET`, in the body on `POST`. Only the owner can call them.
* `pay` answers `402 subscription_required` without a plan.
* `auto-top-up` answers `409 requires_active_plan` during the trial. It answers `409 card_required` with an `addCardUrl` when no card is saved. boat keeps the amount. Open `addCardUrl`, then turn auto top-up on again.
* An amount out of range gives `400 invalid_amount`.

## Control your spend

A personal account has no dollar cap. Use these controls:

| Control | Effect |
| - | - |
| Leave auto top-up off | Spend stops at your plan and your wallet. Then the [running-out rules](#running-out) apply. |
| [Auto-stop](https://docs.boat.dev/long-running-tasks/auto-stop.md) | Each sandbox stops after its time, 1 hour by default. |
| `boat usage <id>`, the **Cost** column | Shows what one sandbox cost. Read [Per-sandbox usage](#per-sandbox-usage). |
| Per-member caps on an [organization](https://docs.boat.dev/organizations/seats-and-limits.md#per-member-caps) | Cap the time and the sandboxes of each member. |

A stopped sandbox costs nothing in VM time. Two charges continue while sandboxes are stopped:

* [Saved snapshots](https://docs.boat.dev/snapshots/templates.md) above your plan's included count: \$0.056 a day each, from the wallet.
* The [AI credentials proxy](https://docs.boat.dev/ai-credentials.md#pricing), while it is on: \$1 a day, from the wallet.

A stopped sandbox keeps its disk for free for 14 days only. Read [Keep a stopped sandbox longer than 14 days](https://docs.boat.dev/snapshots/stop.md#keep-a-stopped-sandbox-longer-than-14-days).

## Check your balance

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat wallet
boat limits
boat limits --json
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS "$BOAT_API_BASE/limits" \
  -H "Authorization: Bearer $BOAT_API_KEY"
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
const limits = await boat.limits();
console.log(limits.canStart, limits.starts?.day?.remaining, limits.wallet?.balanceDollars, limits.planIncluded?.vmHoursRemaining);
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
limits = boat.limits()
day = getattr(limits.starts, "day", None)
print(limits.can_start, getattr(day, "remaining", None), getattr(limits.wallet, "balance_dollars", None), getattr(limits.plan_included, "vm_hours_remaining", None))
```

`BOAT_API_BASE` is `https://boat.dev/api/v1`. `boat` is the SDK client from the [Quickstart](https://docs.boat.dev/quickstart.md#from-code). For every field, read [Get limits](https://docs.boat.dev/api/reference/account/get-boat-limits.md).

## Per-sandbox usage

Every sandbox meters its own machine time. A platform can bill its own users from the same numbers that your plan and your wallet pay.

In the dashboard:

* The **Sandboxes** page has a **Cost** column: what each sandbox cost this calendar month (UTC). Sort by it to find the most expensive one.
* The **Billing** page lists **Cost by sandbox this month**, most expensive first, with the total. For an organization, it lists every sandbox the organization pays for. One **Deleted sandboxes** line holds the machine time of sandboxes you deleted this month.

For all sandboxes in one call, add `include=cost` to the list:

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS "$BOAT_API_BASE/sandboxes?include=cost" -H "Authorization: Bearer $BOAT_API_KEY"
# -> sandboxes: [{ id, name, type, ..., cost: { since, seconds, dollars } }]
#    deletedCost: { since, seconds, dollars }   (sandboxes deleted this month)
```

Read one sandbox over any window, while it runs or after it stops:

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat usage bx_23456789
boat usage bx_23456789 --since 2026-09-01 --until 2026-10-01
boat usage bx_23456789 --json
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS "$BOAT_API_BASE/sandboxes/bx_23456789/usage?since=2026-09-01T00:00:00Z&until=2026-10-01T00:00:00Z" \
  -H "Authorization: Bearer $BOAT_API_KEY"
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
const usage = await boat.usage({ sandboxId: "bx_23456789", since: "2026-09-01T00:00:00Z", until: "2026-10-01T00:00:00Z" });
console.log(usage.seconds, usage.dollars, usage.running);
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
usage = boat.usage("bx_23456789", since="2026-09-01T00:00:00Z", until="2026-10-01T00:00:00Z")
print(usage.seconds, usage.dollars, usage.running)
```

| Field | Means |
| - | - |
| `seconds` | Billable machine time, with the size already applied. A `large` sandbox that ran ten minutes reads 1200. |
| `dollars` | `seconds` at list price. |
| `running` | `true` while the sandbox runs and the number grows. `false` after it stops, and while a refused stop keeps the meter paused. |

* boat never counts stopped time.
* boat does not count time after a [refused stop](https://docs.boat.dev/snapshots/stop.md#when-a-stop-is-refused).
* Omit `since` and `until` to get the full life of the sandbox.
* If a billing month ends while a sandbox runs, boat splits that stretch between the two months.

For every field, read [Get sandbox usage](https://docs.boat.dev/api/reference/sandboxes/get-sandbox-usage.md).

## AI credentials proxy

The [AI credentials proxy](https://docs.boat.dev/ai-credentials.md#the-ai-credentials-proxy) is paid from the wallet:

| Charge | Price | Paid by |
| - | - | - |
| Each UTC day the proxy is on | \$1 | The wallet of the account with the switch on |
| Proxied requests | \$1 per 1,000 | The wallet each sandbox bills |

`boat ai usage` and `GET /ai-usage` show the requests per sandbox, and `dollars` is their charge.

## Organizations

A team shares one plan and one wallet through an organization. Everything on this page applies to an organization in the same way. Read [Organizations](https://docs.boat.dev/organizations.md).

## Running out

When the wallet is empty:

* [Extra starts](https://docs.boat.dev/limits.md#extra-starts) fail with `rate_limited`, unless they are on your invoice.
* Saved snapshots above the included count get 7 days. Then boat deletes them. Read [When your wallet is empty](https://docs.boat.dev/snapshots/templates.md#when-your-wallet-is-empty).

When the wallet is empty and the plan's included time is used:

1. You get a **24-hour grace period**.
2. Your sandboxes keep running. boat sends you an email. Add money before anything stops.
3. If you do not pay in that window, boat stops your running sandboxes. Each stop takes a snapshot. boat stops them earlier if the grace period adds more new debt than 25% of the plan price, or \$50 on smaller plans.
4. Nothing is lost. Resume the sandboxes after you add money.

During the grace period, the wallet goes below zero:

* The wallet shows what you owe, for example `-$3.20`.
* Your next payment pays that amount first.
* You pay for exactly the seconds that you used.

If your plan ends and the wallet has money, running sandboxes keep running on the wallet. An organization drops to the limits of one seat.

## Related

* [Pricing](https://docs.boat.dev/pricing.md)
* [Card, invoices and plan changes](https://docs.boat.dev/billing/plan-changes.md)
* [Limits and errors](https://docs.boat.dev/limits.md)
* [Free trial](https://docs.boat.dev/free-trial.md)
* [Organizations](https://docs.boat.dev/organizations.md)
* [FAQ](https://docs.boat.dev/faq.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.