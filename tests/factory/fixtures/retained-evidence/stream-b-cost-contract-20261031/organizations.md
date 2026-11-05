> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# Teams and organizations

> One shared plan and wallet for a team: members and invites, seat price, which wallet a sandbox bills, shared sandboxes, per-member caps, and moving a plan between personal and organization.

To work as a team on boat, create an **organization**. It has one plan, one wallet, and members who run sandboxes on it.

* The organization pays the plan price once per seat. A 5-seat organization on the \$20 plan pays \$100 a month.
* Each seat adds the plan's included time. It adds the full limits on the \$2000 plan, and 20% of them below. Read [Seats, limits and caps](https://docs.boat.dev/organizations/seats-and-limits.md).
* Organizations get no free trial.
* The API and the CLI also call an organization `org`, and some fields call it `team` (`teamId`, `team_…` ids). All three name the same thing.

| What | Who sees or uses it |
| - | - |
| Sandboxes the organization pays for | Every member sees them all. |
| Shared sandboxes | Every member can use them. A sandbox is shared when it holds no personal logins and its creator did not make it private. |
| Snapshots and personal environments | Only the person who made them. |
| Organization environments and credential profiles | Every member uses them, unless an owner or admin [limits who can use them](#limit-who-can-use-an-environment-or-profile). Owners change them. See [Shared sandboxes](https://docs.boat.dev/organizations/shared-sandboxes.md#shared-environments-and-ai-credentials). |

For everyone who can reach a sandbox, in and out of the team, read [Security and isolation](https://docs.boat.dev/security.md#who-can-reach-a-sandbox).

## Members and invites

The owner invites people by email.

1. The person opens the link in the email.
2. The person signs in with any sign-in method.
3. The organization shows in their `boat org list` and in the **Viewing** dropdown of the dashboard.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat org create acme                 # you become its owner
boat org switch acme
boat org invite dana@example.com     # owner only
boat org members                     # members and pending invites
boat org transfer dana               # make dana the owner; you become a member
```

To remove a member, change roles or set per-member caps, use the [Organization](https://boat.dev/dashboard?tab=org) tab of the dashboard. When a member leaves, the sandboxes that they created go back to their personal billing.

## Limit who can use an environment or profile

By default, every member can use each organization environment and each organization credential profile. An owner or admin can limit an environment to a list of members. An owner can do the same for a profile.

| Setting | Who can use it |
| - | - |
| Everyone (default) | Every member of the organization |
| Only listed members | Owners, admins and the listed members |

A member who is not on the list:

* Does not see the environment or the profile in lists.
* Cannot create, resume or fork a sandbox in the environment. boat returns `403 environment_forbidden`.
* Cannot pick the profile. When an environment that they can use names the profile, their sandboxes get their own default profile.

Other rules:

* An API key acts as the person who created it. It never reaches more than that person can. The environment scope of a key limits it more.
* A change to the list does not change sandboxes that are already running.
* Teammates already cannot use a sandbox that holds another person's secrets. Read [Shared sandboxes](https://docs.boat.dev/organizations/shared-sandboxes.md).

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat env access agents --org acme                          # show the list
boat env access agents --org acme --only a@x.com,b@y.com   # only these members
boat env access agents --org acme --add c@z.com
boat env access agents --org acme --remove a@x.com
boat env access agents --org acme --everyone               # back to every member
boat ai profile access team-claude --only a@x.com          # same flags for a profile
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X PUT "$BOAT_API_BASE/environments/$ENV_ID?org=acme" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"access":{"restricted":true,"members":["a@x.com","b@y.com"]}}'

curl -sS -X PUT "$BOAT_API_BASE/credential-profiles/$PROFILE_ID" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"access":{"restricted":false,"members":[]}}'
```

* `members` takes member ids or the emails of active members. It replaces the full list.
* The environment and the profile objects return `access: { restricted, members }`, with member ids.
* A bad list returns `400 invalid_access`.

On the dashboard, open the environment page or the AI credentials page. The **Who can use this environment** or **Who can use this profile** panel has two choices: **Everyone in \<org>** or **Only the people ticked below**.

## Where to do what

| | CLI | API | SDKs | Dashboard |
| - | - | - | - | - |
| See your organizations | `boat org list` | `GET /orgs` | `listOrganizations` | **Viewing** dropdown |
| Set the active wallet | `boat org switch <org>` | `PATCH /orgs/active` | `setActiveOrganization` | sidebar **CLI and API keys bill … Change** |
| Bill one sandbox elsewhere | `boat --org acme new` | `org` on `POST /sandboxes`, or `X-Boat-Org` | `org` on `create` | select the organization in the sidebar |
| Create, transfer, delete | `boat org create` / `transfer` / `delete` | account API \* | not available | [Organization](https://boat.dev/dashboard?tab=org) |
| Members and invites | `boat org members` / `boat org invite` | account API \* | not available | [Organization](https://boat.dev/dashboard?tab=org) |
| Remove members, caps | not available | account API \* | not available | [Organization](https://boat.dev/dashboard?tab=org) |
| Seats | not available | account API \* | not available | [Billing](https://boat.dev/dashboard?tab=billing) viewing the org |
| See, share and unshare team sandboxes | `boat list` / `boat share` / `boat unshare` | `GET /sandboxes` / `POST /sandboxes/{id}/share` / `POST /sandboxes/{id}/unshare` | `sandboxes` / `share` / `unshare` | [Sandboxes](https://boat.dev/dashboard?tab=sandboxes), row menu |
| Start new sandboxes shared or private | `boat org default-visibility` | `PATCH /orgs/{org}` | `updateOrganization` | [Organization](https://boat.dev/dashboard?tab=team) |
| Org plan, wallet, auto top-up | `boat --org acme billing …` / `boat --org acme wallet …` | account API \* | not available | [Billing](https://boat.dev/dashboard?tab=billing) viewing the org |

\* The account API is the one that the dashboard uses. Its base is `https://boat.dev/api/boat`, not `$BOAT_API_BASE`. Organization routes are under `/teams/{org}/…` and billing routes under `/billing/…` with `teamId` in the body. These routes are not in the [v1 API reference](https://docs.boat.dev/api/v1.md) and can change.

The plan, the wallet and running out work the same on an organization as on a personal account. Read [Plan, wallet and running out](https://docs.boat.dev/billing.md).

## Learn more

> [card] [Which wallet a sandbox bills](https://docs.boat.dev/organizations/active-wallet.md)
>
> Set the active wallet, or bill one sandbox to another wallet.

> [card] [Shared sandboxes](https://docs.boat.dev/organizations/shared-sandboxes.md)
>
> What each member can do with a sandbox. Share a sandbox or make it private.

> [card] [Seats, limits and caps](https://docs.boat.dev/organizations/seats-and-limits.md)
>
> Buy seats, share start and concurrency limits, and cap each member.

> [card] [Move a personal plan in](https://docs.boat.dev/organizations/move-personal-plan.md)
>
> Move your personal sandboxes and plan to the organization.

> [card] [Card, invoices and plan changes](https://docs.boat.dev/billing/plan-changes.md)
>
> Cancel, downgrade, refunds, and move an organization plan back to personal.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.