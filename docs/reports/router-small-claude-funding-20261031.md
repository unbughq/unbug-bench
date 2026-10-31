## Read-only funding check

2026-10-31: GET https://openrouter.ai/api/v1/key reports key limit remaining
$0.409068839. GET /api/v1/credits separately reports account balance
$11.626127395. Only dollar amounts are retained; no credential, identity, key
label, fingerprint or raw authenticated response is saved. No account change.
Authenticated /api/v1/models lists no free MiniMax or DeepSeek route, including
the previously configured minimax/minimax-m3.1-flash:free. OpenCode public docs
list DeepSeek V4.1 Flash Free, but its native factory maximum remains unqualified.
The current OpenCode model/price list has no free MiniMax entry; paid MiniMax
M3/M2.7/M2.5 are listed. Do not assume availability from the stale router chain. Neither native free route currently passes route_maximum.
DeepSeek can fall back to the existing capped paid route, whose $1.174406121
invocation reservation already exceeds this key remaining credit. Scenarios
1–3/6 require MiniMax; 1–3/5–7 require DeepSeek. Thus existing spendable credit
plus qualified free routes do not establish coverage of their scenario caps;
account balance is not an authorization to increase the key cap or top up.
No paid calls were made. Source: OpenRouter key/credits/models GET endpoints,
https://openrouter.ai/docs/api_reference/limits and
https://opencode.ai/v2/docs/console/models/ .

Requested scenarios 1, 2, 3, 5, 6, 7 have model caps $10, $10, $5, $15,
$25, $10 respectively ($75 total). These are all-in model/list-equivalent caps,
not predicted OpenRouter spend. No current free route qualifies for admission:
DeepSeek Free is family-compatible but lacks a factory maximum; no current
free MiniMax is listed. The $0.409068839 key allowance is below the existing
$1.174406121 paid DeepSeek lease reservation. No claim that the account's
$11.626127395 would cover all six caps or the as-yet-unpriced MiniMax work is
justified. No credit limit, purchase or top-up was changed.
