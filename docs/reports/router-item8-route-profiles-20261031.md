# Router item-8 profile implementation

This increment adds opt-in bounded profiles, not item-8 launch approval.
Exact four-field manifest inputs are generated directly from route_maximum in
[router-item8-route-maxima-20261031.json](router-item8-route-maxima-20261031.json).
No existing candidate, role binding, route chain, scenario cap or key was changed.

Claude Opus 4.5 compact reserves $3, small reserves $5. Both request at most
16384 output tokens, use an 8192 thinking budget, and retain $2.409600 for each
unknown maximum request. Another maximum request fits only while validated spend
is at most $0.590399/$2.590399 respectively. Compact serializes concurrent calls;
small can hold two. Neither profile starts with less than its reservation remaining.
Bare Opus 4.5 and unknown aliases remain unbounded. Existing Opus 5.5 profiles stay
unchanged. Public lifecycle status was Active on 2026-10-31, retirement not before
2026-11-24; later dispatch requires refreshed lifecycle/admission evidence.

Paid MiniMax M3.1 Flash pins tenstorrent/fp8, max_usd $0.690001, with a $.23
per-request hold even though requested output is clamped to 32768. The existing
DeepSeek paid route stays at $1.174406120. Source metadata, price caps, full
provider context/output bounds, strict terminal usage and per-request holds
support these maxima. Provider availability and response-model normalization are
not live-qualified. A failed generation without validated usage retains its hold.

## B3 adoption and money prerequisites

The new MiniMax address names the same underlying M3.1 Flash model but changes
billing/address/provider. It does not enter the old free-route chain. A reviewed
stream-D/B3 amendment must define compatibility, including quantization, effort,
gate fairness and carried scientific evidence. New Claude models likewise need
compatible new manifests; saved bindings must not be edited into eligibility.
No current saved candidate is asserted eligible for either profile.

With proposed paid bindings, scenarios 1–3 and 6 use MiniMax; 1–3 and 5–7 use
DeepSeek. Thus 1–3 and 5–7 need OpenRouter under those choices; 4 has no required
OpenRouter role. The empty OpenRouter :free endpoint list proves nothing about
OpenCode native free availability. No native free route is newly qualified here.
A subscription-only run of all seven cannot be promised under the fixed families.

All paid dispatch remains blocked until B3 supplies reviewed atomic reservation
and reconciliation across releases/scenarios for the lower of $11.63 and actual
available account credit. Existing total/list-equivalent job accounting alone is
not claimed to implement this paid sublimit. Pending, unknown, retry, replacement
and cross-release usage all count. There is no per-release regrant or top-up.
See [funding audit](router-item8-funding-20261031.md): no management key was found,
no account setting changed, factory key currently has no key-specific cap, and
account balance was $11.626127395. Dashboard steps explain cumulative limits.

## Evidence and limits

Pinned Claude 2.1.299 on macOS completed a two-request synthetic Read tool loop,
with full request/response bytes retained. Tests replay those bytes through the
actual gate and verify thinking, model/output controls, strict geo handling,
beta allowlisting, pricing and refusal before forwarding. This is no live model
quality evidence. Linux CLI equivalence and small-fast side calls remain unproved.
MiniMax tests use real public endpoint metadata and synthetic response traffic;
no actual MiniMax call was made. Existing cheap-route historical CLI proofs are
still attributed only to MiMo/DeepSeek, never to MiniMax.

Runtime interruption tests cover every Claude profile plus MiniMax through real
Store admission, ModelRuntime receipt production and job accounting, for HTTP 1.0,
HTTP 1.1 keep-alive and Connection:close. They require client/handler completion
before releasing upstream, retain exactly one unknown hold, release the lease,
and prove late replies cannot change the receipt and reconciliation is idempotent.
This is plain-HTTP loopback/process-boundary fault injection, not TLS/worker/cloud
cancellation acceptance.

Historical Opus 5.5 counter envelopes repriced at Opus 4.5 rates, including one
maximum request hold (no model/quality/tokenizer or per-request equivalence):

{
  "public": {
    "all": {
      "total": 153,
      "compact": 17,
      "small": 72
    },
    "writer": {
      "total": 31,
      "compact": 3,
      "small": 17
    }
  },
  "paid-deepseek": {
    "all": {
      "total": 32,
      "compact": 2,
      "small": 16
    },
    "writer": {
      "total": 25,
      "compact": 2,
      "small": 14
    }
  }
}

These aggregate counts are only potential invocation envelopes. They do not
reconstruct requests or establish useful writer/guard completion on Opus 4.5.

## Remaining

No Murphy row closes. OpenAI/Codex enforced maxima need a separate transport
increment. Useful writer/strong-calibrator feasibility, broader TLS/worker
cancellation and settlement, actual account 2 usage and natural account failover
remain unqualified. B3 adoption/cumulative paid enforcement and lifecycle checks
remain launch prerequisites. Full suite and fresh diff review records accompany
the commit; neither is a replacement for live acceptance.

Full suite: 161 test scripts run; 0 failed (exit 0). See
[unique suite record](router-item8-route-profiles-suite-20261031T151208Z-ece0a416.md).
