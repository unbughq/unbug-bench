# Durable execution WP2: worker pool, release store and channel (control side)

Status: draft for design review. Package WP2 of `docs/designs/durable-execution.md`,
brief in `docs/designs/durable-execution-wave1.md`. Branch `de/wp2`, cut from
`durable-execution` at `db13be8`. Contract: `factory/durable/contract.py` v5 (not edited).

## Problem

The engine (WP1) needs three things from the worker side of the control VM, and today
they exist only inside `factory/launch.sh` and `bin/boat-launch-guards.sh`:

- a live worker for a case, with an exact factory release installed and verified
  (`launch.sh:685-707`: upload and checksum, unpack, CLI pins, Medusa image, worker
  release qualification, bench fingerprint);
- Boat creation and deletion that survive a lost response or a control-VM restart
  without a duplicate billable worker or a forgotten one (Murphy row 29);
- the control end of the frozen wire protocol: push input blobs, start an attempt,
  poll it, fetch its outputs, cancel it, with a transport failure always RUNNING.

Review 4 (N3) adds two gaps: the factory bundle is a tar.gz that cannot be rebuilt to
its digest, so something must keep each bundle by its sha256; and `plumbing_version`
and `bench_version` are not independent today, because the bundle's embedded manifest
hashes bench files.

## The change

Two modules, both control-VM only.

### `factory/durable/workers.py`

**Boat CLI wrapper (`BoatCli`).** Every provider call goes through `bin/boat-call`
(the pinned Boat with its version check and timeouts), exactly as launch.sh does, so
`BOAT_CMD` selects the transport in tests. `UNBUG_LAUNCH_STATE` is removed from the
child environment so the old launcher's command fence never applies to engine calls.
A call returns `(exit status, stdout bytes)`; it never raises on a provider failure.

**Release store (`ReleaseStore`).** A directory on the control VM:

- `bundles/<sha256>.tgz`: each factory bundle once, keyed by the sha256 of its bytes.
  Written to a temporary file, fsynced, then `link()`ed into place, so it is first-wins
  and a truncated write is never visible. Reading re-checks the digest.
- `benches/<bench_version>.json`: `{"image": "<Boat saved snapshot>"}`, which image a
  worker for that bench is created from. Without an entry, the pool's default image
  (`bench-env`, as launch.sh uses today) is used; the fingerprint check below still
  decides.

The release command fills it:

- `python3 -B factory/durable/workers.py release --root <tree> --store <dir>` builds a
  bundle from the tree and stores it, printing `plumbing_version`. The bundle is today's
  `launch_manifest.worker_upload` file set plus `factory/durable/*.py` (today's
  `WORKER_GLOBS` is not recursive, so `worker_step.py` would be missing), with the
  manifest stamped the way `worker_release.stamp` does plus the durable files. It is
  built deterministically (sorted members, mtime 0, uid/gid 0, gzip mtime 0), so a
  rebuild of the same tree gives the same digest, but nothing relies on that: the
  store is the source of the bytes.
- `python3 -B factory/durable/workers.py bench --store <dir> --bench-version <sha>
  --image <name>` registers a baked image for a bench release.

`put_bundle` refuses a bundle without `worker-release-manifest.json`, without
`WORKER_COMMAND`'s script, or whose factory members do not match the manifest hashes.

**Does a BENCH_RELEASE imply a new bundle? No.** The bench is the tree outside
`factory/` on the worker image (`run.bench_manifest()` excludes `factory/`), so a bench
release is a newly baked image plus a `benches/` entry. Any stored bundle may pair with
any registered bench. To make the pair independent, qualification uses only the
manifest's `factory/` entries; the bench is checked whole, by `run.bench_manifest()` on
the worker equalling `bench_version`. That is stronger than the embedded per-file
hashes of the stamp tree, which are kept in the bundle as evidence only. Gate code is in
`factory/`, so a gate fix is a plumbing release (contract docstring).

**Pool (`BoatPool`, implements `WorkerPool`).**

- *Labels.* Every worker is created with three labels: `unbug-durable/pool=<pool id>`,
  `unbug-durable/case=<case id>` and `unbug-durable/intent=<nonce>`.
- *Journal.* Per case, under the pool's state directory, one JSON record
  `{"intent": nonce, "worker": boat id or null}`, replaced atomically. The intent is
  written and fsynced before `boat new` runs, and the worker id after it answers.
- *`acquire(case_id, p, b)`* holds a per-case `flock` and is idempotent:
  1. The bundle `p` must be in the store (`infra:release_missing`).
  2. If the record names a worker that is live in a complete inventory (`boat list
     --json`, `pageInfo.hasMore` false) with matching labels, keep it. If its installed
     `RELEASE.json` already equals `{p, b}`, return its lease at once.
  3. If the record has an intent but no worker (a crash or a lost `new` response), adopt
     the live worker carrying that intent label. Only if the inventory is complete and
     has none does it create again, under a new nonce; the old nonce becomes an orphan
     that recovery deletes if it ever appears.
  4. Otherwise create: `boat new --from <image for b> --no-env --no-monitoring
     --no-snapshots --ttl <ttl> [--type T] --label k=v ... --json`, then parse the
     `created` event as `guard_new` does. An exit status other than 0 with an id still
     records the id (it exists and must be adopted or deleted).
  5. Install and verify (below). A failed install or verification deletes the worker
     and raises `PoolError` with a fixed reason; the engine retries (`INFRA_ERROR`).
- *Install and verify* (takes over `launch.sh:685-707`), on the worker, each a separate
  `boat ssh` call:
  1. stream the bundle on stdin to `~/releases/<p>.tgz.part`, `sha256sum -c` it, rename;
  2. unpack into `~/releases/<p>.x`, rename to `~/releases/<p>`;
  3. pin OpenCode 1.19.0 and Codex 0.162.1 (launch.sh's script verbatim, one retry);
  4. build the Medusa image if missing (launch.sh's command);
  5. `worker_release.py --manifest <factory-only manifest>` (one retry);
  6. `run.bench_manifest()` of `~/unbug-bench`, which must equal `b`
     (`infra:bench_mismatch`; the worker is deleted, since its image is wrong);
  7. write `~/releases/<p>/RELEASE.json` = exactly `{"plumbing_version": p,
     "bench_version": b}` atomically, then switch the symlink `~/factory-release ->
     releases/<p>` with a rename.

  `RELEASE.json` is written last, so its presence means verified. A plumbing release on
  a kept worker installs into a new directory and switches the link; a detached attempt
  still running from the old directory keeps its working directory. A bench change
  needs a new worker, because the bench comes from the image.
- *`release(lease)`*: `boat delete <id> --yes --json`, then `boat deletion status <op>
  --json` until `completed` (validated with `boat_lifecycle.completion`), keeping the
  request and completion as receipts in the state directory; then the record goes. An
  id already absent from a complete inventory counts as deleted. Idempotent.
- *`alive(lease)`*: live state and matching labels in the inventory. If the inventory
  cannot be read, it answers True: unknown is never "dead", for the same reason a
  transport failure is RUNNING.
- *`recover()`*, called once by the engine on start: with a complete inventory, adopt
  every pool-labelled worker that a record names (by id or by intent), delete every
  other pool-labelled worker, and drop records whose worker is gone. Workers without
  the pool label are never touched. An incomplete inventory deletes nothing.

**Worker ids.** `WorkerLease.worker_id` must match `[a-z0-9][a-z0-9-]{0,62}`, but a Boat
id is `bx_` plus eight characters. The lease carries the id with `_` replaced by `-`
(`bx-d6dzvjbc`); Boat ids never contain `-`, so the mapping is exact both ways
(`lease_worker_id`, `boat_id`). This is a contract finding, worked around here.

**Errors.** `PoolError(reason)` carries only a reason from the contract grammar, for
example `infra:worker_create_failed`, `infra:inventory_unavailable`,
`infra:release_upload_failed`, `infra:cli_pin_failed`, `infra:release_qualify_failed`,
`infra:bench_mismatch`. WP1's executor turns it into `INFRA_ERROR`.

### `factory/durable/channel.py` (implements `WorkerChannel`)

- `blob_name(ref)` = `<digest>.<kind>.age`, the `attempt_paths` naming. `start`'s
  `blobs` maps such names to ciphertext.
- *`start`*: for each blob, one `boat --stdin ssh` writes `~/durable/blobs/<name>` via a
  temporary file, a `sha256sum -c` of the bytes the control side sent, and a rename. If
  any push fails, `start` returns without sending the frame (the next poll is ABSENT and
  the engine retries). Then it runs `cd ~/factory-release && python3 -B
  factory/durable/worker_step.py start` with `start_frame(...)` as the only stdin.
  Keys travel only in that stdin, never in an argument.
- *`poll`*: runs `poll` with `key_frame` on stdin. Only exit 0 with exactly one line that
  `poll_from_record` accepts is an answer; anything else (ssh error, timeout, other exit
  status, extra or unparsable output, a contract error) is `Poll(RUNNING)`.
  On DONE, every output Ref of the result (`snapshot`, `receipt`, `feedback`, `report`,
  `registry`, `archive`, `diagnostic`) not already in the store is fetched from the
  attempt's `out/` with its sha256 in the same call, checked, and `put_sealed` under the
  batch scope for `BATCH_SCOPED` kinds and the case scope otherwise. Any fetch or store
  failure makes the poll RUNNING, so DONE is returned only once every output is stored.
  A `checkpoint` Ref is fetched the same way; if that fails, the poll is returned
  without the checkpoint rather than with a Ref the store does not hold.
- *`cancel`*: runs `cancel` with `key_frame` on stdin and ignores the outcome. The
  engine learns that the cancel landed from the next poll (a cancel always leaves a
  result), which is how WP1 retries a cancel after a transport failure.
- Nothing raises on worker errors. Bad caller input (a blob name outside the naming,
  a lease for another case) is a `ContractError`, before any transport.

## What it deletes

Nothing yet. WP9 deletes `launch.sh` and `boat-launch-guards.sh`; this package is the
replacement for their provisioning half. The pool does not read or write any launch
state, spend file or `ids` file of the old launcher.

## What it does not do

- Model credentials and router delivery (`launch.sh:711` onward, `push-secrets`,
  `router_delivery.py`) are not part of the release install. Row
  `new-worker-router-delivery-1` stays open; it needs WP7 and the worker side.
- Boat machine spend is not reserved or metered (row 17), and final stopped usage
  is not captured before deletion (row `new-boat-stop-capture-1`).
- Installing a bench tree onto a worker: the bench comes from the image.

## Tests

`tests/factory/test_durable_workers.py` and `tests/factory/test_durable_channel.py`, run
with `BOAT_CMD` set to a stand-in Boat executable written in the test files. The
stand-in answers from real saved Boat CLI outputs:

- `boat new --json`: the `created` event shape of
  `tests/factory/fixtures/isolation-timeouts/created.json`, with real ids from the saved
  fixtures (`bx_d6dzvjbc`, `bx_sk2p68qq`, `bx_z4wktrbn`, `bx_bykfqbyn`);
- `boat list --json`: the envelope of `isolation-timeouts/list.json`; rows use the
  fields of the saved readiness observation (`isolation-settlement-cloud/*readiness.json`)
  plus `labels`, which is documented in the saved provider contract
  (`docs/reports/stream-b-provider-contract-20261031/create.md`) but has not been seen in
  a live capture;
- `boat delete` / `boat deletion status`: the saved operations
  `isolation-settlement-cloud/deletion-{request,completion}.json`.

`boat ssh` runs the command locally with `HOME` set to one directory per worker, so the
upload, checksum, unpack, manifest filter, real `run.bench_manifest()`, `RELEASE.json`
and symlink steps really run. The CLI pin, Medusa image and `worker_release.py` steps
need `/usr/local/bin`, Docker and Node on a bench image, so tests replace those three
commands with stand-ins; they are not exercised here.

The channel tests install a stand-in `factory/durable/worker_step.py` (in the test
file) that obeys the contract docstring exactly: O_EXCL attempt marker, per-case lock,
`attempt_busy`, setsid detach, tombstoning cancel, first-wins results via `link()`, and
one `to_record(Poll)` line. The `ArtifactStore` is a dict fake written from the
protocol.

Workers: store keeps a bundle once and re-checks its digest; deterministic rebuild;
refused bundles; fresh acquire with labels, checksum and exact `RELEASE.json`;
idempotent acquire; plumbing roll on the same worker; bench mismatch deletes the worker;
a lost `new` response is adopted by its intent label with no duplicate; a restart adopts
recorded workers and deletes unrecorded pool-labelled ones, leaving others alone; an
incomplete inventory deletes nothing; a dead worker is replaced; release with operation
receipts, idempotent; `alive` under list failure; upload corruption refused.

Channel: start then RUNNING then DONE with every output in the store under the right
scope; a second start does nothing; ssh failure, timeout, bad exit, garbage and extra
output are RUNNING; ABSENT only from an answering worker; DONE with a missing or
corrupt output blob is RUNNING and stores nothing; cancel of a live attempt and a
tombstone before start; `attempt_busy`; a failed blob push sends no frame; no key in
any Boat argument; nothing raises.

## Murphy rows

Targets from the design: 17, 29, `new-boat-stop-capture-1`, and with WP7
`new-worker-router-delivery-1`. None closes with this package: every row needs a live
Boat run, and there is no Boat or Hetzner access in this sandbox. Row 29 is the one this
package works towards (creation and deletion reconciled by label and operation id);
rows 17 and `new-boat-stop-capture-1` and `new-worker-router-delivery-1` are not
addressed (see "What it does not do").
