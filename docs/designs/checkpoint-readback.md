# Worker checkpoint read-back and receipt revocation (Murphy row 34, offline part)

Status: proposed. Branch `claude/murphy-immutable-checkpoints`, cut from
`factory-simplify@fbca505`. Murphy row 34 stays **open** after this change
(see "What remains open").

## Problem

Row 34: off-worker checkpoints are optional, mutable and incomplete as a
recovery package. Its four facts, checked against the code on `fbca505`:

1. **R2 success means a successful PUT.** `factory/r2_upload.py:upload` runs
   `curl -X PUT` and returns the object key on exit status 0. Nothing reads the
   object back. `RunArtifacts.seal` (`factory/run_artifacts.py:127-128`) then
   names that key in `card["r2_object"]`, and
   `factory/durable_checkpoint.py:checkpoint_progress` turns it into
   `remote_durable: true`. Two callers trust that bit as a durability barrier
   before more paid work: the stress publication barrier (`factory/run.py:233`)
   and the extension evaluator (`factory/extension_evaluator.py:437`).
2. **One mutable object per worker.** `factory/launch.sh:780` presigns PUT for
   exactly `vm/<id>/checkpoint.tar.gz.age` and `vm/<id>/final.tar.gz.age`. Each
   checkpoint seal overwrites the first one.
3. **A receipt stays "remote durable" after its object is overwritten.** This is
   in a real saved card: `tests/factory/fixtures/e15450-collected-card.json`.
   - Its `durable_checkpoint` receipt says generation `460a8f21…` is
     `remote_durable: true` at `vm/bx_gdt298d7/checkpoint.tar.gz.age`.
   - The same card's own later archive is `03a1dd51…`, and it names the same
     key as `r2_object`.
   - A later checkpoint seal outside `checkpoint_progress` (a pause or stop
     seal) replaced the object. The receipt kept claiming the old generation.
   - `canary6-round8-collected-card.json` and `c7d405-confirm-timeout-card.json`
     show the same pattern.
4. **No complete generation-bound card/key receipt reaches the controller
   while the worker lives, and there is no ACK before the recovery pointer
   advances.**

### What already exists (not duplicated here)

- **Controller generation store.** `factory/batch_service.py:collect` freezes
  collected files into immutable `generations/<case>/<sha256>/` with a bound
  manifest.
- **Controller publication.** `factory/batch_holder.py:collect` writes an
  outbox entry, then publishes each member to R2 under
  `generations/<case>/<generation>/<name>` via `r2_publish`. That PUT is
  followed by a streamed GET and a digest comparison. Only after that does it
  write the ACK, atomically replace `current/<case>.json`, re-read the pointer,
  and mark the outbox entry acknowledged.
- **Coverage.** This is the design in `docs/designs/batch-service.md`
  ("Collection and publication"), and it covers facts 2 and 4 for every
  **collected** generation.
- **The gap.** What remains on the worker is the in-flight checkpoint. It is
  the only off-worker copy between collections, and it is what the two
  durability barriers above wait on.

## Change

Keep the existing object keys, interfaces and restore paths, and make the
worker's remote claim true.

1. **Read-back before claiming R2 (`factory/r2_upload.py`).**
   - **Links.** `upload(archive, checkpoint, links=None)` now requires both
     links for its kind in `~/.factory-r2`: `checkpoint` + `checkpoint_get`,
     or `final` + `final_get`. A missing link returns `None`, as an absent
     links file does today.
   - **Read-back.** After a successful PUT it streams the object back with
     `curl -fsS --retry 3 --max-time 1800 <GET link>` into a SHA-256. It never
     buffers the whole archive. It aborts as soon as more bytes arrive than the
     local archive holds.
   - **Result.** It returns the key only if the size and SHA-256 equal the
     local archive. Any mismatch, curl error or timeout returns `None`.
   - **No URL leaks.** URLs never enter exceptions, logs or the card.
2. **GET links from the launcher (`factory/launch.sh:780`).**
   - The launcher also presigns GET for the same two keys, with the same 7-day
     lifetime, and writes them as `checkpoint_get` and `final_get`.
   - If signing fails, the file is not written, as today.
   - The worker receives no R2 credentials, only links for its own two
     objects. It already holds the plaintext these objects encrypt.
3. **Revoke a receipt whose object is about to change
   (`factory/run_artifacts.py:seal`).**
   - **When.** Before writing the work tree's `scorecard.json` (which is sealed
     into the archive), and before any PUT. The condition is: this is a
     checkpoint seal that will attempt an upload, and the card's
     `durable_checkpoint` receipt names the same key with `remote_durable: true`.
   - **What.** Set the receipt to `remote_durable: false, pending: true` and add
     `superseded: "remote_object_replaced"`. It keeps its `sha256` and
     `r2_object`, so the history stays readable.
   - **Why before the PUT.** The new PUT may replace the object even if its
     read-back later fails.
   - **Key.** `r2_upload.target(checkpoint, links=None)` returns the key that
     `upload` would write, or `None`. It reuses the same links parsing.
   - **Final seals** write `final.tar.gz.age` and so never revoke a checkpoint
     receipt.
   - **`checkpoint_progress`** replaces the receipt with a fresh pending one
     before it seals. The revocation is therefore a no-op there, and the new
     receipt is filled from the verified result.
4. **Receipt version (`factory/durable_checkpoint.py`).**
   - New receipts are `version: 2`. Version 2 means `remote_durable: true`
     implies a verified read-back of exactly `sha256` at `r2_object`.
   - Saved version 1 receipts mean PUT-only. Nothing rereads old receipts to
     grant anything. The two barriers only read the receipt that
     `checkpoint_progress` has just written.
   - The `reason` for a not-remote result stays
     `remote_upload_unavailable_or_failed`.

**Behaviour change.** A worker whose R2 GET fails is no longer remote durable.

- The stress publication barrier and the extension evaluator then hold, which
  is already their behaviour after a failed PUT.
- That is the intended fail-closed direction in batch-service ("failed upload
  stays retryable and blocks expensive work rather than silently advancing").
- Workers whose links file lacks GET links are affected the same way. They can
  only be workers whose source bundle predates this change, and such workers
  also run the old `r2_upload`. Bundle and launcher are one release, so this is
  not a mixed state.

## What it deletes

- The "PUT exit status is durability" path in `upload`.
- No other code path is removed. The single-object layout stays, because
  `factory/restore_bundle.py:92` and the launcher restore (`launch.sh:175`)
  bind to `vm/<id>/checkpoint.tar.gz.age`. Changing that key is the live-R2
  part (below).

## Tests (new file `tests/factory/test_checkpoint_readback.py`)

**Real artifacts.**
- The real saved card `tests/factory/fixtures/e15450-collected-card.json`.
  Its receipt, generation and `vm/bx_gdt298d7` prefix are used as is.
- The real `RunArtifacts.seal` with real `tar`/`age` and a throwaway
  recipient. No case is decrypted: the archive contains only the test work tree.
- The real `checkpoint_progress`.
- The real `r2_upload.upload` running real `curl`.

**Authored double.** The R2 endpoint is a local HTTP server on 127.0.0.1. It
stores PUT bodies and serves GETs. It is the only authored part, and it is why
the row does not close on it.

**Cases:**
- **T1 stale receipt (real card).**
  - Seal `checkpoint=True` with the e15450 card, prefix `vm/bx_gdt298d7`.
  - Before: the receipt claims `460a8f21…` remote durable at the checkpoint key.
  - After: the receipt is `remote_durable: false` and `superseded`, both in
    `c.card` and in the `scorecard.json` sealed inside the new archive. The
    archive is decrypted with the test key; it holds only test files.
  - The new `r2_object` is set, and the bytes held by the double equal the new
    archive.
  - Control: a final seal (`checkpoint=False`) does not revoke the receipt.
- **T2 honest store.** `checkpoint_progress` over the real card produces a
  `version: 2` receipt with `remote_durable: true`. Its `sha256` equals the
  bytes held by the double.
- **T3 read-back failures.** For each failure, `checkpoint_progress` yields
  `remote_durable: false`, no `r2_object` on the card, and
  `reason: remote_upload_unavailable_or_failed`. The failures:
  - the store keeps the previous object (ignored PUT);
  - GET truncates;
  - GET returns extra bytes;
  - GET returns 404;
  - the links file lacks `checkpoint_get`;
  - PUT returns 500.

  In the first case, the stress barrier function `install_publication_barrier`
  is not exercised. The barrier reads exactly `remote_durable`, which T3 checks.
- **T4 launcher contract.**
  - `launch.sh` presigns both PUT and GET for both keys.
  - The JSON it writes contains `checkpoint_get` and `final_get`.
  - The check runs the launcher's own `python3 -c` JSON line with stub URLs, so
    it is not just a text match.
- **T5 no URL leak.** On every T3 failure, the card, receipt and captured
  stdout/stderr contain no link query string (`X-Amz-Signature` marker in the
  stub URLs).

**Existing tests.** Tests that patch `r2_upload.upload` (`test_startup_smoke`,
`test_practice_startup`) keep their stubs. `upload` keeps its signature.

## Murphy rows

- **Row 34: stays open.** This change fixes fact 1 (PUT-only success) and
  fact 3 (a stale remote receipt). For collected generations, facts 2 and 4
  are already handled by the controller path above.
- **Still open, and needs live R2 or larger work:**
  - (a) Immutable per-generation worker objects. A worker cannot presign
    digest-named keys, so this needs a holder signing call or a bounded slot
    scheme, and a change to `restore_bundle`'s key binding.
  - (b) Publishing a live worker's checkpoint generation (card + casekey +
    archive) to the controller store with an ACK before the next paid unit.
    That is batch-service's "worker checkpoints synchronously await durability
    ACK", shared with row 35.
  - (c) Live qualification that R2 GET of a just-PUT object returns the same
    bytes, and timing within the retirement reserve (row 16 owns the reserve).
- **Register text.** The Status stays `open`. The row's "Today" text is not
  edited on this branch, because `docs/murphy-register.md` is also changed by
  the owned `claude/practice4-release-prep` branch. The PR asks the integrator
  to update the row's Today cell at merge to say: "worker R2 claims are
  read-back verified and stale receipts are revoked (checkpoint-readback);
  objects are still one mutable key per worker."

## Risks

- **Doubled R2 egress per checkpoint.** One GET per PUT. Checkpoints are
  throttled to one per 900 s, apart from forced barriers. R2 egress is free;
  the cost is transfer time on the worker. The GET is bounded by the same
  1800 s as the PUT. Row 16 owns fitting seal and upload into the retirement
  reserve, and this change adds at most one more bounded transfer there.
- **Eventual consistency.** R2 is strongly consistent for read-after-write. If
  it were not, a stale read fails closed: there is no false durability claim.
