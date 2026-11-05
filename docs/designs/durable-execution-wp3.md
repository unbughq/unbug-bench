# Durable execution WP3: sealer and artifact store

Status: implemented, for diff review. Package WP3 of `docs/designs/durable-execution.md`
(brief in `docs/designs/durable-execution-wave1.md`). Branch `de/wp3`, cut from
`durable-execution` at `db13be8`. Contract version 5.

## Problem

The engine records only `Ref`s: a keyed digest and a kind. Case content (inputs,
snapshots, feedback, receipts, archives) must live somewhere durable, encrypted, and
named so that:

- the same bytes always get the same name inside one scope, and the name says nothing
  across scopes;
- only the holder of the scope key can read them;
- a crash or a cut network during an upload never leaves a partial object under a
  name the engine may later read;
- the store on the control VM never sees a key or plaintext (workers hold no R2
  credentials; the channel moves blobs).

Today the factory seals with ad-hoc `age` calls (`run_artifacts.py`, `r2_upload.py`)
against random `age-keygen` identities stored on disk, and uploads with a pre-signed
PUT that is never read back (Murphy row 34).

## Change

One module, `factory/durable/artifacts.py`. It implements the contract's `Sealer`
and `ArtifactStore` protocols and calls nothing outside the contract, `age` and the
standard library.

### Sealer (`AgeSealer`), used on both sides

- `seal(scope_key, kind, plaintext)`:
  1. `secret, hmac_key = derive_keys(scope_key)`;
  2. `Ref(artifact_digest(hmac_key, plaintext), kind)`;
  3. encode `secret` as an age identity: Bech32 (BIP 173, not Bech32m) of the 32
     bytes with HRP `age-secret-key-`, upper-cased, exactly as `age-keygen` writes it;
  4. run `age --encrypt -i /dev/fd/N` with the plaintext on stdin and the ciphertext
     on stdout. With `--encrypt`, age 1.1 encrypts to the identity's own X25519
     recipient. The identity travels through an anonymous pipe (`pass_fds`), so it is
     never written to disk, never in argv, and never in the environment.
- `open(scope_key, ref, ciphertext)`: `age --decrypt -i /dev/fd/N`, then recompute
  `artifact_digest` on the plaintext and compare (constant time) with `ref.digest`.
  A wrong key, a damaged ciphertext, or a ciphertext swapped in under another Ref all
  raise `ArtifactError("open_failed")` / `ArtifactError("digest_mismatch")`.
- Errors carry fixed codes only. age's stderr is dropped, because it can name files
  or echo input.
- Each `age` run is bounded (`timeout_s`, default 600 s). A stuck `age` is killed,
  and the call raises `ArtifactError("age_timeout")`.

age ciphertext is randomised, so two seals of the same plaintext give two different
ciphertexts with the same Ref. Both open to identical bytes, so which one a store
keeps does not matter.

### Scopes

A Ref is meaningful only with its scope. Kinds in `BATCH_SCOPED` (INPUTS,
STATEMENT_REGISTRY) live in the batch scope (a `BATCH_ID`); every other kind lives in
the case scope (a `CASE_ID`).

- `scope_for(kind, case_id, batch_id)` returns the right scope.
- Every store method refuses a scope that is not a valid id, or that does not match
  the Ref's kind (`ArtifactError("wrong_scope")`). This also rules out path
  traversal: scope, digest and kind are all checked against the contract patterns
  before they form a path or an object key.
- `seal_into(store, keys, sealer, kind, plaintext, case_id, batch_id)` and
  `open_from(...)` compose the three seams (KeyService, Sealer, ArtifactStore) for
  callers (WP1's executor, WP2's channel). They pick the scope with `scope_for`, so
  a batch-scoped kind is always sealed with the batch key.

The Sealer protocol receives only a key, not a scope name, so it cannot itself check
that a batch-scoped kind used the batch key. The store never sees a key: it checks the
scope *name* against the kind. Key-to-scope pairing is enforced by `seal_into`, and
detected by `open` / `open_from`, which fail under the wrong scope's key.

**For WP1 and WP2.** Workers seal their outputs without `seal_into`, and an ADMIT
worker holds both the case and the batch key. So before the engine records any
worker-output Ref, the control side should verify it with `open_from` (scope from
`scope_for`). A recorded Ref then names an object that exists *and* opens under the
right scope's key.

### Object layout

Both backends store one immutable object per (scope, Ref):

```
<prefix>/<scope>/<digest>.<kind>.age
```

`<digest>.<kind>.age` is the same name the wire layout uses for blobs
(`attempt_paths`). Objects are never overwritten with different content in a way a
reader can observe half of. A put is idempotent: an existing object is kept (the
local backend by `link`, R2 by a conditional PUT), and concurrent writers of the same
Ref race harmlessly, because every ciphertext for a Ref opens to the same bytes.

### ArtifactStore (`SealedStore`) over two object backends

`SealedStore(objects, prefix="durable")` implements `put_sealed`, `get_sealed` and
`exists` over a small byte-object interface (`put`, `get`, `exists`). It checks the
scope and that the ciphertext looks like an age file (`age-encryption.org/v1`
header), so it cannot be handed plaintext by mistake. It never takes a key.

- **`LocalObjects(root)`** (tests, offline, and a control-VM cache): writes into a
  temporary file in the target directory, `fsync`s it, then `os.link`s it to the
  final name and `fsync`s the directory. `link` fails if the name exists, so the
  first complete object wins and is never replaced. A crash or exception at any
  point leaves at most a `.tmp-*` file, which no read ever looks at. Both success
  paths (the name already exists, or a concurrent writer linked it first) `fsync`
  the directory before returning, so a returned put survives power loss.
  Directories are `0700`, files `0600`.
  - *Known leak, cache only.* A crash leaves its `.tmp-*` file (up to one artifact
    in size). Nothing sweeps it, because deleting a live writer's temp would fail
    its put. The local backend is for tests, offline runs and a cache, so an
    operator removes stale `.tmp-*` files by hand if they ever matter.
- **`R2Objects(account, access_key, secret_key, bucket)`**: S3 API calls signed with
  SigV4 in the `Authorization` header (the algorithm `bin/r2-presign` uses for query
  signing, here in header form so the payload hash is signed). A PUT signs the payload's sha256 in
  `x-amz-content-sha256` and sends `Content-Length`, so the object store rejects
  any body that is truncated or altered in transit instead of storing it; S3-style
  stores commit a PUT only when the whole body arrived. The PUT also sends
  `Content-Type: application/octet-stream` and `If-None-Match: *`, both signed. A
  412 means a concurrent writer committed first; the backend confirms that object
  is there and keeps it. No request ever follows a redirect: a 3xx comes back as a
  status and fails with a fixed code, so a signed request is never re-sent to
  another host. After a 200 PUT the backend GETs the object back and compares sha256 (as `batch_holder.r2_publish` does),
  and only then returns, so a successful `put_sealed` means durable and readable
  (row 34's "acknowledge durability"). `exists` is a HEAD. Credentials come from
  `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, like
  `bin/r2-presign`. They live only in control-VM memory and never enter an error.
  The HTTP transport is a parameter, so tests can drive it.

`factory/r2_upload.py` is not reused directly: it PUTs to pre-signed links that a VM
receives in a file, with unsigned payloads and no read-back. The durable store runs on
the control VM, which holds the credentials, so it signs each request itself.

## What it deletes

Nothing in wave 1. In WP9, the per-case `.casekey` identities, `r2_upload.py` and
the checkpoint upload path in `launch.sh` are replaced by this module, and go with
the deletion list.

## Tests

`tests/factory/test_durable_artifacts.py`, all with the real `age` 1.1 binary and real
files:

- **Identity encoding.** A real `age-keygen` identity decodes to 32 bytes and
  re-encodes to the identical string; our identity for a derived secret is accepted
  by `age-keygen -y`, and the recipient it prints equals the X25519 public key that
  an independent RFC 7748 implementation in the test (checked against the RFC's
  section 6.1 keys and shared secret) computes from the derived secret.
- **Interop.** A ciphertext from `seal` decrypts with the real `age -d -i <file>`
  using our identity written to a file; a ciphertext made by the real `age -r
  <recipient>` opens with `open`.
- **Keys.** Ciphertext opens only with its scope key: another case's key, the batch
  key, and a damaged ciphertext all fail; a valid ciphertext under the wrong Ref
  fails the digest check.
- **Refs.** The same plaintext gives the same Ref within a scope (ciphertexts
  differ) and different Refs across scopes.
- **Scopes.** Batch-scoped kinds go to the batch scope through `seal_into`; the
  store refuses a batch-scoped kind under a case scope and the reverse; a case key
  cannot open a batch artifact.
- **Interrupted upload, local.** A real child process runs `put_sealed` on a
  64 MiB ciphertext, with `os.write` monkeypatched to write half the bytes and then
  send the process a real SIGKILL. A second run patches `os.link` to SIGKILL after
  the full write instead. Either way, nothing is visible under the final name,
  `exists` is false, `get_sealed` raises missing, and a later put succeeds. An
  `fsync` that fails (injected `ENOSPC`), whether creating the directory or after
  the file's bytes are written, leaves nothing visible and no temporary file.
- **First wins.** A second put of the same Ref does not replace the first object.
  With the `is_file` shortcut hidden, the second put reaches `os.link`, hits
  `FileExistsError`, keeps the first inode, removes its temp and fsyncs the
  directory. The shortcut path fsyncs the directory too.
- **Age timeout.** An `age` that never exits ends in `age_timeout`.
- **R2 signing.** The SigV4 header signer reproduces AWS's published S3 examples
  (GET object with Range, PUT object) exactly.
- **R2 logic over real HTTP.** `R2Objects` talks over real sockets to a local
  S3-like server in the test. The server recomputes every request's SigV4
  signature from what actually arrived (method, raw path, the signed headers' values,
  the test secret), and a wrong secret is refused. It commits a PUT only when the
  whole body arrived and its sha256 matches `x-amz-content-sha256`, and answers 412
  to a conditional PUT of an existing object.
  - A client that disconnects partway through the body leaves nothing visible.
  - A body altered in transit is rejected.
  - A read-back mismatch fails the put.
  - A concurrent writer that commits first is kept, and the put succeeds.
  - HEAD on a missing object is false.
  - A 302 to another host is never followed: every call fails with a fixed code,
    and the other host receives no request.

Not exercised:
- **Real Cloudflare R2.** No R2 credentials exist in this sandbox. The first live run
  of `R2Objects` must confirm that R2 enforces `x-amz-content-sha256` on PUT, as its
  S3 compatibility documentation states, and that it honours `If-None-Match: *`. If
  it ignored that header, concurrent writers would still race harmlessly.
- **HTTPS / TLS verification** through `urllib_transport`. The tests use plain HTTP
  on localhost.

## Murphy rows

WP3 targets 27, 34 and `new-batch-service-2`. This package provides the parts of
each that live in the store; none closes in WP3, because each needs the engine to
use the store on a real run (WP1, then WP9's final exam):

- **27 (mixed generations).** Objects are immutable and content-addressed, and the
  engine records which Refs make a result, so there is no mutable directory to
  replace half of.
- **34 (optional, mutable, unverified checkpoints).** Snapshot objects are
  immutable per Ref, and `put_sealed` returns only after a verified read-back.
- **new-batch-service-2 (card names an absent archive).** `seal_into` returns a
  `Ref` only after the object is stored and read back. With WP1/WP2 verifying
  worker outputs by `open_from` before recording them (above), a recorded Ref names
  an object that exists and opens.

## Contract observations

Neither needs a contract change; both are recorded for the diff review.

- `Sealer.seal` and `Sealer.open` take a scope key but no scope name, so the Sealer
  cannot check that a `BATCH_SCOPED` kind was sealed with the batch key. The store
  checks the scope name against the kind; key-to-scope pairing is enforced by
  `seal_into`, and detected by `open` / `open_from`.
- `Ref.digest` covers the plaintext only, not the kind. The same bytes sealed as two
  kinds get the same digest, and `open` accepts a ciphertext under either kind's Ref.
  The store names objects by digest and kind, and both open to identical bytes, so
  nothing is mixed up; callers must not read meaning into a kind beyond its slot.
