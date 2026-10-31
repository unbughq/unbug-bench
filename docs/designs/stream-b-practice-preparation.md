# Stream B practice preparation, 2026-10-31

## Problem

Prepare the founder-approved USD 25 practice without launching or paying for
models. The source release is factory-simplify 7c6baa6, including the reviewed
holder activation changes. Stream A account-2 routing must land before launch.

## Change

Pin a one-job, concurrency-one, USD 20 model manifest with a one-hour worker
TTL, USD 5 launcher spend ceiling, replacement disabled and account 2 only.
The seven-day admission deadline is a stale-plan refusal boundary, not a worker
TTL or permission to run for seven days. Keep both code gates false.
The manifest uses --dry-run so a mistaken fresh invocation cannot make a real
case. This is a preparation candidate, NOT the account-path acceptance run:
that run requires a verified authenticated practice checkpoint and repinning
after A. Do not remove --dry-run to bypass the missing checkpoint.

Save public VM evidence and a release-bound policy candidate. Do not activate
or overwrite the live legacy controller while its unresolved launch remains.
No new launcher, import exception, accounting history or synthetic authentication.

## Deletes

Replace the prior report's proposed-spend wording with the founder's actual
approval and explicit preparation-only restriction. No production code changes.

## Tests and review

Validate manifest schema, release hashes, policy binding and disabled gates.
Run the ENGINEERING full suite. A fresh goldfish review is still required for
this new manifest/policy. As the assigned implementation sub-agent, this agent
must not delegate: return the concrete files and findings to the parent for
that review. Existing activation reviews do not approve these new files.

## Murphy rows

No closures. Rows 6, 27, 28, 35 and 51 still need real live evidence. No new
runtime failure was observed: this was a read-only readiness inspection.
