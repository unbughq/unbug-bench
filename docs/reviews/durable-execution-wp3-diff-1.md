# durable-execution WP3 diff review 1

Reviewer: fresh goldfish subagent (general-purpose), read-only, personas zoom_out and
implementation_readiness, Mode: REVIEW. Reviewed `de/wp3` at 14e0934 against
`durable-execution` at db13be8. Verdict: **PASS**. Verbatim below; the resolution follows.

---

# Diff review: WP3 (sealer and artifact store), `de/wp3` 14e0934 against `durable-execution` db13be8

Reviewer: goldfish, personas `zoom_out` and `implementation_readiness`, Mode: REVIEW, standard `implementation-readiness-standard.md`. I read `docs/ENGINEERING.md` sections 1, 2 and 4, the WP3 note, the WP3 brief in `durable-execution-wave1.md`, `factory/durable/contract.py` at db13be8, `factory/r2_upload.py`, `bin/r2-presign` and `batch_holder.r2_publish`.

## Test run

`de/wp3` was already checked out in another worktree (`.claude/worktrees/agent-abd9c2a443e717f1c`). So I made a detached review worktree at 14e0934 in `/tmp/wp3-review`, and removed it afterwards. `age` 1.1.1 was already installed.

`BENCH="$PWD" uv run -q --with numpy --with scipy --with dbos==3.4.0 python -B tests/factory/test_durable_artifacts.py -v`: **26 tests, all OK, 5.7 s.**

I also ran a separate probe script against a local HTTP server (results in finding 1).

## What holds

- **Scope.** The branch writes only `docs/designs/durable-execution-wp3.md`, `factory/durable/artifacts.py` and `tests/factory/test_durable_artifacts.py`. These are exactly the files WP3 owns. The contract and the Murphy register are untouched. No row is claimed closed, which is correct under ENGINEERING section 2.
- **Identity encoding.** It is proven against the real tools, not only against its own encoder:
  - Five real `age-keygen` identities decode, with the checksum constant 1. That makes it Bech32 and not Bech32m, so a Bech32m encoder would fail. They re-encode to the identical string.
  - Each secret's X25519 public key, computed by an RFC 7748 implementation in the test that is checked against the RFC 6.1 vectors, Bech32-encodes to the `# public key:` line `age-keygen` printed.
  - `age-keygen -y` accepts derived identities and prints the independently computed recipient.
  - A `seal` ciphertext decrypts with real `age -d -i <file>`, and a ciphertext from real `age -r` opens with `open`.
- **Identity handling** (`artifacts.py:157-175`):
  - The identity goes through an anonymous pipe (`os.pipe` fds are non-inheritable, and `pass_fds` limits the child to that fd). It is not in argv or the environment, and there is no temp file.
  - age's stderr is dropped and every error is a fixed code.
  - `open` compares the digest with `hmac.compare_digest` (`:153`).
- **Wrong keys and swaps.** A wrong case key, the batch key and a random key all fail with `open_failed`. A valid ciphertext under the wrong Ref fails with `digest_mismatch`. Damaged and truncated ciphertexts fail.
- **Scopes and paths.**
  - `check_scope` (`:194-204`) re-validates the digest and the scope pattern, and pairs each kind with its scope class.
  - `CASE_ID` and `BATCH_ID` are disjoint (`case-` against `b-`) and allow no `/` or `.`, so scopes cannot traverse or collide.
  - `LocalObjects._path` and `R2Objects._call` check every key part again, so a `.tmp-*` name can never be read.
- **Local store write order** (`:279-307`): write, `fsync(fd)`, close, `link` (fails if the name exists), `fsync(dir)`, then unlink the temp name. Data reaches disk before the name exists, so neither a crash nor a power loss can expose a short file under the final name. Tests kill real child processes with SIGKILL at mid-write and before the link.
- **SigV4.** The signer reproduces AWS's published S3 header-auth GET (Range) and PUT examples exactly. The payload sha256 is signed, `Content-Length` is sent, the read-back compares sha256, and `repr` hides the secret.
- **Not reusing `r2_upload.py`** is sound. It runs `curl` against a pre-signed `UNSIGNED-PAYLOAD` link on the VM and never reads back, so it cannot bind the payload hash. `bin/r2-presign` uses query signing, which also cannot. The duplicated key-derivation chain is about 6 lines.
- **Contract observation 2** (the digest does not bind the kind) is harmless:
  - Within one scope, the same bytes get the same digest whatever their kind.
  - A copy of `<d>.A.age` to `<d>.B.age` yields the same plaintext.
  - Anyone able to mint a Ref of any kind already holds the scope key.
  - The only leak is that two artifacts in one scope are byte-identical, which is negligible.

## Findings

**1. NIT: `urllib_transport` follows redirects and forwards the SigV4 `Authorization` header to the new host** (`artifacts.py:375-385`).

My probe confirmed it. A HEAD answered with 302 to another host was re-sent with the same `Authorization` (access key ID plus a request signature valid about 15 minutes), and `exists` returned the redirect target's 404 as `False`. The read-back and `open`'s digest check stop any corruption, and the secret key never leaves memory, so this is not a secrecy break.

The same probe showed urllib adds `Content-Type: application/x-www-form-urlencoded` to every PUT.

Fix:
- build an opener whose redirect handler refuses to follow (`redirect_request` returns `None`), so a 3xx comes back as a status and fails;
- send `Content-Type: application/octet-stream` on PUT.

**2. NIT: R2 `put` is not first-wins under concurrency, despite the claims** (`artifacts.py:427-435`; note line 83; `Objects` docstring at `:229`).

`put` does HEAD, then PUT, then GET, and nothing makes that atomic. With two concurrent puts of the same Ref, the last PUT wins, because age ciphertexts are randomised. The other writer's read-back then differs and raises a spurious `upload_unverified`.

Data is never wrong: both ciphertexts open to identical bytes, and a retry takes the `exists` path. The comment "every object was verified when written" is also not strictly true, for example after a crash between PUT and read-back. Harmless, because a PUT commits atomically.

Fix (either one):
- send `If-None-Match: *` on the PUT, treat 412 as already present, then read back;
- or reword the note and the docstrings to "idempotent; concurrent writers may race, harmlessly".

**3. NIT: the local first-wins test never reaches the code that makes first-wins hold under a race** (`test_durable_artifacts.py:273-282` against `artifacts.py:281-282, 297-299`).

The second put returns at the `path.is_file()` shortcut, so the `os.link` / `FileExistsError` branch, which is what makes concurrent first-wins hold, is never run.

Also, on that shortcut and on the `FileExistsError` path, `put` returns success without fsyncing the directory. A concurrent writer may have linked the name but not yet fsynced it, so after a power loss the object can be gone even though this put "succeeded".

Fix:
- add a test that disables the shortcut (patch `Path.is_file`, or race two real processes) and asserts the first inode survives;
- call `_fsync_dir(path.parent)` before both success returns.

**4. NIT: the fake S3 server does not verify signatures, so the over-HTTP tests do not prove the request on the wire is correctly signed** (`test_durable_artifacts.py:419-421`).

`_signed` checks only a prefix and a substring. The AWS vectors prove `sigv4_headers` in isolation, but not how `_call` puts the request together: the path quoting, the `Host` urllib actually sends, and the header set.

The "interrupted upload never visible" and "altered body refused" properties are behaviour of the fake. The note does disclose that real R2 is untested.

Fix:
- have `S3Handler` rebuild the canonical request from what it actually received (method, raw path, the `SignedHeaders` values) and recompute the signature with the vector-proven `sigv4_headers` and the test secret `sk-secret`; reject on mismatch;
- add "HTTPS / TLS verification via `urllib_transport` is not exercised" to the note's "Not exercised" paragraph (line 156), next to real R2.

**5. NIT: the note overstates how far the store enforces key-to-scope pairing, though the gap is harmless** (note lines 77-79 and 180).

The store never sees a key. It enforces only that the scope *name* fits the kind. Key-to-scope pairing is enforced only by `seal_into`, and workers seal outputs without going through `seal_into`.

An ADMIT worker holds both the case and the batch key (`start_frame`). If it sealed a case-scoped kind with the batch key, the store would accept it under the case scope. Batch-key holders, meaning other cases' ADMIT steps, could then read it, but only if a second bug delivered them the ciphertext. `open_from` on the control side detects the mismatch (`open_failed`).

So observation 1 is accurate and needs no contract change.

Fix:
- reword to "the store checks the scope name against the kind; key-to-scope pairing is enforced by `seal_into` and detected by `open` / `open_from`";
- record, for WP1/WP2, that each worker-output Ref should be verified with `open_from` (scope chosen by `scope_for`) before the engine records it. That would also make the new-batch-service-2 claim ("a recorded Ref names an object that exists") mean "and opens".

**6. NIT: small accuracy and robustness points.**
- **Test descriptions in the note:**
  - The note says "an I/O error during the write" (line 145), but the test injects the error in `fsync`, not `write` (`test:336, 343`).
  - The "killed halfway" fault is a monkeypatched `os.write` in a real child, followed by a real SIGKILL. That is fine, but should be described that way.
- **No timeout:** `AgeSealer._run` calls `subprocess.run` with no timeout (`:165`). A bounded timeout returning `ArtifactError("age_timeout")` would stop a stuck `age` from hanging a step.
- **Leftover temp files:** after a crash, `.tmp-*` files (up to the artifact size, 64 MiB in the test) build up in the local cache with no sweep. One option is to remove `.tmp-*` older than an hour on `_mkdirs`, or to document it as a cache-only leak.

## Verdict

**PASS.** No blocking finding:
- no key, identity, plaintext or credential reaches argv, the environment, disk, an error or a `repr`;
- the identity encoding is proven against real `age-keygen` and `age`;
- the local store's never-visible guarantee holds under the code's fsync and link ordering, and the tests use real kills;
- neither contract observation needs a contract change.

Findings 1-6 are nits. Of these, 1 (redirect handling) and 3 (directory fsync on the success paths) are worth taking before WP1 composes the store.

---

## Resolution (elephant)

The review passed and WP3 merges as reviewed. Nits 1 and 3 (redirects forwarding the
SigV4 header; the directory fsync on the success paths) are taken in a follow-up on
`de/wp3` before WP1 composes the store, together with the cheap nits 2, 5 and 6. That
follow-up gets its own short verification review. Nit 4 (signature checking in the fake
server) is taken in the follow-up if cheap; otherwise the untested HTTPS path is recorded
in the note.
