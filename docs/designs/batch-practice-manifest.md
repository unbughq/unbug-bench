# B3 practice policy and manifests

## Problem
The old 6ac450e release is inert preparation, not a launch authorization.
B needs reviewable policy bytes, immutable release pins and exact operational
commands under two distinct founder approvals. Other streams have not supplied
all launch prerequisites. A script must not turn missing evidence into authority.
Base: f41ce5219dadd7f09c245ee03707c0de69158129, the newest local
factory-simplify when this already-created clean task branch was inspected.

## Change and scope
Create docs/practice/b3/ with practice-policy.json (holder schema),
practice-bounds.json (review contract, NOT a runtime policy extension),
item8-draft.json (explicitly non-loadable scenario planning data),
release-pins.json and README.md, plus executable preflight.sh.
Reuse factory/batches/b-practice-20261031.json unchanged as an inert dry-run
candidate. Build its release from a clean committed HEAD with factory/batch.py;
retain batch-release.json and all six release artifact hashes as release pins.
Policy binds that release, the existing manifest digest, exact checkout trusted
fingerprint and existing public recipient. It remains dry-run. Its root is /BLOCKED/b3-not-approved-for-launch, so
policy_load MUST refuse committed bytes. Flags stay false but are NOT safety
barriers: the legacy holder can create workers even with HOLDER_ENABLED false.
Do not install or serve it.
The executable preflight performs release and policy validation only, without
secrets, network, holder launch or money authorization. README lists exact
existing launch/status/deletion interfaces as held commands. A complete live
executable launch cannot honestly be supplied until B2 supplies authenticated
input and B/E supply cleanup. No invented CLI or evidence placeholder is executable.
Final launch release/policy needs a new review after those inputs arrive; these
pins are explicitly preparation pins, never advertised as launch-ready.

Practice bounds: $25 all-in = $20 models including a separate <=$0.01 Claude
attribution probe + $5 total infrastructure/storage/egress. Reserve $0.01 outside
the case; case incremental allocation is <=$19.99, and lifetime commitment must
include authenticated carried baseline S. The old inert $20 manifest is not the
live case policy and must be replaced after B2 determines S. One case, concurrency
one, no replacement/diagnosis, 60-minute creation-through-deletion maximum.
Probe is separately approved but NOT executable with a $10 minimum Claude lease:
A must provide an honest cent-level enforced invocation bound and receipt/settlement
path before it can run. Do not use small/medium to claim a cent-level cap.
Use existing subscription limits, no account purchases; account 2 first, account 1
only on router-proven account-2 rate exhaustion. Record public usage correlation,
never identity details or credentials. Cheap routes must satisfy role families and
honest maximum + spent + pending <= commitment. No saved role rewriting.

A's d7539d1 prerequisite supplies opt-in :small ($10) and :medium ($15),
not item-8's <=$5 target. Record that immutable source pin and exact maxima as
proposed dependency facts, not as available in this base. No merging A ourselves.

Item8 draft mirrors docs/designs/stream-d.md Item 8: $100 total, $90 incremental
model/list-equivalent/unknown reservations, $10 infrastructure; existing Claude/
Codex subscriptions only and OpenRouter existing credit only, no top-ups.
Seven scenarios, caps 10/10/5/15/15/25/10, worker slots 3/2/1/2/4/6/2,
execution minutes 10/10/5/10/15/15/5. Ordered 1,2,3,4,5,7,6. Alpha $40,
all beta releases together $50. Beta root/replacement halves 7.50/12.50/5;
S+E authority, no regrant on carry-over, one replacement maximum and no r2.
Five immutable release/batch pairs alpha,beta-fault,beta-fixed,beta-plumbing,
beta-science; absent pins and inputs are null and launch_ready=false.
Each scenario points to its exact acceptance text in stream-d rather than
inventing outputs or fault injectors. Up to 20 sequential throwaway creations,
verified deletion before successor, $0.40 full lifecycle each + $2 shared;
8-hour absolute deadline, 2-hour per-worker upper bound, 15-minute overhead
admission ceiling. Prices/timing are ceilings requiring B/E proof, not quotes.
No item8 probe: correlate already-required scenario 1/4 Claude work.

## Dependency ownership and acceptance
B (t3-ded79ec5): cleanup/cost evidence, legacy launch disposition, qualified
inventory, controller handoff, cumulative admission and cross-release carry-over.
B2 (t3/batch-auth-inputs): authenticated case IDs, archive/generation hashes,
owner/ACK, role binding, eligible release and baseline S; no fabricated import.
A: merge profile source, all selected route maxima (including free routes and
OpenAI for 4/6), <=$5 qualification feasibility and cent-level probe contract.
E: cancellation/unknown settlement, escaped pipes, bounded pre-armed cleanup
covering uncertain creation and measured timing. D item7 joins and qualification
activation release remain additional prerequisites. Human account attribution
and natural fallback round trip remain live acceptance, not preparation proof.

## Deletes, risks, rollout
No runtime paths added or removed; supersede use of old preparation pins in this
new handoff without rewriting historical evidence. No security property changes.
Risk is mistaking planning data for enforcement: separate filenames, explicit
blocked status, non-loadable policy and a preflight that only validates.
Rollback is no deployment; eventual rollback stops admissions, retains ownership
and receipts and uses a newly reviewed disabled release, never deletes evidence.

## Tests and review
Validate preparation release with batch.verify and a precisely translated local policy_load;
run preflight against real generated release, verify pins/digests and disabled
flags. Check draft arithmetic and all seven slot/cap allocations without provider
calls. No synthetic operational evidence or new runtime tests for static files.
Run full uv run --with numpy --with scipy python -B tests/run.py to a unique
external log, wait, commit its result/hash and log. Fresh design review before
implementation and fresh diff review after suite; fresh reviewer for blocker fixes.

## Murphy rows
No row closes. This work records dependencies for 9,39,49,51,
new-single-path-1, new-batch-service-4 and new-isolation-outer-wall-2.
Only real launch artifacts can close them. Offline preparation costs $0 and
creates no workers; reviewed manifests are the success criterion, not live success.

## Review-1 resolution and concrete artifact contract

Objective: give the operator a trustworthy record of what can be checked now and
what must arrive before spending money. This helps B assemble the eventual live
run without mistaking a planning ceiling for an enforced provider limit.
Timeline: one preparation implementation, full suite and fresh review; live timing
depends on the owners above. No runnable live launch is delivered prematurely.

Authority source is the B3 task instruction received from the founder via the
parent: "$25 all-in, one case, concurrency one, cheap capped routes, and one
separate cent-level Claude call to check account-2 attribution" and "$100 within
the existing Claude/Codex subscription limits. OpenRouter may only use credit
that is already there, with no top-ups." These supersede the older report's
no-extra-probe proposal and stream-d's pending-$100 wording only as to spend
approval. Preparation still authorizes no live calls. $0.01 is this design's
conservative probe ceiling, not a claim the founder specified that exact amount.
Policy review does not clear missing launch prerequisites.

JSON schemas (all schema=1, all USD quantities decimal strings):
- practice-bounds: launch_ready=false, authority (quoted source above), total_usd,
  model_usd, case_incremental_usd, probe_usd, infrastructure_usd, concurrency,
  cases, worker_lifetime_minutes, diagnosis=false, replacement=false,
  live_manifest_requirements (initial_accounts, claude_accounts, commitment formula),
  blockers (list of strings). These are review constraints, not runtime fields.
- item8-draft: launch_ready=false, source {path, sha256, heading}, total_usd,
  model_usd, infrastructure_usd, shared_infrastructure_usd, worker_slot_usd,
  max_workers, wall_minutes, worker_lifetime_minutes, overhead_minutes,
  funding, order, releases [{name, commit:null, sha256:null, batch:null}],
  scenarios [{number, model_usd, workers, execution_minutes, root_incremental_usd,
  replacement_incremental_usd, input:null, acceptance_heading}], blockers.
- release-pins: launch_ready=false, build_commit, release_directory (retained
  external absolute path), batch_release_sha256, files (all six sha256s),
  manifest_sha256, trusted_code_sha256, dependency_commits, blockers.

Committed policy copies all fields from the historical policy except root,
code_sha256, batch.release and batch.sha256. root is the sentinel above;
batch.release=/home/user/.unbug-control/releases/b3-<full-build-commit>;
code_sha256 is key_holder.fingerprint(checkout); release digest is generated.
path stays /usr/local/bin:/usr/bin:/bin. recipient is copied exactly from the
historical policy (age17aef2zj3vd3zj60gtaldwu4383z79wpp9dt2rgth3s7umk9thskqngw6xv).
It is NOT manifest.restore_recipient (age1ae6f86fkvfnlv525ne9n4rj49texw9r9sh5h5udj23da0ptnnuksuxm6ch).
A temporary local validation copy changes ONLY root to checkout absolute path
and batch.release to supplied release directory. Compare the two objects after
normalizing exactly those keys, then policy_load the copy; never save or serve it
outside a temporary directory. Check committed policy_load refuses FIRST.

preflight.sh takes exactly two positional arguments: absolute checkout root and
absolute release directory. It locates committed data relative to its own path.
It invokes an adjacent preflight.py using python3 -B (stdlib and existing factory
modules only), no shell eval and no source of environment files. Ordered checks:
1. JSON schema/false launch flags and null item8 release/input pins;
2. six release hashes and batch.verify with root (stale pins return error);
3. manifest hash, trusted fingerprint, disabled flags, dry-run, no replacement;
4. committed policy refusal, then two-field translation and policy_load;
5. exact cap/slot/time totals and root/replacement allocations.
Successful validation prints PREPARATION VALID — LAUNCH BLOCKED plus blockers
and expected differences: old $20 case vs future S+$19.99, [2] vs future [2,1].
It exits 3 even when valid; error exits 1, usage exits 2. It never exits 0 or
calls launch, authorization, secrets, network or provider APIs. Checks live here,
not in a new test harness. README's held launch step lists interface/arguments
as prose, never a paste-ready complete launch/serve line. Exact read-only status
and positively identified worker deletion interfaces may be documented, never
executed by preflight. Missing authenticated generation and cleanup commands are
explicit launch blockers, not shell placeholders that could accidentally run.

Commit design/review and implementation first; build at that clean commit into
/tmp/unbug-b3-release-<full-build-commit> and retain the six files. Generate and
commit pins/policy afterwards (docs only, outside release source closure). Reviewer
can rebuild at build_commit in a clean checkout and compare all six hashes.
Record build_commit from git, never fabricate it. Later A/E trusted-code changes
make verify(root) fail as pins stale and require a new reviewed release.
Live replacement manifest must use claude_accounts=[2,1], initial_accounts.claude=2
only after reviewed A/handoff integration and set commitment=S+E with E<=19.99.
The inert historical manifest is explicitly not that final manifest.

Preflight resolves both arguments and requires the checkout to equal its own repo
and the imported factory module root; imports come only from that checkout's
factory directory. Translate root using the resolved absolute path. Builds and
review rebuilds use a worktree of this repository with its real common-directory
ciphertext inventory. Missing inventory is a hard stop; never fake or bypass it.
The six pins are batch-release.json, install-source.py, source-manifest.json,
public-source.tar.gz, worker-release-manifest.json and deploy.py. Early hash checks
intentionally duplicate existing verification for specific stale-pin diagnostics;
reuse batch.verify and policy_load rather than duplicating manifest semantics.
