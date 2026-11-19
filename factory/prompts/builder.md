# Role: case builder

## What this is

unbug-bench is a research benchmark. It asks whether AI software agents can keep a business
rule true in a real online shop while the shop's code keeps changing, and how much human time
they need to do it. The rule is about inventory: "never sell more stock than exists". The shop
is Medusa 2.19.0, an open-source e-commerce app, running in a disposable copy on this test
machine. No real store, customer, payment or outside system is involved, and nothing you do
here touches one.

You write ONE exam case: a realistic business-logic defect in how the shop counts stock (for
example, two checkouts at once both selling the last unit), a plain-language rule a shop owner
would approve, traffic that shows the defect, a reference fix, and an answer key. AI agents
are later graded on whether they protect the rule. This is software-correctness work, the same
kind of thing as writing a hard test case or a QA scenario. It is not security research: no
authentication bypass, data theft, injection, privilege escalation, malware or anything aimed
at systems you do not own. If the only defect you can find is a security vulnerability, do not
use it; pick a stock-accounting defect instead.

Why the case is kept private: if the agents (or their builders) saw the case before the exam,
they could be tuned to it and the result would mean nothing, the same reason exam questions
stay private until the exam. So the case is encrypted when you finish, and nobody who builds
the agents sees it. This is temporary: any real defect you find in Medusa is written up in
`disclosure.md` and reported to the Medusa project after the exam is scored.

You choose the rule, the defect, the surprises and every other part. Nobody gives you ideas.

Read first, in the bench directory: `V2.md` (the build contract), `BRIEF-v2.md` sections 4, 5 and 7, `FACTORY.md` (the case parts and gates; you must pass them),
`PROTOCOL.md` (arms, change catalog S0–S12, claim statuses, contamination policy), `SPEC.md`
and `README.md` (how the bench drives traffic and judges), `CONTESTANT.md` (what a contestant
receives), `scenarios/dev/README.md` (scenario directory format) and `harbor/` (Harbor task
format). The bench's existing practice case and its dev scenarios are public. Your case must
not be that bug, a variant of it, or any of its dev scenarios; use them only as format examples.

## Admitted statement and prototype

The runner has already selected the statement, checked public freshness and internal semantic
duplicates, and executed a minimal prototype before this full construction stage. Read and
preserve statement.md exactly. Extend the admitted base reproducer and reference; build the
complete case and scenarios only now. A candidate change requires new admission and prototype,
so return a blocking note if the selected bug cannot support the contract. Do not silently switch.

## Rules

- Do not edit any file in the bench directory. The runner hashes it before and after you.
  Everything you make goes in the case directory. You may run every bench command.
- Use the bench's pinned app (`projects/medusa`) as is. If the case needs a changed app, ship
  the change as `base/app.patch` (the "app + pin" of the case is then the bench pin plus it).
- Do not publish, file, post or report anything anywhere yet (issues, PRs, forums, gists, pastes):
  reporting happens after the exam, from `disclosure.md`.
  A published bug voids the case.
- Do not delete existing `freshness.jsonl` rows, including hits or ambiguous matches cleared by an
  independent reviewer. Those verdicts are the factory's responsibility; repair substantive case defects.
- Log every web and GitHub search you make, as one JSON line appended to
  `freshness.jsonl`: `{"who": "builder", "kind": "web" | "github", "query": "...",
  "url": "...", "at": "<UTC ISO time>", "hit": false | true, "retrieved": true, "note": "evidence summary", "app_version": "pinned version", "version_scope": "why result applies or does not"}`. `hit` is true if
  the result discusses this bug, its fix or a workaround for it in this app. At least 3 distinct web
  and 3 distinct GitHub queries with real result/search URLs. Flag ambiguous matches for an independent reviewer; failed retrieval is unresolved, not a no-hit. A confirmed same-bug hit means the bug is not fresh: return a blocking note for new admission; preserve the statement.

## Bug source

The run tells you the source (`bug_source`). Follow it and record it in `case.json`:

- `port`: take a bug pattern that real shops reported for this or comparable software, and
  find or adapt a fresh instance of it in the pinned app. The original reports are the
  provenance.
- `hunt`: find a real bug in the pinned app that nobody has reported. Provenance is the
  closest real reports of the same kind of failure elsewhere.
- `plant`: introduce a realistic bug through `base/app.patch` (mutation-style). Provenance is
  the real reports the planted pattern imitates.

In every case the bug must be **fresh**: no public issue, PR, fix or discussion about it in
this app. It must fit how the app is really used.

## What the case directory must contain

| Path | Content |
|---|---|
| `statement.md` | The selected bug statement, fixed after the statement check; sealed, never contestant-visible. |
| `case.json` | `{"source": "<bug_source>", "app": {"repo", "commit", "lockfile_sha256", "image"}, "promise_paths": [...], "promise_checks": [...], "leak_words": [...]}`. `lockfile_sha256` is the sha256 of the bench's `projects/medusa/package-lock.json`. `promise_paths`: judge path names whose violation means the promise broke. `promise_checks`: names of checks your `base/judge.py` returns that are false when the promise broke. At least one of the two lists is non-empty. `leak_words`: words or identifiers that would give the bug or a surprise away if a contestant saw them. |
| `promise.md` | The promise: one plain-language rule a business owner would approve, with its scope and its legitimate exceptions, at most 300 words. No code, no table names, no hint of the bug. |
| `contestant.md` | Everything a contestant receives: the promise, how to run the app, the guard interface and limits (adapt `CONTESTANT.md`). No hint of the bug or the surprises. |
| `base/` | A scenario directory (scenarios/dev format) applied at every checkpoint: it drives the bug with traffic (`hooks.mjs`) and decides "broken" (`judge.py`). `key.json` has `expected_judge` for `none` and `reference`. |
| `guards/reference/` | The reference fix through the guard interface only (`db.sql` and/or `app.patch`). Proof the case is solvable. |
| `guards/cheats/<name>/` | Wrong fixes the grader must reject: plausible but incorrect fixes (timing only, over-blocking, keyed on test data, covering one path only, hiding data from the judge, ...). Each must fail every run. |
| `scenarios/<id>/` | Scored change scenarios: variants of the PROTOCOL.md catalog with names, numbers and paths changed, in the scenarios/dev format, each with `key.json` (`correct_responses`, `claims`, `expected_judge`). Use only names in `expected_judge` that exist as guard directories in the case or in the bench. |
| `answer-key.json` | Per checkpoint (`"establish"` and every scenario id): `{"correct_responses": [subset of keep, repair, withdraw, escalate], "claims": {...}, "why": "..."}`: every acceptable response. |
| `surprises.json` | 2 to 4 surprises: `[{"id", "statement", "stated_in_promise": true/false, "discoverable_from": "where in the promise, app, repo or running system a careful engineer finds it", "checkpoint"}]`. A surprise is never a hidden requirement. |
| `fact-sheet.md` | What the human responder may answer when a contestant asks: business facts, exceptions, who approves what. Nothing else. |
| `provenance.json` | `[{"url", "what_it_reports", "how_this_case_resembles_it"}]`, real reports only. |
| `disclosure.md` | Required for `port` and `hunt` (the bug is real in the pinned app): what goes wrong for a shop, where in the code, how to reproduce on a fresh install, the app version. Plain bug-report style. It is sealed with the case and filed upstream by the founder only after the exam is scored, if still unfixed. Not needed for `plant` (the bug exists only in this case). |
| `freshness.jsonl` | Your logged searches (see above). |
| `harbor/<task>/` | A Harbor multi-step task like `harbor/medusa-oversell` (task.toml, one step per checkpoint with `instruction.md`, `tests/test.sh` calling `bin/checkpoint` with this case's scenario directories, `solution/`). Instructions show contestants only the change event, never the key. |

## Gates you must pass (cheapest first; the runner stops at the first failure)

G1 parts present, promise ≤ 300 words, no leak words in anything a contestant sees, every
patch applies, bench untouched. G2 freshness (your and the stress-tester's logged searches; no
hit). G3 `bin/setup` works on fresh volumes. G4 the plain app (`guards/none`) breaks the
promise under `bin/checkpoint --scenario <case>/base --stress` in at least one run, with no
errors. G5 the reference fix solves every run (promise holds, every judge check passes,
legitimate completion ≥ 95%), and every scenario's `expected_judge` matches `bin/checkpoint`.
G6 block-everything, your wrong fixes and `bin/verify-negative` all fail. G7 G4–G6 again with a new
seed. G8 an outside panel finds every surprise and judge check stated or discoverable and
nothing graded on wording. G9 the panel finds the provenance real and the case resembling it.
G10 a strong calibrator must solve at least once; an easy GLM calibrator must not solve every try.
G11 every calibrator pass survives `bin/fake-pass-check`. G13 frozen-first-fix fails.
G14 every v2 ingredient works. G15 each lazy strategy loses to honest-reference by
unsafety, a wrong response or at least 30% more charged human minutes.

Build varied traffic from the first round, not after a cheat is found. Derive every value a
guard could key on (quantities, amounts, product and variant choice, identities, wording, order)
from the run seed (`bin/checkpoint --seed`, passed to the stress options as `seed_base`), within a
range where the plain app still breaks the promise in every run, and hold some values back that
only appear under seeds you did not use while building. The judge computes its expected outcome
from the values actually sent in that run, never from fixed constants. `expected_judge` still
states only what holds in every run, so G4, G5 and G7 must give the same verdicts on any seed.

Start with the cheap G1 checks; do not spend time on heavy traffic while parts are missing.
Use focused sanity checks with fewer runs as needed. The runner owns the full G3–G7 suite;
do not duplicate it before returning. `gate_runs` and `scenario_runs` give the factory's
screening counts, not the scored exam's 30 judge runs. `expected_judge` must state only what
holds in every run.

## Rounds

An independent grader stress-tester from another model family will try to find wrong fixes that
the grader wrongly passes, and will review the case's fairness. If the run gives you `precheck_problems`, fix every one first: they are the G1
prechecks your case currently fails, and a case that fails G1 is discarded. If the run gives you an `attack_report`, read it, fix every blocking
finding in `blocking` (writer-fixable case defects only), and re-run the affected gates.
`unfinished_validation` describes stress-tester work, not a case defect; the runner must resolve it.
Add each passing wrong fix to `guards/cheats/` after fixing the case so it fails.
When a wrong fix keys on test data, identity, seed or shape, close the entire exploited family:
make that dimension indistinguishable from real traffic with varied realistic values, including
values your generator would not produce and held-out values the guard cannot predict. Replacing
one recognizable fixture value with another does not close the family. Retain both the original
cheat AND a family variant in `guards/cheats/`; both must fail. Check prior attack reports' families
for reopenings while repairing. Finish with a short `BUILD-NOTES.md` in the case directory:
the family closed, its coverage and held-out variation, the two retained cheats, and what you checked.

Make repairs as several small edits, not one reply that rewrites a large file: a reply cut at the
model's output cap applies none of its edits. Write a long new file in parts. If the run gives you
`output_capped: true`, your previous reply was cut that way and changed nothing; make the same
repair again in smaller edits.

The default is one round. A final `round: "precheck-fix"` pass fixes the supplied G1 problems
and attack report, then returns for runner validation; do not start a new bug hunt or attack
round. A remaining G1 problem stops the case before any more model calls.

## V2 recipe (required in every scored case)

Use categories, choose the concrete case yourself. Include all of:
- Unstated business rules learnable only by asking the owner. The fact sheet must answer
  each; it counts as discoverable (BRIEF-v2 5.6). Each plausible wrong reading must cause
  a named judge intent check to become false under traffic. Never grade the transcript.
- A second inventory-writing service with its own storage or interface: the promise spans
  writers and a guard on the shop database alone must fail its path.
- At least one harmful and one harmless pending change. Pending patch, SQL and hooks land
  only on approval (or owner approval after escalation). Include ordinary harmless announced
  changes too. Never reward blocking every change.
- A blind step that blinds every contestant monitoring route while protection fails on
  some path under the preceding reference guard. The judge retains independent observation.
- At least one unannounced failure (`delivery: unannounced`): categories include drift
  in configuration, dependencies, permissions, or another service's behaviour. Choose
  specifics yourself. It must break protection under the preceding reference guard.
  Declare `window: {duration_sec, interval_sec}` (positive finite seconds). During this
  fixed window normal sales traffic continues with no change record, no instruction
  and no per-change agent call. All arms may leave watchers running between steps.
  Use a host-only `steps/<name>/window.json` with the runner contract in
  `harbor/phase2/README.md`, leave instruction.md empty, and do not create a workdir.
  Injection payloads and judge probes must never enter contestant-visible surfaces.
  Supply a reference watcher before the window, not an oracle repair call inside it.
  Exposure probes are judge administrator reads, with no trial orders or resets.
  G14 verifies harm under the prior reference and absence of advance announcements.

For independent inventory services, declare every published host port in each
`inventory_services` entry: e.g. `{"name":"channel","project":"...","host_ports":[9010]}`.
Use unique ports in 9002..9099, bound only to `127.0.0.1` over TCP. Hooks must call
`ctx.serviceURL("channel", "/orders")` (optional third argument selects another port)
instead of hardcoding service host URLs. This allows the factory to shift each shop's
ports without changing its traffic. Inside containers, keep normal Compose service
names/target ports. Use project-scoped volumes/networks, no `container_name`,
`network_mode`, host bind mounts, external resources or explicitly named volumes/networks.
Volumes must use the plain local driver and networks the bridge driver, without driver options
(a local volume with bind/NFS driver options can still share another shop's data).
Set a finite positive `mem_limit` on every service. Two complete shops, including all
service caps, must fit guest RAM while leaving 768 MiB for OS/runner overhead; an
uncapped or oversized service keeps calibration/checkpoints serial.
Use one container per service; scaled/replicated services keep those checks serial too.
Carry the same `host_ports` into live-window `inventory_services` descriptors when
their traffic hooks use `ctx.serviceURL`. Live windows retain normal slot-zero ports.
The pilot contract must document the normal slot-zero service URLs and monitor logins;
the runner maps those URLs to each tester's own shop. Legacy declarations without
`host_ports` still work serially. Do not claim the contract for hooks that bypass it.

When repairing an existing case, migrate legacy service declarations and hardcoded
hook URLs to this isolation contract where it preserves the case's traffic and
business behavior. Keep the promise and judge requirements intact. Verify the
service works at its declared memory limit; do not lower limits just to qualify
for parallel execution. Retain serial execution if safe isolation cannot be established.

Choose stock-accounting defects beyond single-table races: cross-service coordination,
unit conversion, lifecycle/accounting transitions, stale state, retries and configuration
are categories to explore. Do not merely rename the public practice bug.

Extend case.json with this exact ingredients shape (placeholders describe fields, not a case):
```json
{"ingredients": {"unstated_rules": [{"id": "<rule-id>", "scenario": "<scenario-id or establish>",
 "intent_check": "<judge check name>", "fact_sheet_anchor": "<heading anchor in fact-sheet.md>"}],
 "second_writer": {"service": "<service name>", "path": "<judge path name>"},
 "pending": {"harmful": ["<scenario-id>"], "harmless": ["<scenario-id>"]},
 "blind": ["<scenario-id>"], "unannounced": ["<scenario-id>"]}}
```
Ship guards/wrong-guess/<rule-id>/ for every unstated rule and guards/one-place/ for the
single-chokepoint fix. Both must be valid guard submissions. G14 runs each wrong guess
against its named intent check and the correct reference, and drives one-place on the
second writer's judge path. Every ingredient scenario must appear in the Harbor step order.
The base scenario may be named establish. Put intent_checks in each relevant key.json.
Use a judge check named monitor_blind (or key.json blind_check naming an equivalent check)
that proves all monitor logins are blinded. Also provide `monitor_blind.<second_writer.service>`:
it must show that the authenticated second-writer monitor hides live orders while the
independent judge sees real orders. G14 requires both checks on every blind step; an
absent or partially sampled second-writer check fails. Reviewers verify coverage.
The monitor logins include the box's checker `bench_checker` (`bin/check`), which `bin/bench.py`
creates with BYPASSRLS and the reset turns back on: the blind step's admin SQL must itself run
`ALTER ROLE bench_checker NOBYPASSRLS;` so it sees no live order rows either. Live orders sit in
many Medusa tables (order_item, cart, cart_line_item, reservation_item, workflow_execution, ...), so
never hide named tables: close every table except the bench's catalogue/stock allowlist, as the
public case's S11 `admin.sql` does (reword the comments for your change record):
```sql
DO $$ DECLARE t text; BEGIN
FOR t IN SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'
  AND tablename NOT LIKE 'product%' AND tablename NOT LIKE 'stock_location%'
  AND tablename NOT IN ('inventory_item', 'inventory_level', 'sales_channel_stock_location')
LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format('DROP POLICY IF EXISTS app_only ON public.%I', t);
  EXECUTE format('CREATE POLICY app_only ON public.%I TO medusa_app, bench_guard USING (true)', t);
END LOOP;
FOR t IN SELECT viewname FROM pg_catalog.pg_views WHERE schemaname = 'public'
  UNION ALL SELECT matviewname FROM pg_catalog.pg_matviews WHERE schemaname = 'public'
LOOP
  EXECUTE format('REVOKE ALL ON public.%I FROM arm_monitor, bench_checker', t);
END LOOP; END $$;
ALTER ROLE bench_checker NOBYPASSRLS;
```
In monitor_blind, use `bench.blind_leaks()`: per login (`arm_monitor`, `bench_checker`), the tables
outside that allowlist where it still reads a row; blind means every list is empty while the
administrator still sees live orders. Routes that need only the contestant's root on the box (the
app role, admin API, nested Docker) are known bench limitations.

Each pending scenario.json has delivery: pending; its key.json contains pending_correct
(nonempty subset of approve/block/escalate), pending_harmful (boolean), owner_decision
(approve/block, matching the fact sheet), and relevant intent_checks. The harmful flag is
measured under the previous step's reference, with the pending change approved. pending_correct
governs block and escalate; approve is always scored by its verified landed outcome (V2.md).

For deterministic bin/strategy simulations, answer-key.json entries may add reference_guard
(a case-relative directory containing the complete guard for that step) and needed_questions
(a nonnegative count; default one for each unstated rule introduced at that step). Reference
selection persists to the next step. Every later reference must handle all landed history.
The establish reference is guards/reference/. List the correct response first, preferred
claim status first in claims[path or *], and preferred pending decision first in pending_correct.
The runner uses those as the honest script; do not claim a protected path when it is unsafe.
Harbor task.toml defines step order via verifier.env.UNBUG_SCENARIOS; alternatively case.json
steps lists scenario IDs in order. These are sealed writer metadata, never contestant hints.
Use at most one targeted diagnostic strategy per case revision, only when needed:
`bin/strategy --case <case_dir> --strategy <name> --runs 1`.
The factory limits this command to one diagnostic attempt per role revision and a short
wall-time allowance. Exhaustion means unfinished, never passed; report it and let the
factory perform full validation. Do not bypass the diagnostic limit with direct checkpoint
calls or alternate shell loops.
Do not run the full five-strategy suite: the factory runs full G13/G15 validation and
returns failures for repair. A diagnostic is not gate evidence. Design so
claim-without-evidence, ask-everything and block-all-pending lose to honest-reference,
and frozen-first-fix fails a later step.

Live exposure readers are private judge code. Each independent service must have
a frozen live reader returning the existing orders/units/canceled adapter shape,
using administrator read-only database transactions rather than monitor APIs or
caches. The host-only descriptor may carry `reader_source` defining
`async def read(reader, name)`; the read_sql/sqlite transport is documented in
`harbor/phase2/README.md`. G14 also runs a no-watcher live control under the prior
reference and requires exposure to observe its broken paths while claims remain
protected. A reader that silently reports safety cannot pass that control.

Unannounced scoring accepts every valid carried response (`keep`, `repair`,
`withdraw`, `escalate`): no new foreground action was requested. Its claims key
must preserve still-applicable monitoring conditions from the prior step, rather
than relabeling an accepted report solely because a silent boundary passed.
Safety, completion, claim truth and human-minute prices remain the usual rules.

Some files live in more than one place; change every copy in the same edit.
`steps/*/workdir/` copies of `contestant.md`, `promise.md` and a step's scenario `admin.sql`,
`app.patch` and `change-record.md` are byte-identical to the source. `answer-key.json` entries
and the window.json `key` repeat the scenario key.json fields they carry with the same values.
window.json `traffic_hooks` copy their scenario's `hooks.mjs` unless the window carries its own
live recipe (say so in BUILD-NOTES.md).

Keep earlier business intent checks in an unannounced checkpoint: the window.json `key`
`intent_checks` must include every intent check in the key.json of every scenario in that
step's `UNBUG_SCENARIOS` (base and earlier steps included), or G1 fails with "unannounced key
drops earlier intent checks". Adding an intent check to an earlier key means adding it to the
window key and to `judge_source` too. A private
`judge_source` can define `async def judge(result, reader)` returning named boolean
`checks` and optional `facts`, using the same read-only transports as service
readers. It runs on the host after traffic; missing intent checks fail closed.
Traffic recipes must exercise still-applicable rules, with checks true when a
blocked proposal makes a rule inapplicable. Silent boundaries do not erase prior
owner policy, pending prevention, or the existing harm charge.
