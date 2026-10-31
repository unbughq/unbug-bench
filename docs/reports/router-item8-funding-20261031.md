# Item-8 OpenRouter funding audit

2026-10-31, read-only audit after founder authorization to use existing credit.
The control VM encrypted factory secret bundle was decrypted into process memory
using the existing scoped identity. No secret value, identifier/hash, raw API
response or decrypted file was printed or persisted. No provider settings changed,
no credit added, and no inference request was made.

No nonempty OpenRouter management/provisioning/admin credential label exists in
the bundle; no other management/provisioning/admin candidate label exists either.
A second read-only pass checked every nonempty OpenRouter-labelled archive entry.
The only usable credential is `openrouter-key`, which reports
is_provisioning_key=false. Its `._openrouter-key` companion is non-UTF8 archive
metadata, not an ASCII API credential; no request was sent with its contents.
Only management credentials can call the key-update API.

Current GET /api/v1/key: limit and limit_remaining both null (no key-specific
spend ceiling); cumulative usage $31.494136472. Current GET /api/v1/credits:
remaining account credit $11.626127395. The earlier $0.409068839 remaining-key
observation is not the current state. This audit cannot attribute the change.

No increase is currently needed to remove a key cap. Item-8 must still limit new
paid settled+unknown+pending spend across all releases to the lower of $11.63 and
available account credit; balance is not new authority or a reason to top up.

## Founder dashboard steps

1. Sign in to https://openrouter.ai/settings/keys in the factory account/workspace.
2. Locate the existing factory inference key and open its row menu, then Edit.
   Do not delete/recreate it or reveal/copy its secret.
3. Inspect Key limit / Credit limit and the reset interval. The API currently
   reports no limit. If the goal is to permit existing credit, leave that as-is;
   the account already has only $11.626127395 credit.
4. If setting a protective one-time lifetime cap, choose no reset. OpenRouter's
   limit is cumulative, not additional credit. To allow $11.63 additional at
   the observed usage, the absolute limit is $43.124136472, subject to fresh
   usage verification. Entering $11.63 as the absolute lifetime limit would
   immediately exhaust this already-used key. This differs from the literal
   requested $11.63 limit, so no such adjustment was made by the agent.
5. Save only the intended limit/reset change. Leave billing/top-up controls alone.
   Recheck key-info limit, usage and limit_remaining; account credit remains the
   separate lower bound. Do not enter a key value in chat or shell arguments.

Sources: https://openrouter.ai/docs/api/api-reference/api-keys/update-keys
and https://openrouter.ai/docs/api-reference/limits . PATCH requires a management
key and exposes limit separately from usage/limit_remaining.
