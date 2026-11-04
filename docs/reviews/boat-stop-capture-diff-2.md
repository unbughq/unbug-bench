BLOCKERS

- `factory/boat_lifecycle.py:607–612`: identity polling accepts a stop whose status is already `superseded`. If subsequent by-ID status and stopped-info observations report `completed`, capture can commit proof despite having observed supersession. Reject `superseded` immediately when identity first appears. Add a regression where only that first identity observation is superseded; later observations complete normally.

The three review1 fixes are present. The original deadline, fixed public error enum, and first-failure preservation remain intact. No tests or live calls were run during this read-only review.

Disposition: accepted, fixed; regression now supersedes only first observed identity and was red before fix. No rejection.
