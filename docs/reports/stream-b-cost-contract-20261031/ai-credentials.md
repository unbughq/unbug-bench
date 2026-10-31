> ## Documentation Index
> Fetch the complete documentation index at: https://docs.boat.dev/llms.txt
> Use this file to discover all available pages before exploring further.

# AI credentials and proxy

> Credential profiles, a second Claude or ChatGPT account when one runs out of credits, custom APIs, AI usage, and the proxy that keeps real keys out of your sandboxes.

Your sandboxes get the AI credentials of a **credential profile**: Claude and ChatGPT sign-ins, API keys, and custom APIs. With the **AI credentials proxy** on, a sandbox gets placeholder keys, and the real keys stay with boat.

| You want | Page |
| - | - |
| Connect your first key or subscription, or pass the keys of your users with `-e` | [Keys and subscriptions](https://docs.boat.dev/integrated-agents/keys.md) |
| Share keys with a team, switch accounts, keep keys out of sandboxes, see AI usage | This page |

| | CLI | API | SDKs |
| - | - | - | - |
| List profiles | `boat ai profiles` | `GET /credential-profiles` | `listCredentialProfiles` |
| Create a profile | `boat ai profile new <name>` | `POST /credential-profiles` | `createCredentialProfile` |
| Rename, make default | `boat ai profile rename` / `default` | `PUT /credential-profiles/{profile}` | `updateCredentialProfile` |
| Delete a profile | `boat ai profile rm <name>` | `DELETE /credential-profiles/{profile}` | `deleteCredentialProfile` |
| Set, remove an API key | `boat ai profile set-key` / `rm-key` | `PUT`, `DELETE /credential-profiles/{profile}/keys/{credential}` | `setCredentialProfileKey`, `deleteCredentialProfileKey` |
| Switch a credential to another account | `boat ai accounts` / `switch` | `GET /credential-profiles/{profile}/accounts/{credential}`, `PUT …/{account}/active` | `listCredentialAccounts`, `switchCredentialAccount` |
| Add, forget an account | `boat ai add-account` / `forget-account` | `POST /credential-profiles/{profile}/accounts/{credential}`, `DELETE …/{account}` | `addCredentialAccount`, `deleteCredentialAccount` |
| Set, remove a custom API | `boat ai profile set-api` / `rm-api` | `PUT`, `DELETE /credential-profiles/{profile}/custom-apis/{name}` | `setCredentialProfileCustomApi`, `deleteCredentialProfileCustomApi` |
| Proxy on or off | `boat ai proxy [on\|off]` | `GET`, `PUT /ai-proxy` | `getAiProxy`, `updateAiProxy` |
| Usage | `boat ai usage [id]` | `GET /ai-usage`, `GET /sandboxes/{id}/ai-usage` | `getAiUsage`, `getSandboxAiUsage` |
| Block, unblock a sandbox | `boat ai block` / `unblock` | `PUT /sandboxes/{id}/ai-access` | `setSandboxAiAccess` |

The profile and proxy calls need an API key with `account.admin`. Account usage needs `account.read`. Sandbox usage needs `sandbox.read` on that sandbox.

## Credential profiles

A credential profile is a named set of AI credentials. boat encrypts it at rest. The API never returns a secret value: it lists which credentials a profile holds (`connected`) and the names of its custom APIs.

Each account has one **default** profile. A sandbox gets the default profile of its owner, unless its environment names another profile. The credentials you had before profiles existed are now the profile named `default`. On the dashboard **Agents & Proxying** page, pick a profile at the top. Both tabs then show and edit only that profile: its sign-ins and keys, its proxy switch, its custom APIs and its usage.

| Credential | Kind | Set it with |
| - | - | - |
| `anthropic-api-key`, `openai-api-key`, `openrouter-api-key`, `llmgateway-api-key`, `deepseek-api-key`, `moonshot-api-key`, `mistral-api-key`, `xai-api-key`, `opencode-api-key` | API key | `set-key`, or the Agents & Proxying page |
| `claude-subscription`, `chatgpt-subscription`, `kimi-subscription`, `mistral-vibe-subscription`, `grok-subscription` | Sign-in | The Agents & Proxying page |
| `claude-bedrock`, `codex-bedrock` | AWS Bedrock | The Agents & Proxying page |

You can remove any credential with `rm-key`. A sign-in sent to `set-key` returns `400 not_an_api_key`.

### Out of credits? Switch to another account

A credential can hold several accounts: two ChatGPT sign-ins, two Claude sign-ins, two OpenAI keys. One account is in use. When it runs out of credits, switch the credential to another account. Every sandbox that uses the profile gets the other account at once, running sandboxes included. Nothing restarts, and the other credentials do not change.

On the dashboard **Agents & Proxying** page, the account in use shows next to each credential. Click it to:

* **switch** to another account,
* **add another account**: sign in again, or paste another key. The current account stays, ready to switch back to,
* **forget** an account. Forgetting the one in use switches to another account first.

Sign-ins renew only while in use. An account set aside keeps its sign-in as it was, and renews when you switch back to it.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat ai accounts chatgpt-subscription
#  #  ACCOUNT          
#  1  you@work.dev     in use
#  2  you@home.dev
boat ai switch chatgpt-subscription 2

# API keys: add a second key, then switch by number, or by its last characters
echo "$OPENAI_API_KEY_2" | boat ai add-account openai-api-key
boat ai switch openai-api-key …7f3a

boat ai forget-account openai-api-key 2
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS "$BOAT_API_BASE/credential-profiles/default/accounts/chatgpt-subscription" \
  -H "Authorization: Bearer $BOAT_API_KEY"

# use the id of the account to switch to, from the list
curl -sS -X PUT "$BOAT_API_BASE/credential-profiles/default/accounts/chatgpt-subscription/$ACCOUNT_ID/active" \
  -H "Authorization: Bearer $BOAT_API_KEY"

curl -sS -X POST "$BOAT_API_BASE/credential-profiles/default/accounts/openai-api-key" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"value":"'"$OPENAI_API_KEY_2"'"}'
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
const { accounts } = await sandbox.listCredentialAccounts({ profile: "default", credential: "chatgpt-subscription" });
const other = accounts.find((a) => !a.active)!;
await sandbox.switchCredentialAccount({ profile: "default", credential: "chatgpt-subscription", account: other.id });
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
accounts = sandbox.list_credential_accounts("default", "chatgpt-subscription").accounts
other = next(a for a in accounts if not a.active)
sandbox.switch_credential_account("default", "chatgpt-subscription", other.id)
```

`--profile` picks another profile; the default is your default profile. The account list never shows a secret: a sign-in shows its email when the provider gives it, a key shows its last characters.

To give different sandboxes different accounts at the same time, use one profile per account and name the profile on an environment (see [Environments](#environments)).

### Set and remove API keys

`--copy-from` starts a new profile with a copy of the API keys and custom APIs of a profile you manage. Sign-ins are not copied: one sign-in in two profiles would sign itself out at the first renewal. Sign in again on the new profile. The CLI reads a key from stdin when you omit the value, so the key stays out of your shell history. A key is one token of up to 8192 printable characters, without spaces or line breaks; anything else returns `400`.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat ai profile new ci --copy-from default
echo "$ANTHROPIC_API_KEY" | boat ai profile set-key ci anthropic-api-key
boat ai profile rm-key ci claude-subscription
boat ai profile rename ci ci-bots
boat ai profile rm ci-bots
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X POST "$BOAT_API_BASE/credential-profiles" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"name":"ci","copyFrom":"default"}'

curl -sS -X PUT "$BOAT_API_BASE/credential-profiles/ci/keys/anthropic-api-key" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"value":"'"$ANTHROPIC_API_KEY"'"}'

curl -sS -X DELETE "$BOAT_API_BASE/credential-profiles/ci/keys/claude-subscription" \
  -H "Authorization: Bearer $BOAT_API_KEY"

curl -sS -X DELETE "$BOAT_API_BASE/credential-profiles/ci" -H "Authorization: Bearer $BOAT_API_KEY"
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
await sandbox.createCredentialProfile({ name: "ci", copyFrom: "default" });
await sandbox.setCredentialProfileKey({
  profile: "ci",
  credential: "anthropic-api-key",
  value: process.env.ANTHROPIC_API_KEY!,
});
await sandbox.deleteCredentialProfileKey({ profile: "ci", credential: "claude-subscription" });
await sandbox.deleteCredentialProfile({ profile: "ci" });
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
import os
from boat_sdk.models.create_credential_profile_request import CreateCredentialProfileRequest
from boat_sdk.models.set_credential_key_request import SetCredentialKeyRequest

sandbox.create_credential_profile(CreateCredentialProfileRequest(name="ci", copy_from="default"))
sandbox.set_credential_profile_key("ci", "anthropic-api-key", SetCredentialKeyRequest(value=os.environ["ANTHROPIC_API_KEY"]))
sandbox.delete_credential_profile_key("ci", "claude-subscription")
sandbox.delete_credential_profile("ci")
```

Running sandboxes that use the profile get a changed key. You cannot delete a default profile (`409 is_default`) or a profile that an environment names (`409 in_use`).

### Organization profiles

An organization can own profiles too. By default, every active member can use them. An owner can limit a profile to a list of members with `boat ai profile access`. Read [Limit who can use an environment or profile](https://docs.boat.dev/organizations.md#limit-who-can-use-an-environment-or-profile). Only organization owners create and change them, and only they see the account list. In a profile list, `owner.kind` is `org` and `canManage` tells you if you can change it.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat --org acme ai profile new team-claude
echo "$ANTHROPIC_API_KEY" | boat ai profile set-key team-claude anthropic-api-key
boat ai profiles --org-only
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X POST "$BOAT_API_BASE/credential-profiles" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"name":"team-claude","org":"acme"}'
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
await sandbox.createCredentialProfile({ name: "team-claude", org: "acme" });
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
sandbox.create_credential_profile(CreateCredentialProfileRequest(name="team-claude", org="acme"))
```

To give the sandboxes of an organization the organization profile, name it on an organization environment. See [Shared sandboxes](https://docs.boat.dev/organizations/shared-sandboxes.md#shared-environments-and-ai-credentials).

### Your own Claude sign-in in a sandbox

A Claude Code credential in your profile sets variables in the sandbox's shells:

| Credential | Variables |
| - | - |
| Claude subscription | `CLAUDE_CODE_OAUTH_TOKEN` |
| OpenRouter or DeepSeek key for Claude Code | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` |

Claude Code prefers these variables to a sign-in. Remote Control needs a full claude.ai sign-in. To use it, run `claude` in the sandbox and sign in with `/login`. From the next shell, boat removes the three variables above, and `claude` uses your sign-in. boat never removes that sign-in: it stays across stops, resumes and cold resumes. The agent that `boat prompt` runs still uses the profile.

## Custom APIs

A custom API is a secret for any HTTPS API, such as Stripe or your own service. You give it a name, a value and a base URL. The sandbox gets two variables:

| Variable | Value |
| - | - |
| `<NAME>` | The secret. A placeholder when the proxy is on |
| `<NAME>_BASE_URL` | The base URL. The proxy URL when the proxy is on |

The name is an environment variable name: `A-Z`, `0-9` and `_`, up to 64 characters. Provider names (`ANTHROPIC_*`, `OPENAI_*`, `AWS_*`, and so on) and names that end in `_BASE_URL` are reserved. The base URL must use HTTPS on the default port, with a public DNS name.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
echo "$STRIPE_KEY" | boat ai profile set-api default STRIPE_KEY --base-url https://api.stripe.com/v1
boat ai profile rm-api default STRIPE_KEY
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X PUT "$BOAT_API_BASE/credential-profiles/default/custom-apis/STRIPE_KEY" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"value":"'"$STRIPE_KEY"'","baseUrl":"https://api.stripe.com/v1"}'

curl -sS -X DELETE "$BOAT_API_BASE/credential-profiles/default/custom-apis/STRIPE_KEY" \
  -H "Authorization: Bearer $BOAT_API_KEY"
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
await sandbox.setCredentialProfileCustomApi({
  profile: "default",
  name: "STRIPE_KEY",
  value: process.env.STRIPE_KEY!,
  baseUrl: "https://api.stripe.com/v1",
});
await sandbox.deleteCredentialProfileCustomApi({ profile: "default", name: "STRIPE_KEY" });
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
from boat_sdk.models.set_custom_api_request import SetCustomApiRequest

sandbox.set_credential_profile_custom_api("default", "STRIPE_KEY", SetCustomApiRequest(
    value=os.environ["STRIPE_KEY"],
    base_url="https://api.stripe.com/v1",
))
sandbox.delete_credential_profile_custom_api("default", "STRIPE_KEY")
```

Code in the sandbox must send its requests to `$<NAME>_BASE_URL`. With the proxy on, a request sent straight to the API with the placeholder fails.

## The AI credentials proxy

Without the proxy, a sandbox holds your real keys and sign-ins. Anyone with a shell in it can copy them. With the proxy on, the real keys never enter the sandbox.

```text theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
 sandbox                              Boat                              provider
 ANTHROPIC_API_KEY=<placeholder>
 ANTHROPIC_BASE_URL=<Boat proxy>
 agent ── request + placeholder ──▶  proxy: placeholder valid?
                                       sandbox blocked?
                                       swap in the real key  ── request + real key ──▶  api.anthropic.com
       ◀──────── reply ─────────────  count tokens  ◀─────────── reply ──────────────
```

| | The sandbox holds | boat holds |
| - | - | - |
| Proxy off | The real keys and sign-ins | The real keys and sign-ins |
| Proxy on | Placeholders and the proxy URL | The real keys and sign-ins, and renews the sign-ins |

* A placeholder is worthless outside boat. It does not contain the real key.
* A copied placeholder stops working when the sandbox stops. Each start gives the sandbox new placeholders.
* The proxy sends each credential only to its own provider. An Anthropic key never goes to another host.
* The proxy puts a provider key only in the `Authorization` or `x-api-key` header. A placeholder in another header or in the URL stays a placeholder, so a provider that echoes it cannot return the real key.
* A custom API gets its secret in any request header and in the query string, never in the path. Pick a base URL you trust: a host that echoes requests shows the secret to the sandbox.
* boat renews Claude, ChatGPT and Grok sign-ins behind the proxy. The sandbox never sees a renew token.

### What the proxy covers

| Proxied | Not proxied |
| - | - |
| Claude sign-in and Anthropic API key (Claude Code) | AWS Bedrock (`claude-bedrock`, `codex-bedrock`) |
| ChatGPT sign-in and OpenAI API key (Codex) | Kimi Code sign-in (`kimi-subscription`) |
| OpenRouter, LLM Gateway, DeepSeek, Moonshot API keys | |
| Mistral API key and Mistral Vibe sign-in | |
| Grok sign-in and xAI API key | |
| OpenCode key (Go and pay-as-you-go) | |
| Custom APIs | |

Bedrock signs each request with AWS keys, so there is nothing to swap. The Kimi Code CLI renews its sign-in itself. While the proxy is on, boat withholds these credentials from sandboxes. Use a Moonshot API key in place of the Kimi sign-in.

### Turn it on

The switch is per account: one for you, one for each organization. Only an organization owner can change the organization switch. On the dashboard, open **Agents & Proxying**, then the **Proxying** tab. It holds the switch, the custom APIs and the AI usage, for the account in view: you, or the organization you selected.

A sandbox goes through the proxy when either switch is on:

* the switch of the account that owns its credential profile, or
* the switch of the organization that pays for the sandbox. An organization can make sure that no real key enters its sandboxes, whoever's profile they use.

Running sandboxes switch at their next start. Stop and resume a sandbox to switch it now.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat ai proxy               # state and price
boat ai proxy on
boat --org acme ai proxy on
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS "$BOAT_API_BASE/ai-proxy" -H "Authorization: Bearer $BOAT_API_KEY"

curl -sS -X PUT "$BOAT_API_BASE/ai-proxy" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"enabled":true}'

curl -sS -X PUT "$BOAT_API_BASE/ai-proxy?org=acme" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"enabled":true}'
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
const proxy = await sandbox.getAiProxy();
console.log(proxy.enabled, proxy.pricing);

await sandbox.updateAiProxy({ enabled: true });
await sandbox.updateAiProxy({ org: "acme", enabled: true });
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
from boat_sdk.models.update_ai_proxy_request import UpdateAiProxyRequest

proxy = sandbox.get_ai_proxy()
print(proxy.enabled, proxy.pricing)

sandbox.update_ai_proxy(UpdateAiProxyRequest(enabled=True))
sandbox.update_ai_proxy(UpdateAiProxyRequest(enabled=True), org="acme")
```

The proxy applies to sandboxes that use a profile of an account with the switch on. A sandbox that uses an organization profile follows the organization switch.

## Safe for third parties, with AI credentials

An environment marked [safe for third parties](https://docs.boat.dev/environments.md#safe-for-third-parties) passes nothing of yours. Turn on `proxyAiCredentials` on that environment to still pass AI credentials, as placeholders. The sandbox user can run the agents, but cannot take your keys. You can block the sandbox at any time.

`proxyAiCredentials` needs the proxy on for the account that owns the profile. If it is off, the call returns `400 ai_proxy_off`.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat ai proxy on
boat env set customers --safe-for-third-parties true --proxy-ai-credentials true --credential-profile ci
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X PUT "$BOAT_API_BASE/environments/$ENV_ID" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"safeForThirdParties":true,"proxyAiCredentials":true,"credentialProfileId":"ci"}'
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
await sandbox.updateEnvironment({
  environmentId: envId,
  safeForThirdParties: true,
  proxyAiCredentials: true,
  credentialProfileId: "ci",
});
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
from boat_sdk.models.update_sandbox_environment_request import UpdateSandboxEnvironmentRequest

sandbox.update_environment(env_id, UpdateSandboxEnvironmentRequest(
    safe_for_third_parties=True,
    proxy_ai_credentials=True,
    credential_profile_id="ci",
))
```

## Environments

An environment can name the profile its sandboxes get, with `credentialProfileId` (an id or a name). `null`, or `--credential-profile default` in the CLI, means the default profile of the sandbox owner. Like every environment change, this makes a new version. Running sandboxes move at `boat env upgrade`. See [Environments](https://docs.boat.dev/environments/access.md#ai-credentials).

## Usage

For each proxied sandbox, boat counts requests and errors, and the tokens per UTC day, credential and model. The token counts are the numbers the provider reports in its replies: input, output, cache read and cache write. A sandbox that holds real keys has no usage here, because its requests do not go through boat.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat ai usage                       # every sandbox of the account in scope
boat ai usage bx_23456789 --days 7  # one sandbox, per day and model
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS "$BOAT_API_BASE/ai-usage?days=30" -H "Authorization: Bearer $BOAT_API_KEY"
curl -sS "$BOAT_API_BASE/sandboxes/bx_23456789/ai-usage?days=7" -H "Authorization: Bearer $BOAT_API_KEY"
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
const account = await sandbox.getAiUsage({ days: 30 });
for (const s of account.sandboxes) console.log(s.sandboxId, s.totals.requests, s.dollars);

const one = await sandbox.getSandboxAiUsage({ sandboxId: "bx_23456789", days: 7 });
console.log(one.blocked, one.totals.inputTokens, one.totals.outputTokens);
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
account = sandbox.get_ai_usage(days=30)
for s in account.sandboxes:
    print(s.sandbox_id, s.totals.requests, s.dollars)

one = sandbox.get_sandbox_ai_usage("bx_23456789", days=7)
print(one.blocked, one.totals.input_tokens, one.totals.output_tokens)
```

The account view covers the wallet in scope: your own, or an organization with `--org`, `org` or `X-Boat-Org`. In the dashboard, open the **⋯** menu of a sandbox and select **AI usage**.

`dollars` in these responses is the boat proxy charge: \$1 per 1,000 requests. It is not your provider bill. The provider bills your tokens on your own provider account.

### Cap AI spend

boat has no automatic AI spend cap. The member spend cap of an organization limits sandbox time, not provider tokens. To cap AI spend yourself:

1. Read the usage of each sandbox with `GET /sandboxes/{id}/ai-usage` on a schedule.
2. When the tokens pass your limit, [block the sandbox](#block-a-sandbox).

This works only for proxied sandboxes. Also set a spend limit in the console of your provider.

### Block a sandbox

Block a sandbox to stop its AI requests at once, running or stopped. The proxy refuses its placeholders with `403`. Unblock it to accept them again. Blocking has no effect on a sandbox that holds real keys (proxy off). The sandbox creator and the managers of its profile can block it.

```bash CLI theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
boat ai block bx_23456789
boat ai unblock bx_23456789
```

```bash curl theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
curl -sS -X PUT "$BOAT_API_BASE/sandboxes/bx_23456789/ai-access" \
  -H "Authorization: Bearer $BOAT_API_KEY" -H "Content-Type: application/json" \
  -d '{"blocked":true}'
```

```ts TypeScript theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
await sandbox.setSandboxAiAccess({ sandboxId: "bx_23456789", blocked: true });
await sandbox.setSandboxAiAccess({ sandboxId: "bx_23456789", blocked: false });
```

```python Python theme={"theme":{"light":"github-light","dark":"github-dark-default"}}
from boat_sdk.models.set_sandbox_ai_access_request import SetSandboxAiAccessRequest

sandbox.set_sandbox_ai_access("bx_23456789", SetSandboxAiAccessRequest(blocked=True))
sandbox.set_sandbox_ai_access("bx_23456789", SetSandboxAiAccessRequest(blocked=False))
```

## Pricing

Profiles, custom APIs and usage tracking are free. The proxy costs money. The [wallet](https://docs.boat.dev/billing.md#wallet) pays it, not the plan's included time:

| Charge | Price | Paid by |
| - | - | - |
| Each UTC day the proxy is on | \$1 | The wallet of the account with the switch on |
| Proxied requests | \$1 per 1,000 | The wallet each sandbox bills |

`dollars` in the usage responses is the request charge for the period. It does not include the daily charge. The provider bills your tokens as usual, on your own provider account.

## Related

* [Keys and subscriptions](https://docs.boat.dev/integrated-agents/keys.md)
* [Environments](https://docs.boat.dev/environments.md)
* [Organizations](https://docs.boat.dev/organizations.md)
* [Integrated agents](https://docs.boat.dev/integrated-agents.md)
* [Pricing](https://docs.boat.dev/pricing.md)
* [CLI reference](https://docs.boat.dev/cli-reference.md#boat-ai)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.