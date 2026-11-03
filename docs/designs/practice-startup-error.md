# Practice startup error (offline repair)

## Problem and evidence
The single b75c9b4 worker failed before any router request. Retained encrypted
logs establish RuntimeError: exit 1 at run.py:3387 -> sh:161: the early
`docker compose up postgres redis` conflicts with an existing image container
`unbug-bench-postgres-1`. The sanitized real exception/location extract is
`tests/factory/fixtures/practice-startup-conflict-20261103.json`.
The public card has only the exception type and no continuation-budget ledger.
The full traceback and Docker message survived in encrypted logs; their public
location was not advertised. Missing accounting is a consequence of this crash
before model admission initializes a ledger. Keep the accounting refusal; do
not invent a zero ledger from an error card or relax collection validation.

## Change and deletion
Delete the eager Compose startup from run.main and its now-unused COMPOSE constant.
It runs before models and outside the existing bench preparation lock. G3 already
calls factory_pool.prepare(fresh=True), whose locked prepare_factory_main does
Compose down, setup and seeding. That is the existing owner of bench startup.
No new container-removal, retry or parallel launch path. Preserve that G3 path.
This removes the premature conflict; it does not claim arbitrary foreign Docker
containers can be safely reclaimed by the later bench owner.

For runner_error, write a structured `logs/runner-error.json` before sealing:
exception type, sanitized message and traceback filename/function/line locations.
Add its relative path to the public scorecard; keep arbitrary exception messages
out of the public card (they can contain case content). Replace the current raw
traceback log write with this retained structured record. Scrub known sensitive
environment values and string leaves of existing RAM secret files in memory,
plus bearer/key/URL credential patterns; never copy secret files into evidence.
Bound diagnostic reads and messages, reject linked secret files, and leave a
fixed diagnostic-unavailable label if diagnostic capture itself fails. Keep the
original stop/type and never replace it with a diagnostic error.

## Exams and scope
Use the retained real conflict message as the Docker edge response in the
existing full worker-command integration exam. Before the deletion it must stop
with runner_error and no router request; afterwards it must reach the existing
local TLS router/provider-preflight end state. This is replay of a real failure
at an authored provider edge, not qualification of a live Docker image.
Test the real runner exception handler with a failing startup command: retained
message/location survives sealing, sentinels from env/RAM/JSON are absent from
public and decrypted evidence, and the card points at that evidence. Exercise
existing G3 preparation tests to show its down/setup order remains the owner.
A local isolated Docker experiment with old Compose labels successfully recreated
containers; that does not reproduce the precise deleted worker metadata. Do not
claim it does. No more remote reads or workers are required.

Add new-practice-startup-1 for the premature startup conflict and
new-practice-startup-2 for undiscoverable error details; close only against the
real-error replay and retained-diagnostic tests, subject to the fresh reviewer.
Timeline: one offline increment. Provider cost: $0. Payoff: reach model admission
and retain actionable failure evidence. Risk: later G3 preparation may expose a
separate image problem; an early-start fix is not a pilot qualification.
Locked full suite, then fresh diff review (maximum two rounds). Practice remains
disabled; merge and repin precede any parent-approved retry.
