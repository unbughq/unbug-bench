# Real Harbor silent-window probe

Executed on the labeled Hetzner phase2 cx33 with Harbor 0.24.0, no model calls.
Use `python3 harbor/phase2/run.py run -p harbor/probes/unannounced-withdraw
-a oracle --job-name NAME -o /tmp/NAME` through `bin/hcloud-dev run`.
This minimal Python lifecycle probe uses the direct adapter: the audited webproxy
entrypoint expects start-dockerd, which this image does not contain. The full
Medusa practice run exercises the audited launcher separately.

Establish and observe each passed with reward 1. The silent step has no agent
execution or agent result. The solve script rejects a third call, and both
ordinary verifiers assert the exact cumulative call count. Calls: **2**.
PID **46**, UUID **4e6bf8db-2a2d-4024-af07-fc2474ba2b98** persisted unchanged
across all three artifact snapshots. The final snapshot has **229** heartbeats,
spanning **45.775 seconds**, maximum gap **0.204 seconds**; traffic reached 27.
No Harbor process-lifetime fix was needed.

The synthetic failure stays unsafe; its preinstalled watcher replaces claims
with unknown/escalate after two seconds. Over the fixed 8-second window,
observed unsafe time is **8.000 seconds**, unsafe while claiming protected is
**2.907 seconds**, unknown time **0**, at a 1-second interval. Expected quiet
reward is 0 (unsafe remains); judge_error is 0. This verifies exposure and
carry-forward claim updates, not a successful repair.

Machine evidence is in [verification.json](verification.json); raw pulled job:
`results/remote/phase2-claims-direct/`. An earlier independent persistent-process
probe is retained under `results/remote/phase2-lifecycle/`.
