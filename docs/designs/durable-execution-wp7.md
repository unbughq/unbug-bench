# Durable execution WP7: the key service

Status: design note for WP7 of `docs/designs/durable-execution.md` (wave 1).
Branch `de/wp6-wp7`, cut from `durable-execution` at `db13be8`.
Owns `factory/durable/keys.py` and `tests/factory/test_durable_keys*.py`.

## Problem

Every artifact of a scope (a case, or the batch for INPUTS and the registry) is
encrypted under that scope's 32-byte key (`derive_keys`). The engine on the control
VM needs the key, unattended, every time it starts an attempt or opens an output,
including after a reboot. Today the only key that opens case material lives in the
founder's Mac holder (`key_holder.py`), which expires and needs the founder to
renew it (Murphy row 1). On 2026-10-29 the founder approved a scoped VM restore key
for exactly this (ENGINEERING section 4; `docs/factory-single-path.md`), and stream B
already seals batch case keys to it: its public recipient is
`factory/control-recipient.txt`, beside the founder's `run.FOUNDER_RECIPIENT`
(`r2_upload.case_recipient`, `run_artifacts.py`).

## Change

`factory/durable/keys.py` implements the frozen `KeyService` protocol as
`AgeKeyService(url, *, restore_recipient, founder_recipient, restore_identity)`.

- **Generated once per scope.** The first `scope_key(scope)` makes 32 bytes with
  `secrets.token_bytes`, wraps them, and inserts the wrapped bytes into the engine
  database (table `durable_scope_key(scope PK, wrapped)`, through SQLAlchemy as in
  WP6). If another process inserted the scope first, the primary key refuses the
  second insert, and the service discards its own key and uses the stored one.
  Every caller therefore gets the key that is in storage, never a private copy.
- **Stored only wrapped.** `age -r <restore> -r <founder>` encrypts the key, reading
  it from a pipe and writing the ciphertext to a pipe: the plain key never touches
  disk. The plaintext inside the wrapping is one line,
  `unbug-durable/scope-key/v1 <scope> <base64 key>`, so a wrapped key filed under the
  wrong scope is detected on unwrap.
- **Unwrapped into control-VM memory only.** `age -d -i <restore identity>` reads
  the ciphertext from a pipe and writes the line to a pipe into the engine process.
  The service checks the scope and the length, keeps the key in an in-process dict,
  and returns it. Even a freshly generated key is returned only after it has been
  read back from storage and unwrapped, so a key that cannot be recovered is never
  used to seal anything.
- **The restore identity** is a file path, checked like `key_holder.read_control_identity`
  (regular file, not a symlink, owned by the current user, mode 0600). At
  construction, `age-keygen -y` of that file must equal `restore_recipient`, so a
  wrong identity fails at start-up, not halfway through a batch.
- **Scopes** are a case ID or the batch ID (contract `CASE_ID`, `BATCH_ID`).
- **Nothing is logged.** The service has no logger. Every error is a
  `KeyServiceError` with fixed text plus the scope ID, raised `from None`, with
  `age`'s stderr discarded, so no key, wrapped key or `age` message reaches a log
  or an engine record. `repr` names only the database.
- `wrapped_key(scope)` returns the stored ciphertext (never the key), so WP8 can
  publish it next to the sealed archive (see Findings).
- `recipients_from_repo(root)` reads the two public recipients from the tracked
  files (`factory/control-recipient.txt`; `FOUNDER_RECIPIENT` in `factory/run.py`,
  parsed as `launch.sh` does), for WP1 and WP8.

Proportionate security (ENGINEERING section 4): there is no mlock and no zeroing
ceremony. Keys live as Python bytes in the engine process. WP8's systemd unit
should set `LimitCORE=0`, so a crash dump cannot hold them.

### Seams

- Implements `contract.KeyService`.
- Called by WP1's executor, which passes the keys to `start_frame` and to WP3's
  `Sealer`. For the "no key in any engine record" property to hold end to end, WP1
  must call `scope_key` inside a step body and never pass a key as a DBOS step or
  workflow argument or return it from a step. WP3's `Sealer` must hand the age
  identity to `age` through a pipe, not a file.

### Deployment (WP8, needs the founder; not done here)

Installing the real scoped VM restore identity on the control VM, at the path the
engine's unit passes as `restore_identity`, is a deployment step for WP8 and needs
the founder. This package never reads, creates or installs a real founder or VM
key. Its tests use throwaway identities made by `age-keygen` in a temporary
directory.

## What it deletes

Nothing in wave 1. In WP9 it replaces the Mac holder's role as the only unattended
source of case keys (`key_holder.py`), and the per-case `.casekey` identity that
`r2_upload.case_recipient` keeps in the work tree.

## Tests

`tests/factory/test_durable_keys.py`, with the real `age` and `age-keygen` CLIs and
real SQLite:

- **Restart:** the same scope returns the same 32-byte key from a new service on the
  same database; distinct scopes get distinct keys.
- **Recipients:** the stored wrapped key opens with the throwaway restore identity
  and with the throwaway founder identity (plain `age -d`), and not with an
  unrelated identity.
- **No key in any record, log or exception:** with every logger at DEBUG and
  SQLAlchemy echo on, the test generates keys, then drives each error path (an
  identity that does not match, an unsafe identity file, a wrapped key filed under
  another scope, a corrupted wrapped key, a missing `age`). It scans the captured
  logs, every exception's text and traceback, `repr` of the service, the database
  rows, the raw database file and every file in the work directory for the keys
  and their derived secrets, in raw, hex, base64 and age-identity (Bech32) form.
- **Concurrent first use:** four processes ask for the same new scopes at once; all
  get the same keys and there is one row per scope.
- **Scope checks:** a scope that is neither a case nor a batch ID is refused.

## Murphy rows

WP7 targets row 1 (the Mac holder expires during the batch). This note does not
close it: the row closes when a batch runs on the control VM with the installed VM
identity and no holder (WP8's deployment and WP9's final exam).

## Findings for the elephant

- **The wrapped key must leave the control VM, and the contract has no slot for
  it.** `Sealer` encrypts only to the scope key, so the founder can open a sealed
  archive only with the scope key, which exists only wrapped in the engine
  database. If that database is lost after a key was made and before WP8's nightly
  backup, every artifact of that scope in R2, including a `SEALED_ARCHIVE`, becomes
  unreadable to everyone. `ArtifactStore` cannot hold the wrapped key: there is no
  `ArtifactKind` for it, and a `Ref` is named by a digest under the very key it
  would carry. Not blocking for wave 1: `wrapped_key(scope)` exists so WP8 can
  upload `<scope>.scopekey.age` next to the archive, as `r2_upload` does today for
  `.casekey.age`. Whoever owns publication should decide where it goes.
