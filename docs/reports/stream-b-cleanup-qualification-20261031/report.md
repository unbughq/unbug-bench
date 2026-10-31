# Cleanup, cost and legacy deployment qualification

Verdict: **unresolved; deployment is not qualified**. This is a completed
read-only evidence increment, not a completed cleanup supervisor or cumulative
infrastructure ledger. Neither activation gate changed. No worker was created,
deleted, resumed or extended; no model call was made. Existing VM running costs
continue and are not claimed to be zero.

## Fresh VM evidence

Observed 2026-10-31T14:48:43Z on control server 172111861, unbug-control.
`observations.json` is the safe metadata output of the exact retained `probe.py`.
The probe executed over existing pinned SSH as user@2.31.89.209, python3 -B -,
using ~/.ssh/unbug-bench-hcloud and strict checking against
~/.cache/unbug-bench/hcloud/172111861.known_hosts. The payload embeds the unchanged
reviewed deployment_inventory scanner, with its SHA256 in observations.json.
No source, policy, unit, journal or ownership marker was changed. Transient
capture files and brief nonblocking locks were used as reviewed. No rollback
is needed; the probe installed nothing. Observations are not atomic.

All five queried units were inactive before locks were attempted. Holder and
resume service/timer were disabled. Router and batch unit files were absent.
All six observed controller locks were free at their individual observation.
A manual launch can race this probe; these facts are not a durable fence.
The complete Boat inventory was readable and empty. This neither proves
non-creation nor substitutes for deletion receipts.

The legacy launch b275ffccd6134a33833853ad1d31ed16 still has only launch.json
and controller.lock among all directory entries. Its cloud is explicitly boat,
type default, BOAT_CMD absent. Values of credential labels/paths and arbitrary
argv were not emitted. The other five launches have markerless creation
responses and complete/deleted/spend-finished markers. Those markers are not
requalified deletion or accounting evidence by this probe. Their unknown-entry
counts remain visible for subsequent history inspection.

All four deployed public source ctimes are later than b275's launch.json mtime:
the necessary historical-source ordering check fails. Directory timestamps
match the latest retained child's timestamps, which is consistent but cannot
prove intact history. Both read-only Git queries failed; no HEAD/reflog evidence
was obtained. This does not assert a reason (for example, absent Git checkout).
`provenance.json` records local Git-blob matching separately: guards/spend match the initial
4936347 commit, control_resume matches cfe4ad8, and launch.sh matches no retained
blob across the locally available branch history. No retained record
binds the executing source to b275 or proves an unpruned directory, so
execution_binding=false, intact_history=false and verdict=unresolved.
Do not write a completion marker, remove the directory or release ownership.

The legacy policy hash still equals fd0a861da1ef5f315ebf99345e410962437902004308539c9e02cd3d89beadf5.
The staged practice-6ac450e manifest hash is
0781679022b81b4c3beff3c0e0595fbe19128c568e22f5737da61b8e0cbfb1ab.
Neither establishes a current approved deployment. Installed CLI version is
1.0.87, an ELF executable with hash
663483ab622abcf10ff8d079785f96b33596f41e91484e4198e16ed8a1d94cda.
This differs from the previously discussed 1.0.85; neither binary's create
multiplicity is established by help/version or this hash. We did not attempt
binary reverse engineering or a creation probe.

## Per-question exams

All nine public documentation URLs were re-fetched unauthenticated and were
byte-identical to the retained pages. Exact fetch times, URLs and old/new hashes
are in contracts/sources.json. The rows below separate published narrow terms
from the all-in deployment proof.

| Question | Verdict | Acceptance condition, evidence and missing proof |
|---|---|---|
| creation-count | unresolved | At most the reserved number of starts per submitted intent, including CLI retries and lost replies. [create.md](https://docs.boat.dev/api/reference/sandboxes/create-sandbox.md) (`27a103e0832040be66c450adec636b1aec0935e79e36af5deda97cedf9f3e53d`) documents API idempotency, not the installed opaque CLI retry path. Need audited matching CLI source or a separately reviewed single-request API adapter. Never replay an expired key to query outcome. |
| exceptional-billable-seconds | unresolved | A maximum billed duration even when auto-stop/deletion fails or the control VM is unavailable. [auto-stop.md](https://docs.boat.dev/long-running-tasks/auto-stop.md) (`6ef4b66fd15cdfaa292c280ca6bceb97ba107ca45cf401621ff615c9ebaad157`) gives typical timing; [stop.md](https://docs.boat.dev/snapshots/stop.md) (`14fcf02297270dfc85f2acc91c29f293dde896ae46155728d55b1fff53ffb502`) does not establish a universal bound for the no-snapshot path. Need an explicit provider billing ceiling covering delayed/failed stop and no-snapshot deletion. |
| type-rate | satisfied | Published Boat default rate is USD 0.036/hour billed per second, also listed small 0.018, large 0.072, xlarge 0.20. [pricing.md](https://docs.boat.dev/pricing.md) (`b2203efdd360f109f516c728dd294730499c54b2e5a457d8346d241b7936b31b`). Scope: published rate only, not a lifetime bound or account charge proof. |
| start-charge | satisfied | Published maximum extra-start price is USD 0.07 per start. [limits.md](https://docs.boat.dev/limits.md) (`644a292de716fe566b69d4f8f881c5c18527d4a73d6bcfbff89a3d0e114d7a7b`). Scope: price per start only; creation multiplicity remains unresolved. |
| storage-charge | unresolved | [pricing.md](https://docs.boat.dev/pricing.md) (`b2203efdd360f109f516c728dd294730499c54b2e5a457d8346d241b7936b31b`) includes automatic snapshots; paid saved snapshots are distinct. Need runtime/configuration evidence the pinned workload creates no paid saved snapshots; current no-snapshots flag alone is not all workload behavior proof. |
| proxy-charge | unresolved | [ai-credentials.md](https://docs.boat.dev/ai-credentials.md) (`fc68551cbe3f30c2bad982d3e888f5d3dc6f457594cb3beb3a02f3b6b7943be1`) documents paid AI proxy behavior. Need runtime/account configuration evidence that this workload uses no paid Boat AI proxy, not merely --no-env or direct-model intent. No credential values should be collected. |
| egress-charge | satisfied | [pricing.md](https://docs.boat.dev/pricing.md) (`b2203efdd360f109f516c728dd294730499c54b2e5a457d8346d241b7936b31b`) explicitly includes network egress. Scope: Boat provider network egress, not other providers or future pricing. |
| cumulative-ledger | unresolved | Require settled conservative charges + unresolved full holds + next justified hold <= USD 5 across all successor workers. bin/boat-spend at base 839a096 checks a per-launch estimate and current reserved holds; finished holds leave that sum. No cumulative batch infrastructure ledger exists. [billing.md](https://docs.boat.dev/billing.md) (`ebfdf29702f22db170024067c8ee7a9aeea40ac100649374e0d2fd26b26aeb9b`) is not a per-batch cap. Need the reviewed hold formula first, then durable cumulative admission/settlement and crash tests. |
| legacy-provenance | unresolved | observations.json + provenance.json: source ctime-before-launch fails, execution binding and intact history absent. Need retained deployment/execution provenance predating b275 and intact directory history, or authoritative provider resolution of its creation. A free lock, empty list and matching current Git blob cannot resolve it. |
| deployment-readiness | unresolved | All cost/ownership rows plus B2 authenticated store/input proof and B3 reviewed exact policy/release pins must pass. Missing router/batch units and old staged release are observed facts, not permission to install. No activation or deployment took place. |

## Seams and next work

B2 can finish input/store evidence independently. B3 must carry unresolved legacy
ownership and the all-in infrastructure bound as explicit blockers in its
execution manifest. Later admission/replacement clamps must not treat a per-worker
USD 5 estimate as a cumulative cap. Carry-over remains the separate agent's work.

The next implementable cleanup design needs provider evidence for exceptional
billing and creation multiplicity, plus no-proxy/no-paid-snapshot qualification.
Only then choose the single existing launch path's intent schema, independent
cleanup supervisor and cumulative ledger. This increment adds no speculative
runtime machinery. Provider outreach needs separately authorized messaging;
none was sent. Historical source records may resolve legacy ownership locally,
but the observed current source timestamps do not.

No Murphy rows close. The requested cleanup/cumulative-cost implementation and
legacy disposition remain incomplete; this report identifies concrete external
and historical evidence gaps rather than claiming completion of those items.
No new live failure is claimed from a read-only observation.

## Validation

The retained-output test validates fixed keys/enums, public IDs, timestamps,
source hashes and the nine document hashes, and rejects injected extra fields
and malformed values. It proves report hygiene only. Full-suite and fresh diff
review records are retained alongside this report or in docs/reviews; neither
an offline suite nor a review replaces the missing live lifecycle proof.

## Evidence hashes

- probe.py: `4d2017d8b369978f12eb1f81d3a4eba17a2e6c30bdab1eeb98b8ee9faa9b67e2`.
- observations.json: `0c86a1967dfd02d996592e7a401cbb31acc3822a28ab54b1a17462bd94f898a1`.
- contracts/sources.json: `d792fa5a72c27a84c8dc864cfc902e25686404809288a4ca183020189e51dad0`.

Full suite completed at 2026-10-31T15:20:17Z: **162 scripts, 0 failed, exit 0**,
tested commit 97fedd1754840c153cce1bd75df522281933d33c. See
[the result record](full-suite-20261031T145151Z-0a6616ef.json) and its compressed
log for timestamps, tree/log hashes and reported skips. No source or test changed
during the run. Fresh diff review follows this committed suite record.
