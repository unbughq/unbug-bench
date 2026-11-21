# Diff review 5 (confirm): verdict-code repin, commit 331efefc (goldfish)

Reviewer: fresh general-purpose subagent (implementation_readiness; Mode: REVIEW).

## Verbatim review (tables flattened)

Method: both trees extracted with `git archive`; digests recomputed the way `verdict_code()` does (`checkpoints.py:145-155`), same file tuples (`:130-133`), same pin rule.

Check 1, digests: 19b404be — bench raw 9511baae…, answers d4a7127a…; model raw c464ced1…, answers 802bfc8f…. 331efefc — bench raw 9511baae…, answers d4a7127a…; model raw a8c991fb…, answers 802bfc8f….
- New `to` equals the raw model digest of 331efefc, `a8c991fbf0c765fdc8debcacd730c23f630e05a54ad1aeaa3d89d26db9a11b55` (`invalid-runs-compat.json:76`).
- `from` 802bfc8f… is what 19b404be answers through its own pin, satisfying the rule above COMPAT (`checkpoints.py:137-138`).
- Bench pin untouched and still matches; no BENCH_VERDICT_CODE file changed.
- Follows the precedents 28a2f958 and 14d512bd.

Check 2, does the branch change any verdict? Model-effect receipts are written only for a settled success (`checkpoints.py:304-309`), keyed `[name, models, roles, root, ordinal, request]` (`:281`): the requested model, never the route, account or seat. Gate receipts: passes carry over, failures replay only under the same plumbing (`:329-331`), and this is a new plumbing release, so only cached passes and successes carry over.
- Claude order and Mythos-only claude-token (`model_router.py:185-188`, `eligible()` ~579-583): which login leases a `claude/` route; the receipt key has no account. A Mythos call on the small account would have failed and never produced a cached success.
- Worker `_account_order` filter (~987-990): availability, not output.
- NW burst and floor cooldown (`:425-433`, `free()` ~586-592, observe ~753-755): admission and blocking only.
- NW `rate` moving on (`model_runtime.py:411`): only the `router_deferred` decision (`:775`); cannot change a settled success; no failure carries across the release.
- Config hot reload: lane keys only, admission state only.
None can change what a cached model-stage receipt or gate pass means; the "changes no verdict" claim holds.

Check 3: the rest of the branch is docs, reviews, tests and a test fixture; 331efefc itself is the design doc, a review file and the one-line pin.

Findings:
1. NIT (design, Verdict-code pin section ~141): "which account or seat ... and when it retries" leaves out that NW `rate` now also moves the call to the next route; suggested "which account, route or seat".
2. NIT, process: `from` must be what the deployed release answers (`checkpoints.py:137`); confirmed for 19b404be (origin/main tip), not that the VM runs it. Check before deploying.

No BLOCKING findings. **PASS**

## Response (elephant)
- NIT 1: wording changed to "account, route or seat".
- NIT 2: checked read-only on the control VM: `source-current` -> `source-19b404be`, the router's `ExecStart` runs `source-19b404be`, and that tree answers model `802bfc8f…`, bench `d4a7127a…`. Recorded in the design.
