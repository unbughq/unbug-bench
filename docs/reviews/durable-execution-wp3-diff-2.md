# durable-execution WP3 diff review 2 (follow-up verification)

Reviewer: fresh goldfish subagent (general-purpose), read-only, persona
implementation_readiness, Mode: REVIEW. Narrow verification of `git diff cca6292 9803db3`
(the follow-up taking review 1's nits). Verdict: **PASS**. Verbatim below.

---

# WP3 follow-up verification review: `git diff cca6292 9803db3`

Reviewer: goldfish, `implementation_readiness`, Mode: REVIEW, read-only.

## Test run

I ran it in a detached worktree at `/tmp/wp3-review2`, which I removed afterwards. `BENCH="$PWD" uv run -q --with numpy --with scipy --with dbos==3.4.0 python -B tests/factory/test_durable_artifacts.py`: **32 tests, all OK, 11.2 s.** That is 26 before plus 6 new.

## Per-nit status

1. **Nit 1 (redirects): done.**
   - `_NoRedirect.redirect_request` returns `None`. A 3xx then reaches the default error handler, which raises `HTTPError`, and `urllib_transport` turns that into a returned status.
   - `build_opener` keeps the default proxy and HTTPS handlers, the same ones `urlopen` used.
   - On PUT, `Content-Type: application/octet-stream` is set and signed. It also stops urllib adding its form content type, and the test checks the header that was sent.
   - `test_a_redirect_is_never_followed` asserts the fixed codes and `other.requests == []`, so no `Authorization` header goes to the second host.
2. **Nit 2 (concurrent PUT): done.**
   - `If-None-Match: *` is signed on PUT. A 412 leads to a GET and an age-header check, and the existing object is kept.
   - The `Objects` docstring and the note now say "idempotent", and the note says R2 support for the header is unverified live.
   - `test_a_concurrent_writer_keeps_the_first_object` exercises this path.
3. **Nit 3 (lost race): done.**
   - The `is_file` shortcut now calls `_fsync_dir` (inside the `try`, so an OSError becomes `store_failed`). The `FileExistsError` path still reaches `_fsync_dir`.
   - The new test hides the shortcut and reaches `os.link`, which hits `FileExistsError`. It asserts the first inode and bytes are kept, the temp file is removed, and the directory is fsynced on both paths.
4. **Nit 4 (signature checking in the fake server): done.**
   - `S3Handler._signed` rebuilds the canonical request from what it received and recomputes the signature with `sigv4_headers` and `sk-secret`. It checks the credential date and region, that the signed headers are present, and that the body hash matches. It uses `compare_digest`.
   - All PUT, GET and HEAD requests go through it, and the wrong-secret test fails with `store_unavailable`.
   - The note lists HTTPS / TLS verification as not exercised.
5. **Nit 5 (note on scope pairing): done.**
   - The note now says the store checks the scope name, and that pairing is enforced by `seal_into` and detected by `open` / `open_from`.
   - It records the WP1/WP2 rule to verify each worker-output Ref with `open_from`, and says "exists and opens".
6. **Nit 6 (accuracy and robustness): done.**
   - The note names the monkeypatched `os.write` / `os.link` followed by a real SIGKILL, and the injected `fsync` failure.
   - `timeout_s` defaults to 600, and `TimeoutExpired` becomes `ArtifactError("age_timeout")` with `from None`.
   - `subprocess.run` kills and reaps the child, and the parent closes `read_end` in its `finally`. The identity is written and `write_end` closed before the child starts, so after a timeout no process holds the pipe. Native X25519 identities spawn no plugin, so there is no grandchild.
   - The `.tmp-*` leak is documented in the `LocalObjects` docstring and the note.

## Secrecy check

Nothing new reaches argv, the environment, disk, logs, exception text or `repr`:
- All new errors are fixed codes raised with `from None`.
- The redirect path returns `{}` headers and an empty body, and never re-sends a request.
- The new signed headers are constants.
- The 412 path does a GET to the same host only.

## New findings

- **NIT: on a 412, the store accepts any object that starts with the age header** (`factory/durable/artifacts.py:449-453`).
  - `R2Objects` has no key, so it cannot check that the object is a valid age ciphertext for that Ref. It checks only `AGE_HEADER`, which is what the resolution says.
  - This is no weaker than the existing `exists()` shortcut at `:445`, which accepts an existing object with no check at all.
  - A wrong object is still caught when it is read: `open` / `open_from` fail with `open_failed` or `digest_mismatch`. The WP1/WP2 rule from nit 5, to verify each worker output with `open_from` before recording it, covers this too.
  - No change is needed. Optionally, the 412 comment could say "age-shaped, verified on open" so nobody reads it as a Ref check.

No BLOCKING findings.

## Verdict

**PASS.**

---

## Resolution (elephant)

Passed. The one NIT needs no change. The rule that WP1 and WP2 verify each worker
output with `open_from` before recording it covers it.
