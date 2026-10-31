**Verdict: FAIL. Two blockers are open.**

Scope: read-only goldfish design review of `docs/designs/stream-b-cleanup-qualification.md` (uncommitted, worktree base 839a096). I used the `zoom_out`, `design_critic` and `implementation_readiness` personas, with the Heilmeier and implementation-readiness standards. I ran nothing on the VM and made no network calls.

## Is the evidence-first refusal scope justified?

Yes. The earlier designs left these contract items open, and the retained provider pages do not answer them:
- **Billing during failed stops:** how long a worker can keep billing when its stop fails or is delayed. `stop.md` gives a forced stop after three days of failed saves. That is not a hard billing bound, and it covers different stop mechanics.
- **CLI multiplicity:** whether CLI 1.0.85 can create more than one worker in one call, or whether a reviewed single-request API adapter is needed instead.
- **Proxy and snapshot charges:** runtime proof that the workload uses no paid snapshots and no AI-proxy charges.
- **Cumulative ledger:** there is still no ledger for settled + holds + next ≤ USD 5. The existing `--max-spend` check is per launch.

Sources: `stream-b-creation-intent.md` lines 241–274, `stream-b-delayed-creation.md` lines 69–94, and the retained `stream-b-cost-contract-20261031/` pages. Reviews delayed-creation-design-1/2 and creation-intent-design-* forbid inventing a bound or building a dormant supervisor while these stay open.

So refusing to build the cleanup state machine without that proof is correct and proportionate. The two blockers below are about the qualification half: as written, it cannot be run without the implementer making design decisions, and its legacy result is fixed in advance.

## Blockers

### B1. The output contract is undefined, so "only fixed metadata fields" cannot be tested
- **Scope:** Change items 1–5; "Tests and acceptance".
- **Finding:** The design never names the probe file, the observation file, the report file or the `sources.json` location. It never gives the fixed field list or the pass/fail rule for each contract question. The test "ensure output contains only fixed metadata fields and validated IDs" needs that field list. Without it, the implementer chooses the schema, which breaks the zero-decision rule.
- **Exact fix:** Add an "Output contract" section, like the one in `stream-b-deployment-inventory.md`:
  1. **Paths.** For example:
     - `docs/reports/stream-b-cleanup-qualification-20261031/probe.py` (the exact bytes sent over SSH);
     - `observations.json`;
     - `contracts/sources.json`;
     - `report.md`.
  2. **Top-level keys of `observations.json`, each with its allowed values:**
     - `scanner` (the scanner's schema-1 output verbatim, plus `scanner_sha256`);
     - `units` (`active` and `enabled` for `unbug-key-holder.service`, `unbug-resume-launches.timer`, `unbug-resume-launches.service`, `unbug-model-router.service`, `unbug-batch.service`);
     - `unit_file_sha256`;
     - `policy_sha256` (name the policy path);
     - `locks` (per launch: `free`, `busy`, `missing`, `error` or `skipped-units-active`);
     - `legacy` (see B2);
     - `fleet` (`readable`, `page_complete`, `worker_ids` matching the validated regex, `exit_label`);
     - `cli` (`version` string, `exit_label`);
     - `observed_at`;
     - `activation_authorized: false`;
     - `snapshot_atomic: false`.
  3. **A closed list of error labels.**
  4. **A per-question verdict table in `report.md`.** One row for each required proof in item 5: creation count, billable seconds including exceptional stops, type rate, starts, storage/proxy/egress, cumulative settlement across successors, plus legacy provenance. Each row records `satisfied` or `unresolved`, cites a source URL and hash, and names the exact evidence still needed.
  5. **A test** that parses `observations.json` and rejects any key or value outside the contract. Run it against the retained real output.

### B2. The legacy qualification has no concrete evidence-gathering step, so "unresolved" is guaranteed
- **Scope:** Change item 4; item 2 (`launch.json` hash).
- **Finding:** Item 4 says b275 "needs evidence of the executed launcher and preserved directory history". No step collects that evidence or says what would count. delayed-creation-design-1 (B2, lines 78 and 151) already named the residual checks: the deployed release's commit, and b275's mtime not being older than that deployment. Some of that evidence can be read safely and is not collected:
  - The repo starts at 4936347 (2026-10-26). Every version in history writes `launch.json` before exec, `ids` before creation, and `new.N` before the provider call. So the provenance question becomes: was the launcher that ran when b275 was created a repo version, unchanged since before b275 was created?
  - The scanner reports only hashes for source files and no directory timestamps. The timestamps needed for this check are therefore missing.
  - The design hashes `launch.json` but has nothing to compare the hash against, so it proves nothing. Meanwhile `UNBUG_CLOUD` is never observed. Hetzner is the default cloud (`creation-intent.md` line 268). If b275 was a Hetzner launch, the Boat list in item 3 and the Boat cost contracts do not apply to it.
- **Exact fix:** Replace item 4 with a fixed evidence set and decision rule:
  1. **Collect in the same probe.** Use `lstat` or `statx`; do not change the scanner.
     - Collect `mtime_ns`, `ctime_ns` and `btime` (where available) for:
       - the four deployed sources the scanner hashes;
       - the b275 directory;
       - b275's `launch.json` and `controller.lock`.
     - If `/home/user/unbug-bench` is a git checkout, read only `git -C … rev-parse HEAD` and `git -C … log -g --date=iso --format=…`. Never run `status`, `fetch` or anything that refreshes the index.
     - Read the staged-release manifest hash (practice-6ac450e, per the preflight).
  2. **Replace the `launch.json` hash with allowlisted enum fields.**
     - `UNBUG_CLOUD` must be one of {`boat`, `hetzner`}.
     - `BOAT_TYPE` must be one of {`small`, `default`, `large`, `xlarge`, absent}.
     - The argv shape is a fixed label (`launch`, or `other`).
     - Every other `ENVIRONMENT` key is reported only as a present/absent boolean.
     - Any value outside the allowlist becomes `other`. No raw strings are emitted.
  3. **Decision rule.** `provenance-qualified` holds only if all of these are true. Otherwise the result is `unresolved`, with the failing clause named.
     - (a) Each deployed source's sha256 equals a blob in `git rev-list --all -- <path>`. Compute this locally as sha256 of `git cat-file blob`.
     - (b) Each source's `ctime` is earlier than b275's `launch.json` mtime.
     - (c) The b275 directory's mtime and ctime are no later than the latest child timestamp plus a stated tolerance, so no entry was removed or replaced afterwards.
     - (d) The cloud value is known. If it is `hetzner`, say that the Boat evidence does not apply, and run no Hetzner provider call without separate authorization.
  4. **State the limit.** `provenance-qualified` assumes a trusted, quiesced filesystem, the same assumption the scanner makes. It is a report finding, not a disposition: no record is written.

## Major findings

- **M1. The controller-lock probe can disrupt a live controller** (item 2).
  - **Finding:**
    - `control_resume.py:51-53` takes the lock with `LOCK_EX|LOCK_NB` and exits with "launch already owned" if it is busy. A probe holding the lock at that moment makes a concurrent resume or launch fail. `batch_holder.record_child` counts such failures.
    - The reviewed scanner design also says the scan "never acquires controller locks", and item 2 itself says the lock result proves nothing.
    - The last known state was the timer and holder disabled (preflight `units_after`), but parallel streams use the same VM.
  - **Fix:** Try the lock only when the same probe has already seen all five units inactive. Otherwise record `skipped-units-active`. Use `O_RDONLY|O_NOFOLLOW` and say this in the design. State the remaining risk of colliding with a manual operator.
- **M2. CLI help text cannot answer the multiplicity question** (item 3).
  - **Fix:** If the pinned CLI 1.0.85 ships as inspectable package code (for example JS), hash its files and read its create-request path read-only for retry logic. Record the file, hash and line references. If it is opaque, record the multiplicity row as `unresolved`, with the exact question for the provider.
- **M3. Heilmeier gaps.**
  - There is no objective free of jargon. Add one sentence, for example: "Find out whether the provider's published rules let us prove a hard total infrastructure spending limit, and whether the old launch b275 could have created a machine; if not, list exactly what is missing."
  - There is no stated exam per question. B1's verdict table fixes that.
  - Name the SSH host alias and identity path used by the earlier probes.
- **M4. The contract re-check (item 5) is open-ended.**
  - **Fix:** Re-fetch exactly the 9 URLs in the two retained `sources.json` files and compare sha256. Save changed pages verbatim with new UTC fetch time and hash. Fetch new pages only when an unresolved row names them. Make no authenticated or paid requests.

## Nits

- **N1.** Item 3 should reuse the fleet-list method from the `stream-b-preparation-preflight-20261031.json` probe, rather than a new invocation. It should also state that the list uses the VM's existing provider credential implicitly, with nothing read or printed by us.
- **N2.** The sentence "Base is 839a096, which merges the newest local factory-simplify into the assigned branch" belongs in the review record, not the problem statement.

## What already passes

- Seams with B2 and B3.
- No deletions and no new launch path.
- The Murphy rows stay open, which is correct for an evidence increment.
- The cost and timeline statements.
- The suite and review records.
- The bans on writes, workers and secrets.

Once B1 and B2 are fixed, run a fresh design review before the probe runs on the VM.

## Elephant response

B1 and B2 accepted: added exact output paths/schema, a retained-output validator,
fixed provenance metadata and decision rules. M1–M4 addressed in revision 2.
Timestamp conditions are necessary consistency checks, not sufficient proof of
unpruned history; a positive finding additionally needs retained execution/deployment
provenance. This conservative strengthening is submitted to a fresh reviewer.
No probe ran against the VM before re-review. Base merge: 839a096.
