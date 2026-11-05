# Durable execution WP3: sealer and artifact store

Status: draft, for diff review. Package WP3 of `docs/designs/durable-execution.md`
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
that a batch-scoped kind used the batch key. The store and `seal_into` enforce the
pairing instead, and opening under the wrong scope's key fails.

### Object layout

Both backends store one immutable object per (scope, Ref):

```
<prefix>/<scope>/<digest>.<kind>.age
```

`<digest>.<kind>.age` is the same name the wire layout uses for blobs
(`attempt_paths`). Objects are never overwritten with different content in a way a
reader can observe half of: a put of an existing object is a no-op (first wins).

### ArtifactStore (`SealedStore`) over two object backends

`SealedStore(objects, prefix="durable")` implements `put_sealed`, `get_sealed` and
`exists` over a small byte-object interface (`put`, `get`, `exists`). It checks the
scope and that the ciphertext looks like an age file (`age-encryption.org/v1`
header), so it cannot be handed plaintext by mistake. It never takes a key.

- **`LocalObjects(root)`** (tests, offline, and a control-VM cache): writes into a
  temporary file in the target directory, `fsync`s it, then `os.link`s it to the
  final name and `fsync`s the directory. `link` fails if the name exists, so the
  first complete object wins and is never replaced. A crash or exception at any
  point leaves at most a `.tmp-*` file, which no read ever looks at. Directories
  are `0700`, files `0600`.
- **`R2Objects(account, access_key, secret_key, bucket)`**: S3 API calls signed with
  SigV4 in the `Authorization` header (the same algorithm as `bin/r2-presign`, which
  this reuses for the signing-key derivation). A PUT signs the payload's sha256 in
  `x-amz-content-sha256` and sends `Content-Length`, so the object store rejects
  any body that is truncated or altered in transit instead of storing it; S3-style
  stores commit a PUT only when the whole body arrived. After the PUT the backend
  GETs the object back and compares sha256 (as `batch_holder.r2_publish` does),
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
  an independent RFC 7748 implementation in the test (checked against the RFC's own
  vector) computes from the derived secret.
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
- **Interrupted upload, local.** A real child process is killed with SIGKILL
  halfway through writing a 64 MiB ciphertext: nothing is visible under the final
  name, `exists` is false, `get_sealed` raises missing, and a later put succeeds.
  An exception mid-write also leaves nothing visible and no temporary file.
- **First wins.** A second put of the same Ref does not replace the first object.
- **R2 signing.** The SigV4 header signer reproduces AWS's published S3 examples
  (GET object with Range, PUT object) exactly.
- **R2 logic over real HTTP.** `R2Objects` talks over real sockets to a local
  S3-like server in the test that commits a PUT only when the whole body arrived
  and its sha256 matches `x-amz-content-sha256`. A client that disconnects halfway
  through the body leaves nothing visible; a body altered in transit is rejected;
  a read-back mismatch fails the put; HEAD on a missing object is false.

Not exercised: real Cloudflare R2. No R2 credentials exist in this sandbox. The
first live run of `R2Objects` must confirm that R2 enforces `x-amz-content-sha256`
on PUT, as its S3 compatibility documentation states.

## Murphy rows

WP3 targets 27, 34 and `new-batch-service-2`. This package provides the parts of
each that live in the store; none closes in WP3, because each needs the engine to
use the store on a real run (WP1, then WP9's final exam):

- **27 (mixed generations).** Objects are immutable and content-addressed, and the
  engine records which Refs make a result, so there is no mutable directory to
  replace half of.
- **34 (optional, mutable, unverified checkpoints).** Snapshot objects are
  immutable per Ref, and `put_sealed` returns only after a verified read-back.
- **new-batch-service-2 (card names an absent archive).** A `Ref` is returned to
  the engine only after the object is stored and verified, so a recorded Ref names
  an object that exists.
