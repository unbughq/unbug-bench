# Provider waits design review 4

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

FAIL

- **Blocker — earlier serial waits can affect the current result.** [Design lines 60–64](/private/tmp/unbug-wp1-terminal-20261105/docs/designs/durable-execution-provider-waits.md:60) clear the collection once per step and select from waits collected during that step. In `de/wp5a@41861e4`, `factory/run.py:267–270` adds both the terminal wait and `error.previous_waits` to that collection. `factory/model_runtime.py:504–515` can retain earlier serial failures unchanged when a later lease-finish raises `router_unavailable`. An earlier credential failure or later reset can therefore win incorrectly. Select the terminal wait for each currently stopped logical call; preserve earlier waits for usage evidence only. Test both an earlier credential failure and an earlier longer reset.

- **Blocker — reset validation and fallback are unspecified.** [Design lines 58–64](/private/tmp/unbug-wp1-terminal-20261105/docs/designs/durable-execution-provider-waits.md:58) require the latest “valid” reset without defining validity or what happens when none qualifies. `de/wp5a@41861e4:factory/model_router.py:552–555` accepts finite past or far-future values, while [classify.py](/private/tmp/unbug-wp1-terminal-20261105/factory/durable/classify.py:172) accepts only future resets within eight days and otherwise uses 900 seconds. Specify validation before selecting the maximum and the no-valid-reset fallback; reconcile the eight-day cap with the design’s promise to sleep until the recorded reset. Test mixed valid and invalid resets, past and out-of-range values, and no valid reset.

The supervisor-derived pre-restore cutoff and slow-restore test are specified in [design lines 74–79](/private/tmp/unbug-wp1-terminal-20261105/docs/designs/durable-execution-provider-waits.md:74). The WP1 policy and fake-test slice may proceed under the founder’s decision; real integration remains gated on WP5a and WP8.

No files were changed; no tests, databases, checkout, or network were used.

---

## Resolution

| Finding | Disposition |
|---|---|
| Earlier serial waits | Revision 5 selects the terminal wait of each currently stopped logical call and retains prior waits only as usage evidence; fresh review and real WP5a integration remain pending. |
| Reset validation | Revision 5 matches the classifier's finite future, eight-day maximum and 900-second fallback, specifies selection before the maximum, and lists boundary tests; fresh review and real WP5a integration remain pending. |
