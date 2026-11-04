# Worker checkpoint read-back and receipt revocation (Murphy row 34, offline part)

Status: proposed, revision 2 (after `docs/reviews/checkpoint-readback-design-1.md`).
Branch `claude/murphy-immutable-checkpoints`, cut from `factory-simplify@fbca505`.
Murphy row 34 stays **open** after this change (see "What remains open").

## Objective, in plain words

When a worker says a checkpoint is safely off the machine, that must be true:
the exact bytes must read back from R2. When a later checkpoint replaces that
copy, the old note must stop saying it is safe.

Effort: about 60 lines of code and one new test file, all offline. No live R2,
workers or money.

## Problem

Row 34 says off-worker checkpoints are optional, mutable and incomplete as a
recovery package. Its four facts, checked against the code on `fbca505`:

1. **R2 "success" means only that the PUT succeeded.**
   - `factory/r2_upload.py:upload` runs `curl -X PUT` and returns the object key
     on exit status 0. Nothing reads the object back.
   - `RunArtifacts.seal` (`factory/run_artifacts.py:127-128`) then records that
     key in `card["r2_object"]`.
   - `factory/durable_checkpoint.py:checkpoint_progress` turns the key into
     `remote_durable: true`.
   - Two callers trust that bit as a durability barrier before more paid work:
     the stress publication barrier (`factory/run.py:233`, raising
     `InvalidInfra` at `factory/stress_progress.py:39`) and the extension
     evaluator (`factory/extension_evaluator.py:437`).
2. **One mutable object per worker.** `factory/launch.sh:780` presigns PUT
   links for exactly two keys, `vm/<id>/checkpoint.tar.gz.age` and
   `vm/<id>/final.tar.gz.age`. Every checkpoint seal overwrites the first one
   (and the local `sealed/<case>.checkpoint.tar.gz.age`, `run_artifacts.py:124`).
3. **A receipt keeps saying "durable" after its copies are replaced.** This
   shows in real saved cards. In `tests/factory/fixtures/e15450-collected-card.json`:
   - The `durable_checkpoint` receipt says generation `460a8f21…` is local and
     remote durable, at `/home/user/sealed/…checkpoint.tar.gz.age` and
     `vm/bx_gdt298d7/checkpoint.tar.gz.age`.
   - The same card's own later archive is `03a1dd51…`, at the same path and
     the same key.
   - The stop seal outside `checkpoint_progress` (`run.py:3505`) replaced both
     copies, and the receipt was not updated.
   - `canary6-round8-collected-card.json` and `c7d405-confirm-timeout-card.json`
     show the same thing.
4. **No complete card/key receipt bound to a generation reaches the controller
   while the worker is alive.** There is also no acknowledgement before the
   recovery pointer moves forward.

### What already exists, and is not duplicated here

- **Controller generation store.** `factory/batch_service.py:collect` freezes
  collected files into an immutable `generations/<case>/<sha256>/` directory,
  with a bound manifest.
- **Controller publication.** `factory/batch_holder.py:collect` writes an outbox
  entry, then publishes each member to R2 at
  `generations/<case>/<generation>/<name>` via `r2_publish`.
  - That step does a PUT, a streamed GET and a digest check.
  - After it, the holder writes the ACK, swaps `current/<case>.json`
    atomically, re-reads the pointer, and marks the outbox entry acknowledged.
- **The design behind it.** This is `docs/designs/batch-service.md`
  ("Collection and publication"). It covers facts 2 and 4 for every
  **collected** generation.
- **What remains.** The in-flight checkpoint on the worker. It is the only copy
  off the worker between collections, and it is what the two durability
  barriers wait on.

## Change

1. **Read the object back before claiming it (`factory/r2_upload.py`).**
   - **Links required.** `upload(archive, checkpoint, links=None)` now needs
     both links for its kind in `~/.factory-r2`:
     - `checkpoint` and `checkpoint_get`; or
     - `final` and `final_get`.

     If either is missing, it returns `None`, the same as an absent links file
     today.
   - **Read-back.** After a successful PUT, it streams the object back and
     hashes it with SHA-256.
     - It never buffers the whole archive.
     - It stops as soon as it receives more bytes than the local archive holds.
     - It returns the key only if the size and SHA-256 equal the local archive.
       Any mismatch, curl error or timeout returns `None`.
   - **How the GET runs.**
     - `subprocess.Popen(["curl", "-fsS", <GET link>], stdout=PIPE)`.
     - A monotonic bound of 1800 s, the same as the PUT's. When it expires, the
       process is killed.
     - No `--retry`, because a retried transfer would append to bytes already
       hashed. A failure fails closed, and the next checkpoint boundary
       retries.
   - **No leaks.** URLs never enter exceptions, logs or the card.
   - **`target(checkpoint, links=None)`.** It returns the key that `upload`
     would write, or `None`, using the same links parsing.
   - **Why not reuse `batch_holder.r2_publish`.**
     - It is controller-only: it presigns locally and imports the holder.
     - The worker has only presigned links, and it already uses curl as its
       transport.
     - Both apply the same rule: a size bound, a streamed SHA-256, then
       equality.
2. **Add GET links in the launcher (`factory/launch.sh:780`).**
   - The launcher also presigns GET for the same two keys, with the same 7-day
     lifetime, and writes them as `checkpoint_get` and `final_get`.
   - If signing fails, no file is written, as today.
   - The worker still gets no R2 credentials, only links for its own two
     objects. It already holds the plaintext those objects encrypt.
3. **Revoke a receipt before its copies are replaced
   (`factory/run_artifacts.py:seal`).**
   - **When.** On every `checkpoint=True` seal, before any of these:
     - writing the work tree's `scorecard.json`, which goes into the archive;
     - replacing the local archive;
     - the PUT.
   - **Condition.** The card's `durable_checkpoint` receipt names either:
     - this seal's local `out` path as its `archive`; or
     - this seal's `target(True)` key as its `r2_object`.
   - **Why it ignores `case_key`.** The local archive is replaced on every
     checkpoint seal, uploaded or not. The condition does not depend on whether
     an upload will happen. If it revokes a receipt that turns out not to be
     replaced, the only error is towards "not durable".
   - **Effect.**
     - Set `local_durable: false`, `remote_durable: false` and `pending: true`.
     - Add `superseded: "checkpoint_replaced"`.
     - Keep `sha256`, `archive` and `r2_object`, so the history stays readable.
   - **Where it lives.** Today the only checkpoint seal outside
     `checkpoint_progress` is `run.py:3505`. The revocation goes in `seal`
     because `seal` owns replacing both copies. That way it also covers any
     future caller.
   - **Inside `checkpoint_progress`.** That function replaces the receipt with
     a fresh pending one, with no `archive` or `r2_object`, before it seals. So
     the revocation is a no-op there.
   - **Removal.** Delete this revocation once item (a) below gives every
     generation its own objects.
4. **Receipt version (`factory/durable_checkpoint.py`).**
   - New receipts are `version: 2`. Version 2 means `remote_durable: true`
     implies a verified read-back of exactly `sha256` at `r2_object`.
   - Saved version 1 receipts mean PUT-only. Nothing re-reads old receipts to
     grant anything; the two barriers read only the receipt just written.
   - The `reason` for a result that is not remote stays
     `remote_upload_unavailable_or_failed`.
5. **Refuse mixed versions in place (`factory/resume-in-place.sh`).**
   - **The problem.** `resume-in-place.sh` (lines 27-34) copies the host's
     current `factory/` onto a parked VM, and it never rewrites
     `~/.factory-r2`. A VM launched before this change would run the new
     `r2_upload` with PUT-only links. Every checkpoint would fail its barrier,
     and stress publication would exhaust its infrastructure retries.
   - **The guard.** It is the first command in the script's remote shell, before
     `rm -rf ~/factory`. If `~/.factory-r2` exists and lacks either
     `checkpoint_get` or `final_get`, it refuses with "R2 links predate
     checkpoint read-back; restore this case with factory/launch.sh
     --restore". The VM, its code and its plaintext stay unchanged.
   - **Absent links file.** It passes. That is today's "host-collected only"
     case, and the new code claims nothing in it.
   - **No other path mixes versions.**
     - `launch.sh`'s in-place restart (`resume_case`, about line 620) reuses
       the worker's installed code.
     - A fresh launch or a restore rewrites the links file.

**Behaviour change.** A worker whose R2 GET fails is no longer remote durable.
The two barriers then hold, as they already do after a failed PUT. That is the
fail-closed direction batch-service asks for: a failed upload "blocks
expensive work rather than silently advancing".

## What it deletes

- The path in `upload` that treats a PUT exit status as durability.
- Nothing else is removed. This change adds GET links, `target()`, the
  revocation, the receipt version and the resume guard.
- The single-object layout stays, because `factory/restore_bundle.py:92` binds
  to the literal `vm/<id>/checkpoint.tar.gz.age`. The launcher restore
  (`launch.sh:741`, `:175`) uses whichever `r2_object` the card names, and it
  checks that object's digest against the card's `sha256`.

## Tests (new file `tests/factory/test_checkpoint_readback.py`)

**Setup for T1-T3.**
- `c` is a `SimpleNamespace` built from the real card:
  - `case_id = card["case"]`;
  - `args = SimpleNamespace(dry_run=False)` with no `batch_release_sha256`.
    `seal` then takes the founder plus case-key path, and `case_key` is real.
  - `work`: a temporary tree holding `logs/runner.log`;
  - `recipient`: a throwaway age public key;
  - `ledger`: a temporary JSON file;
  - `t0 = time.time()`.
- `RunArtifacts`:
  - `bench`: a temporary directory with an empty `results/`;
  - `statements_recipient`: an absent path;
  - `agent_state=()`;
  - `pilot_homes`: returns `[]`;
  - `retain_delivery`: fails the test if called, because a checkpoint seal
    never calls it.
- **Environment.**
  - `HOME` is a temporary directory holding `.factory-r2`, so `upload` reads
    it through `Path.home()`.
  - `NO_PROXY` and `no_proxy` include `127.0.0.1`, so curl reaches the local
    double.
- **Real parts.**
  - The saved card `tests/factory/fixtures/e15450-collected-card.json`, used
    with its receipt, generation and `vm/bx_gdt298d7` prefix as saved.
  - The real `RunArtifacts.seal`, with real `tar` and `age`.
  - The real `checkpoint_progress`.
  - The real `r2_upload.upload`, running real `curl`.
- **No case is decrypted.** The archive contains only the test work tree.
- **Authored double.** The R2 endpoint is a local HTTP server on 127.0.0.1. It
  stores PUT bodies and serves GETs. It is the only authored part, and it is
  why row 34 does not close on this test.

**Cases.**
- **T1: stale receipt (real card).**
  - Seal `checkpoint=True` with the e15450 card, unmodified. The links prefix
    is `vm/bx_gdt298d7`, so the receipt's saved `r2_object` key matches the
    target key.
  - Before: the receipt claims `460a8f21…` local and remote durable.
  - After: the receipt has `local_durable: false`, `remote_durable: false` and
    `superseded` set. This holds in `c.card` and in the `scorecard.json` sealed
    inside the new archive, which the test decrypts with its own key.
  - The new top-level `r2_object` is set. The bytes the double holds equal the
    new archive.
  - **T1b control.** A final seal (`checkpoint=False`) writes a different local
    path and key, and does not revoke. For that call, `retain_delivery` is
    allowed as a no-op.
  - **T1c local-path condition.** There is no links file, so there is no
    upload and no `target`. Only the receipt's `archive` field is relocated
    to the test's `sealed/` path, because the saved `/home/user/sealed` path
    cannot exist in the test. A checkpoint seal still revokes the receipt.
- **T2: honest store.** `checkpoint_progress` over the real card writes a
  `version: 2` receipt with `remote_durable: true`. Its `sha256` equals the
  bytes the double holds.
- **T3: read-back failures.** The cases are:
  - the store keeps the previous object (PUT ignored);
  - the GET is truncated;
  - the GET has extra bytes;
  - the GET returns 404;
  - the links file has no `checkpoint_get`;
  - the PUT returns 500.

  For each one, `checkpoint_progress` yields:
  - `remote_durable: false`;
  - no `r2_object` in the receipt;
  - `reason: remote_upload_unavailable_or_failed`.

  The card's top-level `sha256`, `archive` and `r2_object` are restored to the
  real e15450 values. That restore is `checkpoint_progress`'s existing contract,
  checked by `tests/factory/test_durable_checkpoint.py`.
- **T4: launcher contract.**
  - The test finds the single `launch.sh` line containing
    `json.dumps({"prefix"`, and extracts its `python3 -c '…'` program.
  - It runs that program with a worker id and four stub URLs.
  - It asserts the keys `checkpoint`, `checkpoint_get`, `final` and
    `final_get`, and the `vm/<id>` prefix.
  - It feeds the output to the real `upload` in the honest case.
  - It also asserts that `launch.sh` calls `r2_sign GET` for both keys.
- **T5: no URL leak.** On every T3 failure, the card, the receipt and the
  captured stdout/stderr contain no stub signature marker (`X-Amz-Signature`).
- **T6: resume-in-place refusal.** The test extracts the guard line from
  `factory/resume-in-place.sh` and runs it with `sh` against a temporary HOME:
  - old links, without GET links: refused;
  - new links: passes;
  - no links file: passes.

**Existing tests.**
- `test_startup_smoke` and `test_practice_startup` patch `r2_upload.upload` and
  keep their stubs. `upload` keeps its signature.
- `tests/factory/test_r2_upload.py` and `tests/factory/test_durable_checkpoint.py`
  pass unchanged.

## Murphy rows

**Row 34 stays open.** This change fixes fact 1 (PUT-only success) and fact 3
(stale receipts). Facts 2 and 4 are already handled by the controller path
above, but only for collected generations.

**Still open:**
- **(a) Immutable per-generation worker objects.** A worker cannot presign keys
  named by digest. This needs either a holder signing call or a bounded slot
  scheme, plus a change to `restore_bundle`'s key binding.
- **(b) Publishing a live worker's checkpoint generation.** The card, casekey
  and archive go to the controller store, with an ACK before the next paid
  unit. This is batch-service's "worker checkpoints synchronously await
  durability ACK", and row 35 shares it.
- **(c) Live qualification.** That an R2 GET of a just-PUT object returns the
  same bytes, and that the timing fits the retirement reserve (owned by
  row 16).

**Register text.** Status stays `open`. This branch does not edit
`docs/murphy-register.md`:
- the owned `claude/practice4-release-prep` branch also changes that file;
- this branch's assignment forbids touching files that owned branches change.

**Proposed new row.** ENGINEERING §2 asks for a row for this real failure. It
is proposed here verbatim, for the integrator to add at merge:

> | new-checkpoint-readback-1 | **A durable receipt keeps claiming a replaced
> checkpoint.** | `factory/run_artifacts.py:124`, `:128`;
> `tests/factory/fixtures/e15450-collected-card.json` (receipt 460a8f21 vs card
> 03a1dd51, same path and key) | A later checkpoint seal replaces the local
> archive and the single R2 object, but leaves the earlier receipt
> `local_durable`/`remote_durable: true`. | Medium / misleading recovery
> evidence | Revoke the receipt before its copies are replaced. | No | B |
> closed | `tests/factory/test_checkpoint_readback.py` T1 (real e15450 card,
> real seal/tar/age) |

T1's revocation proof uses the real card and the real `seal`. It does not
depend on how faithful the R2 double is.

Declining design-1's "edit the register on this branch" finding is a rejection
of a blocking finding. It goes to a second goldfish (ENGINEERING §1).

**Row 34's Today cell.** The integrator should add at merge: "Worker R2 claims
are read-back verified and stale receipts are revoked (checkpoint-readback);
objects are still one mutable key per worker."

## Risks

- **Doubled transfer per checkpoint.** Each PUT is followed by one GET.
  - Checkpoints are throttled to one per 900 s, apart from forced barriers.
  - R2 egress is free; the cost is transfer time on the worker.
  - Estimate for the largest recorded archive (527,987,760 bytes,
    new-single-path-1): about 34 minutes each way at the launcher's
    conservative 256 KiB/s floor, or about 26 s at 20 MB/s.
- **The stop seal.** The GET is part of the stop seal at `run.py:3505`. If it
  does not finish, `r2_object` stays unset. The host still collects the local
  archive, so nothing is falsely claimed.
- **Short remaining lifetimes.** Shortening the stop seal's GET when little
  worker lifetime is left is row 16's reserve work, owned elsewhere.
- **Read-after-write consistency.** Cloudflare documents R2 as strongly
  consistent for read-after-write; this design does not verify that. If a read
  were stale, it would fail closed, with no false claim.
