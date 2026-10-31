> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Seats, limits and caps

> Seat price (one plan price per seat), what a seat adds, buying seats, the shared start and concurrency limits, the shared wallet, and per-member caps.

## Seats

**One seat costs the plan price.** A 5-seat organization on the \$20 plan pays \$100 a month.

Each seat adds the plan's included time. So a 5-seat organization on the \$20 plan also gets \$100 of included time each month.

Seats add limits (sandboxes at once and starts) as follows:

| Plan | What one more seat adds to the limits |
| - | - |
| \$2000 | The full plan limits |
| \$20, \$100, \$500 | 20% of the plan limits. The total never goes above the limits of the next plan. |

To get higher limits, move to a bigger plan first. A bigger plan always gives more limits than the same money in seats. Organizations that had more than one seat on 28 October 2026 keep the full limits for those seats.

An organization pays for the larger of two numbers:

* Its members.
* The seats that the owner bought.

You do not need one person or one email for each seat. To pay for more seats than people, set the seat count. Use the [Billing](https://boat.dev/dashboard?tab=billing) tab with the organization selected, or call the account API. This route is not under `$BOAT_API_BASE` and is not in the v1 API reference:

```bash theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -X PUT https://boat.dev/api/boat/teams/acme/seats \
  -H "Authorization: Bearer $BOAT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"seats": 5}'
```

| Change | Result |
| - | - |
| Raise the count | The organization card pays the prorated difference at once. If the card fails, the seat count does not change. |
| A member joins | The member takes an empty seat at no extra cost. |
| A member joins and no seat is empty | Accepting the invite adds a seat. The organization card pays for it at once. If the card fails, the accept fails with "could not add the paid seat" and the invite stays unused. |
| Lower the count | You get credit on the next invoice, not a card refund. You cannot go below the number of members. |

* A seat counts accounts, not email addresses. Invites to email aliases such as `name+1@example.com`, accepted by the same account, add no seat. To get more seats, set the seat count.
* To add members, the organization needs an active plan.

## Shared limits

The included time, start-rate and concurrency numbers of the plan are **one shared pool for the whole organization**. The seats set the size of the pool, as in [Seats](#seats). For every limit, read [Limits and errors](https://docs.boat.dev/limits.md).

Example: 5 seats of \$20 against the \$100 plan, for the same \$100 a month:

| Limit | 5 seats of \$20 | \$100 plan, 1 seat |
| - | - | - |
| Included time per month | \$100 (2,777 h of `default`) | \$100 |
| Concurrent sandboxes | 180 | 300 |
| Starts per minute | 21 | 30 |
| Starts per hour | 108 | 210 |
| Starts per day | 360 | 840 |

* If one member uses all of the hourly start budget, boat refuses every other member's `new`, `fork` and `resume` billed to the organization. This lasts until the window rolls.
* Personal sandboxes use the member's own personal limits.
* The seat limits apply only while the organization's plan is active. Without a plan, money in the wallet still runs sandboxes, at the limits of a single seat.
* [Extra starts](https://docs.boat.dev/limits.md#extra-starts) use these shared limits as their included numbers.

## Per-member caps

One shared plan and one shared wallet mean one member can spend all of it. So the owner can cap each member on the [Organization](https://boat.dev/dashboard?tab=org) tab. Both caps are unlimited by default. These caps are the only spend caps in boat. A personal account has none: read [Control your spend](https://docs.boat.dev/billing.md#control-your-spend).

| Cap | Limits |
| - | - |
| Usage cap | That member's organization-billed machine time per billing window |
| Concurrent sandboxes | How many organization-billed sandboxes that member can run at once |

* The owner and admins set caps. Only the owner sets the owner's caps.
* Caps apply only to organization-billed sandboxes.
* A sandbox counts against the caps of its **creator**. This is also true when a teammate resumes it.

| Over the cap | `new`, `fork` and `resume` answer |
| - | - |
| Usage cap | `402 team_member_cap_reached` |
| Concurrent-sandbox cap | `429 member_limit_reached` |

In both cases, boat snapshots and stops the member's organization sandboxes within about a minute. Nothing is lost. The sandboxes can resume again when the owner raises the cap or the billing window renews.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.