BLOCKERS

- `factory/boat_lifecycle.py`, stop-status validation: `{"id": worker, "stop": null}` raises uncaught `AttributeError`. Neither capture nor deletion catches it, so malformed provider data produces no fixed `invalid_response` receipt and aborts ordinary safety deletion. Validate the status envelope before calling `.get()`; test through the real capture path.

- Failed-capture replay can repeat the stop request while `info.stop` remains null. The retained `stop-request.json` is ignored. A successful stop followed by an info failure and a pre-claim deletion failure allows the next capture to issue stop again. Continue identity polling from the retained request, within the original deadline.

- `stopped_info` polling ignores a same-ID `superseded` status while state remains transitional. A later completed observation could therefore commit proof despite observing supersession. Refuse superseded observations immediately and add a transition test.

The original deadline and strict final settlement predicates remain intact. The live trigger remains unknown. No tests or live calls were run during this review.

Disposition: all three accepted and fixed with regressions; no rejection.
