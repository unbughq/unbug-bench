PASS

The diff2 blocker is resolved: the first non-null stop identity now rejects `superseded` immediately, before status polling or proof capture. The regression supersedes only that first observation, leaving later DTOs completed.

Read-only review against the design; no tests or live calls run.

Disposition: accepted; all earlier blockers fixed, none rejected. No full suite in this handoff.
