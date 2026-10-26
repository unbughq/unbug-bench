# Public runtime contract for the clean-room builder

This document describes infrastructure only. It contains no judge implementation,
reference protection, traffic schedule, case answer key or sealed-case information.
It may be shared with the clean-room builder without sharing other bench files.

## Questions

Inside the contestant container, run:

```sh
ASK_STEP=<current-step-name> ask-human "the question"
```

The command waits for an answer and fails explicitly if the responder is unavailable.
The owner service is a separate container; its private fact sheet is not mounted
into the contestant. Questions and configured time charges are logged independently.
Infrastructure tests used canned answers and a five-minute charge per question;
the final experiment's responder configuration determines the actual charge.

## Persistent work

The contestant's `/app` filesystem and services persist between steps. A detached
monitor can survive the agent CLI exiting and continue through a nonfinal separate
verifier. Start it in a new session, redirect all three standard streams, and record
its identity so a later session can check it and avoid duplicate processes.

Use `/app/unbug/` for persistent notes, monitor observations, actions and usage
records; that directory is declared as a per-step artifact in the practice runtime.
Keep the required guard and claims artifacts at the paths in the public task brief.

An artifact is a snapshot taken before that checkpoint's verifier. Work performed
during verification appears in the next snapshot. The environment stops at the
last step before its separate verifier, and at trial teardown. Persistence across
VM snapshots, reboots or infrastructure failure is not promised.

Every arm has this capability, including plain agents. Some failures arrive with
no announcement, change record, instruction or foreground agent call. Background
processes continue during those fixed windows. The latest claims remain in effect
until updated; use an atomic replacement when a watcher updates claims.json.
The host judge reads live state before a final silent step tears the environment
down. It observes at a constant cadence across ordinary steps too, so observation
starting does not announce a failure. These steps count in the primary totals and
are also reported separately, with observed unsafe and falsely protected seconds.

## Usage

Harbor records the foreground agent CLI's model usage. Background monitor calls
are not automatically included. Record timestamps, model/token/cost metadata,
CPU time and actions for any background work, including work during verification.
Retain enough information to distinguish process restarts and duplicate calls.

## Web access

Use the supplied HTTP/HTTPS proxy and trusted public audit certificate. Main tools
receive proxy and trust settings; the supplied Medusa build receives the public
certificate for npm. Arbitrary additional nested images/tools need their own trust
configuration. Keep TLS verification enabled. Direct internet egress is blocked.

Use shell or browser retrieval through that network. Hosted model-side search and
fetch cannot be observed by the local proxy and must be disabled in the agent
configuration. A custom agent wrapper must preserve that restriction.

Ordinary public web requests record sanitized URL paths. Model API/support TLS
remains opaque and records connection metadata only. Do not rely on audit logs as
memory or as proof that every possible source of information was observed.
