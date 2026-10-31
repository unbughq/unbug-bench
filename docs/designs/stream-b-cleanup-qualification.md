# Stream B cleanup, cost and legacy deployment qualification

## Problem and scope

The requested increment is delayed cleanup and cumulative infrastructure cost
proof, plus fresh legacy ownership/deployment qualification.
Find out whether published provider rules establish a hard total infrastructure
spending limit and whether the old launch could have created a machine; if not,
list exactly what is missing.
Read docs/ENGINEERING.md and the preceding stream-b-delayed-creation,
stream-b-creation-intent and stream-b-deployment-inventory designs first.
Those reviews prohibit inventing a provider bound or speculative dormant
supervisor while the provider contract and legacy provenance remain unresolved.

This increment first qualifies those prerequisites using public provider
contracts and fresh read-only control-VM evidence. If either fails, the concrete
output is an evidence-backed refusal report, not guessed implementation or a
claim that the requested cleanup service is complete. No worker, paid model
call, VM mutation, source refresh, service restart, deployment or activation.
No secrets are read, printed or saved. The existing holder and diagnosis gates
remain false. No security or section 4 rule changes.

## Change

1. Run the existing deployment_inventory.inventory scanner on the actual VM
   roots /home/user/unbug-bench and /home/user/.unbug-control, using its reviewed
   source sent to python over pinned SSH stdin (in-memory compilation, no upload).
   Preserve its safe metadata-only output and the scanner source SHA256.
2. In the same read-only probe, inspect systemd active/enabled state for holder,
   resume service/timer and router; hash public installed unit files and policy
   bytes without printing policy values. For each scanner-listed launch, attempt
   a nonblocking exclusive flock only after all five named units were observed
   inactive, of its existing regular controller.lock opened
   O_RDONLY|O_NOFOLLOW without O_CREAT. Otherwise record skipped-units-active.
   Even this can collide with a manual launch; no manual or automated actor is
   fenced by this observation. Release immediately. Missing/failed/busy locks
   remain explicit unknown/live observations. This is an observation only, never
   a durable fence or proof of no provider work. Do not change complete/ids/markers.
   Project only the fixed launch enums/presence bits specified below. Record current source
   hashes through the scanner. Do not read secret files or arbitrary logs.
3. Query one bounded Boat list through the existing bin/boat-call list --json
   path as in preparation, using the VM credential implicitly; no credential file
   is read by the probe. Project only validated worker IDs and pageInfo.hasMore.
   Query CLI version, hash the fixed /home/user/.ascii/bin/boat executable and
   inspect its magic bytes. An ELF/Mach-O binary is opaque: no multiplicity claim.
   If readable source is found, review its request/retry code before claiming
   multiplicity; help/version alone never prove it. Capture errors as fixed labels/exit codes, never raw stderr.
   Empty inventory does not resolve a creation. No create/delete/resume/extend.
4. Collect the fixed legacy evidence below, then compare deployed public source
   hashes against all locally retained Git versions. Compute sha256 of git
   cat-file blob output for each path/commit from git rev-list --all -- <path>.
   Save matching blob/commit IDs locally in provenance.json. Check source ctime
   predates launch.json mtime, and launch-directory mtime/ctime are no later than
   the latest direct-child mtime/ctime (zero tolerance). Missing metadata fails.
   These are necessary consistency checks, not proof against a deletion followed
   by a later child write. A positive legacy verdict additionally requires a
   retained deployment/execution record binding that source to this launch and
   evidence of intact directory history. Git HEAD/reflog and staged manifest are
   collected as candidate provenance, never silently treated as that binding.
   Name each failed or unproved clause. Never synthesize a disposition. If cloud
   is absent, other, or BOAT_CMD is present, provider identity stays unresolved;
   a known hetzner selection makes Boat evidence inapplicable. No additional
   Hetzner provider query is made by the qualification probe.
5. Re-fetch exactly the nine official URLs listed in the two existing
   stream-b-{provider,cost}-contract-20261031/sources.json files, unauthenticated.
   Save new UTC fetch times/hashes and comparisons; retain changed pages verbatim,
   refer to unchanged existing files. No new URL unless the report identifies
   the unresolved question it answers. Required proof: bounded creation count,
   exceptional billable-seconds ceiling, selected rate, starts, storage/proxy/
   egress terms, and cumulative settled + holds + next <= USD 5. A TTL estimate,
   wallet observation or typical stop timing is insufficient.

If the evidence supplies all missing contracts, write a separate implementation
addendum and obtain a fresh design review before implementing the cleanup state
machine. Otherwise stop after the reviewed qualification report and suite;
identify the exact evidence needed from the parent/provider. Do not contact a
provider or send messages to others without authorization.

## Seams and deletions

B2 owns authenticated input/store qualification. B3 owns policy/release/manifest
pins; its deployment approval must consume this report's unresolved ownership
and cost findings. Neither a staged release nor B2 store success clears them.
Later admission/replacement work must consume a justified cumulative infra bound,
not the current per-launch --max-spend estimate. Carry-over stays with its owner.
This evidence increment deletes no code and replaces no launch path. It supersedes
stale VM observations with dated observations, without rewriting historical facts.

## Tests and acceptance

Check report JSON parsing, hashes and provenance against retained probe/source
bytes; ensure output contains only fixed metadata fields and validated IDs.
Retain the exact public probe used so results are reproducible. A source payload
is public code, not a credential. SSH uses the existing host key with strict
checking and existing identity path; key contents are never accessed by us.
No read-only observation is labelled atomic or activation authority.
Run uv run --with numpy --with scipy python -B tests/run.py to a unique log,
wait for completion and commit a result with command, timestamps, source tree,
exit code, script count and log SHA256. Fresh diff review checks report claims
against raw sanitized observations and public contracts. Save every review
verbatim and append disposition. Never self-verify a blocking fix.

## Murphy rows, cost and remaining work

No rows close unless real artifacts prove their full condition. In this evidence
increment none are expected: rows 6,27,28,29,35,49,51 and open batch-service rows
remain open. No new live failure is claimed. Read-only control activity uses the
existing VM; zero workers and model calls, with no claimed zero ongoing VM cost.
One local evidence/suite/review cycle. A provider response or historical execution
provenance may be an external blocker with no promised delivery date.

## Output contract (revision 2)

All evidence lives in docs/reports/stream-b-cleanup-qualification-20261031/:
probe.py (exact public Python payload sent over SSH, including the embedded
reviewed scanner source), observations.json, provenance.json, report.md,
contracts/sources.json and changed contracts/<original-basename>.md.
The scanner's current SHA256 is recorded; its code is not changed. Add
tests/factory/test_cleanup_qualification_evidence.py to validate the retained
real output, with mutation tests for extra keys, arbitrary enum strings and
malformed IDs/hashes. This proves output hygiene, not runtime qualification.

Connection: user@2.31.89.209, server 172111861 unbug-control, existing identity
~/.ssh/unbug-bench-hcloud and known-hosts
~/.cache/unbug-bench/hcloud/172111861.known_hosts. StrictHostKeyChecking=yes,
BatchMode=yes, ConnectTimeout=10. No alias is needed. Run python3 -B - via SSH
stdin; no remote upload, __pycache__, shell tracing or raw error output. Subprocess
captures use temporary local-to-process files rather than pipes for commands
whose descendants might keep pipes open; raw output is never emitted. Command
bounds: 10 seconds systemctl/git/version, 30 seconds provider list plus the
existing boat-call cleanup allowance; 150-second overall SSH bound. Version
sets BOAT_NO_UPDATE=1. Failure labels are fixed, no exception repr or stderr.

Exact top-level observations keys:
- schema: integer 1; observed_at: timezone-aware UTC ISO8601;
  activation_authorized:false; snapshot_atomic:false.
- scanner: unmodified deployment_inventory schema-1 result. Its existing field
  types/enums/IDs are validated recursively against that scanner's output contract.
  scanner_sha256: lowercase 64 hex.
- units: exactly the five units named in review 1 (holder, resume timer/service,
  router, batch). Each has active in {inactive,active,failed,unknown} and enabled
  in {enabled,disabled,static,masked,not-found,unknown}. All other outputs map
  to unknown. unit_file_sha256 has the same five keys, each null or 64 hex,
  hashing only /etc/systemd/system/<unit> regular files.
- policy_sha256: null or 64 hex of /home/user/.unbug-control/policy.json;
  no policy data. staged_release_sha256: null or 64 hex of
  /home/user/.unbug-control/releases/practice-6ac450e/batch-release.json.
- locks: scanner-listed 32-lowercase-hex launch IDs mapped to
  free|busy|missing|error|skipped-units-active.
- legacy: {metadata,launch,git}. metadata has exactly the four source paths plus
  labels directory,launch.json,controller.lock for b275ffccd6134a33833853ad1d31ed16. Each value is null or
  {mtime_ns,ctime_ns,btime_ns}; timestamps nonnegative integers, btime_ns nullable
  if os.stat does not expose birthtime. Use lstat, reject unexpected file types.
  launch is {cloud,type,argv,environment_present,unknown_environment_keys}:
  cloud boat|hetzner|absent|other; type small|default|large|xlarge|absent|other;
  argv launch|other (launch only for a nonempty string list whose first element
  is a positive decimal worker count); environment_present has exactly all
  current control_resume.ENVIRONMENT labels except UNBUG_CLOUD/BOAT_TYPE, boolean
  values only. unknown_environment_keys is boolean, never key names or values.
  Invalid/unreadable launch JSON yields cloud/type/argv other and all presence
  bits false, plus read-failed. git is {head,reflog,exit_label}: head null or
  lowercase 40 hex; reflog up to 100 {commit,committed_at} entries parsed from
  git log -g -100 --format=%H%x09%cI (no subjects, selectors, names/emails);
  committed_at UTC-offset ISO8601. exit_label from fixed list below. No index read.
- fleet: {readable,page_complete,worker_ids,exit_label}. First two booleans;
  worker_ids unique sorted strings matching [A-Za-z0-9_-]+. Only validated full
  response shape produces readable true; page_complete is hasMore is false.
  Failure emits false,false,[] and a fixed label. No raw sandbox records.
- cli: {version,sha256,format,exit_label}. version null or numeric x.y.z only;
  sha256 null or 64 hex; format elf|macho|source|other|missing; source means
  script text header only, not reviewed multiplicity. Fixed executable above.
- errors: unique sorted labels from read-failed,command-failed,timeout,
  malformed-output,unsupported-file,units-not-inactive. Command exit_label uses
  ok|command-failed|timeout|malformed-output|read-failed.

provenance.json is a local analysis, not probe authority: source paths map to
{observed_sha256,matches:[{commit,blob}],ctime_before_launch}; hashes null when
missing, commits/blobs 40 hex; ctime_before_launch boolean or null. Also record
{directory_timestamp_consistent:boolean|null,execution_binding:false|true,
intact_history:false|true,cloud_known:false|true,verdict:unresolved|satisfied}.
True execution_binding/intact_history require exact cited retained records in
report.md. No inference from timestamp consistency alone.

contracts/sources.json is a list of exactly nine {url,old_file,old_sha256,
new_sha256,fetched_at,status,file} records: status unchanged|changed|unavailable,
new_sha256 and file nullable on failure. URLs exactly the prior lists. file is
old_file for unchanged or this increment's contracts/<basename>.md for changed.

report.md has one row each for creation-count, exceptional-billable-seconds,
type-rate, start-charge, storage-charge, proxy-charge, egress-charge,
cumulative-ledger, legacy-provenance, deployment-readiness. Verdict per row is
satisfied or unresolved, with evidence path/hash (URL for provider sources),
acceptance condition and exact missing evidence. Rate/fee rows can be satisfied
for their published narrow scope while the all-in bound stays unresolved.
Deployment-readiness is satisfied only when cost/ownership and B2/B3's exact
release/input qualifications all pass; this probe never grants activation.
