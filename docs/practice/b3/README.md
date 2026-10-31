# B3 practice execution handoff — LAUNCH BLOCKED

These are reviewed preparation constraints and pins, not an enabled live release.
The policy root deliberately makes `key_holder.policy_load` refuse it. Neither
`--dry-run` nor `HOLDER_ENABLED=False` prevents the legacy holder creating a paid
worker. Never install or serve this policy, or change its root to activate it.

The founder's B3 instruction approves $25 all-in for one plumbing case, concurrency
one, cheap capped routes and one separate cent-level Claude attribution call.
It also approves $100 for item 8 within existing Claude/Codex subscriptions and
existing OpenRouter credit, with no top-ups. This task executes neither approval.
`practice-bounds.json` records them; its fields are review constraints, not new
runtime enforcement. The conservative $0.01 probe reserve leaves at most $19.99
new case model money and $5 infrastructure. All list-equivalent usage, waste,
unknown reservations and probe usage count. An authenticated historical baseline
S must be added to the case commitment; it is never fresh spending authority.

## Executable offline preflight

From this checkout, exact commands (no provider calls):

```sh
ROOT=$(pwd -P)
RELEASE=$(python3 -c 'import json; print(json.load(open("docs/practice/b3/release-pins.json"))["release_directory"])')
docs/practice/b3/preflight.sh "$ROOT" "$RELEASE"
```

Expected exit is **3**, with `PREPARATION VALID — LAUNCH BLOCKED` and the blockers.
Exit 1 means invalid/stale data; 2 means usage error. It never returns 0 and must
not be chained into a launcher. It validates six file pins, the actual release
and trusted checkout closure, refusal of the committed policy, and a temporary
local policy copy changing only root and release directory. It performs the
scenario arithmetic checks. It neither accesses credentials nor calls the holder.

Release files are retained outside Git at the path in `release-pins.json`.
The pins name the clean build commit, not the later documentation commit.
Rebuild at that commit using `python3 -B factory/batch.py build --root` with the
absolute checkout root and `--release` with a fresh absolute destination. Use a
worktree of this repository so its real common-directory ciphertext inventory is
available. A missing inventory stops the build; never bypass qualification.
Compare every one of the six hashes. A/E trusted-code changes intentionally make
the current pins stale and require a new release and review.

## Held live execution manifest

This sequence specifies the ordinary interfaces and acceptance evidence. It is
not yet a runnable launch script: exact authenticated input, probe, fault injection,
pre-armed cleanup and activation commands depend on unfinished owners below.
No complete launch or serve command is provided for the unsafe preparation policy.

1. B resolves legacy launch `b275ffccd6134a33833853ad1d31ed16`, validates the real
   migrated inventory, and supplies lifecycle pricing/reservation evidence under
   $5, including storage, egress and delayed deletion. Empty inventory alone does
   not settle ownership or prove cost. B/E supply pre-armed VM cleanup covering
   uncertain creation, a measured deletion bound, and a maximum 60-minute lifetime
   measured from creation, not from when a post-create timer is armed.
2. B2 supplies an authenticated eligible generation, archive hash, owner, publication
   ACK, release binding, role slot and baseline S. The old a869de dry-run archive
   is not eligible. No renamed card, synthetic ACK or test fixture is acceptable.
3. A supplies and pins all selected exact route maxima/prices and feasible role
   profiles. `d7539d1d78d3e227450697e69bc3646c72ab648e` adds
   `claude/claude-opus-5-5:small` ($10) and `:medium` ($15); neither provides a
   cent-level probe or item-8's <=$5 target. Both retain $8.655360 worst-request
   holds; useful settled headroom is only $1.344639/$6.344639. Small token maxima
   are 50,000,000 input/500,000 output, medium 75,000,000/750,000; per-request
   context 1,000,000 and output 32,768. No profile fallback or saved-role rewrite.
   A must supply a separately enforced <=$0.01 probe and ordinary receipt path.
4. Replace the historical dry-run manifest with a freshly reviewed live manifest:
   case authority S+E (E <=19.99), separate probe <=0.01, one case, concurrency
   one, initial Claude account 2, allowlist [2,1] only after reviewed handoff.
   Account 1 requires genuine provider rate exhaustion, not occupancy or missing
   credentials. Select an absolute deadline and pin it; restarts never extend it.
   Enable only the reviewed practice holder release; diagnosis/replacement stay off.
   Rebuild/pin/install through the existing release process. Review exact final bytes.
5. On the control VM, read-only baseline commands from `/home/user/unbug-bench`:

   ```sh
   python3 -B bin/unbug status
   python3 -B factory/key_holder.py status
   bin/boat-call list --json
   ```

   Verify the final release with `factory/batch.py verify`: use `--root` equal to
   `/home/user/unbug-bench`, `--release` equal to its final immutable VM directory,
   and `--sha256` equal to its final reviewed digest. These pins do not exist yet.
6. After all prerequisites, the ordinary launch interface is `factory/key_holder.py`
   subcommand `launch`, with `--batch`/`--job` from the final policy and `--checkpoint`
   the authenticated B2 generation. Do not substitute an empty checkpoint. Retain
   operation and launch IDs, worker ID binding and schema2 money reservation.
   The separate probe must have its own correlated UTC/account-2 usage window,
   excluded builder traffic, invocation/lease IDs, final usage and settlement.
   Record only public attribution confirmation, never email, token or fingerprint.
7. Disconnect the Mac and restart the holder once while active (control VM root
   command: `systemctl restart unbug-key-holder.service`). B/E's independent cleanup
   must already be armed. Verify same operation/worker/reservation, no duplicate
   creation. Inject one transient publication failure only through a reviewed B
   injection interface, then verify replay generation, ACK, pointer and money agree.
   That injection command is missing and blocks live execution. Do not buy five
   retries or force account fallback. Natural fallback absent means unexercised.
8. Normal cleanup is collect-then-delete through the controller. Emergency provider
   interfaces, only for a worker positively matched to both reservation and launch:

   ```sh
   bin/boat-call delete "${WORKER_ID:?verified practice worker required}" --yes --json
   bin/boat-call deletion status "${DELETE_OPERATION_ID:?returned operation required}" --json
   bin/boat-call list --json
   ```

   Unknown responses require reconciliation, not blind repeats. Require matching
   targetId, kind sandbox, status/stage completed and timezone-aware completedAt,
   then complete inventory (`hasMore=false`) with exact ID absent. Install evidence
   through B's reviewed ownership path; do not fabricate retirement. Stop admissions
   on any uncertain creation/deletion. Preserve encrypted artifacts, public receipts,
   settled/retained money, restart trace and cost evidence. Disable practice admission
   through a newly reviewed disabled release; retain ownership and paid work.

## Item 8 draft

`item8-draft.json` pins the stream-d source hash and each scenario's acceptance
heading. Its null input/release fields are intentional blockers, not defaults.
Run order is 1,2,3,4,5,7,6. Alpha shares $40; all beta releases together share
$50, never $50 per release. Use alpha for 1–4, beta-fault for scenario 5's fault,
beta-fixed for its original/replacement and scenarios 7 then 6, beta-plumbing and
beta-science for scenario 6's original only. Finish scenario 6's replacement on
beta-fixed before carrying the original onward. Each release needs its own batch.

For each job record S, current settled total, pending reservations, remaining new
allocation and S+E commitment. Beta root/replacement splits are 7.50/7.50,
12.50/12.50 and 5/5. Carry both scenario 5 lineages without regrant; forbid r2 and
duplicate replacement admission via reviewed B controls, not invented JSON fields.
Exhausted ordinary authority stays exhausted. Only one scenario is admitted at a
time. Publish, settle or retain unknown holds, delete and verify before its successor.

20 creations maximum at $0.40 full lifecycle plus $2 shared costs are ceilings,
not verified prices. Global 8-hour deadline, 2-hour per-worker upper bound,
15-minute lifecycle overhead admission bound, and 70 total execution minutes
require B/E feasibility proof. Never shorten scientific caps to fit a window.
Missing outcomes, natural capped guards or live provider waits remain unproved;
never fabricate a verdict or spend more. Account attribution uses required calls
in scenarios 1/4; there is no extra item-8 probe. Beta diagnosis/replacement needs
its own reviewed isolated activation release after item 7; normal flags stay off.

## Remaining launch blockers

The authoritative list is repeated in both constraints and release pins:
B cleanup/cost proof, legacy ownership, inventory and handoff;
B2 authenticated inputs; A selected route maxima, probe and role feasibility;
E cancellation and bounded cleanup; D item7 joins; B admission/carry-over clamps;
live account identity/fallback evidence; final reviewed execution bindings.
No Murphy row closes, no service is deployed, and no model or infrastructure spend
is incurred by this preparation. Full suite and review records live under
`docs/reports/` and `docs/reviews/` with prefix `batch-practice-manifest`.
