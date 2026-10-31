# Stream B: read-only deployment ownership inventory

## Problem

Before deployment, the operator needs to list past launches and money holds on
the control VM without reading secrets or changing state. The report supplies
observations for deciding which old launches still need investigation or cleanup.
It cannot establish historical code provenance, resolve ownership, or authorize
activation. Delayed cleanup and the cumulative USD 5 proof remain blocked on
provider guarantees for how long failed stops can bill and how many workers one
CLI invocation can create (see stream-b-creation-intent.md).

## Change and deletions

Add a standalone standard-library `factory/deployment_inventory.py` command with
required `--control-home` and `--root`. It reads only local metadata and the
existing version-1 <control-home>/boat-reservations.json. It never starts controllers, invokes
providers, changes files, acquires controller locks, or grants admission. Output
is JSON on stdout. No deployment integration or new persisted state. Delete no
runtime path; replace ad-hoc filename/hold inspection with one reproducible report.

For each directory under control-home/launches, report a public launch identifier
only when it matches `[0-9a-f]{32}`. Symlinked and non-directory entries are
invalid even when their names match. Otherwise report an
invalid-entry count without printing names. Report presence/type, size and mtime_ns
of only launch.json, controller.lock, monitor.sh, ids, complete, spend-finished
and cleanup-status.json, plus numeric
new.N and new.N.pending names. Never read their contents (argv, environment,
provider output and monitor scripts may contain sensitive material). Report
unknown entry counts, not names or contents. Count names matching
`[A-Za-z0-9_-]+\.deleted` by type without printing worker names. These markers
are unverified observations, not deletion receipts. Unknown entries include
restore-casekey.age, restore-input*.age, founder-ruling.json, initial.accounts.json
and *.admission-*; keep these unnamed and unread. Do not follow symlinks.

Report creation evidence per serial (string of ASCII digits, preserving leading
zeros), plus counts per label. Presence here includes any lstat-observed type;
a symlink/directory is unsupported but still counts as present in this table:

| response new.N | marker new.N.pending | label |
| --- | --- | --- |
| absent | present | intent-only |
| present | present | response-and-intent |
| present | absent | response-without-marker |

When neither exists, omit that serial; an empty creation array means none observed.
Response-without-marker includes both legacy records and normally resolved new
creations; the scan cannot distinguish them. No label proves provider submission
or non-submission. A complete marker is not verified deletion evidence. Never
call any launch resolved or safe to activate.
No lock availability claim: the scan is non-atomic and owners may be active.

Ledger output contains counts by known status (reserved, finished,
reconciled_expired), sum of finite nonnegative USD for status == reserved only as a decimal string,
and counts of expired reserved holds, malformed records and unknown statuses.
Do not print ledger keys (arbitrary spend paths), raw values or exceptions.
Missing ledger is distinct from empty ledger; unreadable/malformed/version mismatch
is reported as invalid and totals are null. An invalid entry makes the total null,
never a partial sum. Expiry is informational, never releases a hold. Historical
reconciled_expired remains an explicit review prerequisite even with no workers.
Ledger is read with a bounded size (8 MiB); fail closed on oversized data.

Report current deployed SHA256 hashes for a fixed source allowlist:
factory/control_resume.py, factory/launch.sh, bin/boat-launch-guards.sh,
bin/boat-spend. These hashes describe present code, not provenance of a historical
launch. Source entries must be regular files without symlink path components;
otherwise report unsupported. Bound source reads to 8 MiB each. Root and
control-home must be real directories with no symlink components; refuse bad
roots with generic errors. Descendant symlink directories are never traversed.
Use lstat and O_NOFOLLOW/fstat for files, and report changed/unsupported observations
rather than claiming a consistent snapshot. The supported use is a quiesced,
trusted control filesystem, not an adversarial concurrent filesystem.

Always include `activation_authorized: false`, `snapshot_atomic: false`, UTC
observation time, and explicit outstanding proofs: historical provenance,
controller ownership, provider creation/deletion, cumulative cost. No live VM
inspection is claimed by an offline report. CLI exits nonzero on scan errors;
known pending/legacy holds are findings, not read errors. Never include arbitrary
exception text or input paths in errors.

## Output contract

Schema 1, with fixed top-level keys illustrated below. Example is an empty control
home with absent source files (the sources map always includes all four names):

```json
{
  "schema": 1,
  "observed_at": "2026-10-31T13:00:00+00:00",
  "activation_authorized": false,
  "snapshot_atomic": false,
  "outstanding_proofs": ["historical-provenance", "controller-ownership", "provider-creation-deletion", "cumulative-cost"],
  "launches": {"state": "missing", "invalid_entries": 0, "items": []},
  "ledger": {"state": "missing", "counts": {"reserved": 0, "finished": 0, "reconciled_expired": 0}, "reserved_usd": null, "expired_reserved": 0, "malformed_records": 0, "unknown_statuses": 0},
  "sources": {
    "factory/control_resume.py": {"state": "missing"},
    "factory/launch.sh": {"state": "missing"},
    "bin/boat-launch-guards.sh": {"state": "missing"},
    "bin/boat-spend": {"state": "missing"}
  },
  "errors": []
}
```

Each launches.items object has id, state (ok or error), files (the seven fixed
names mapped to metadata), creations (objects with serial, label, response and
intent metadata), creation_counts (all three labels, zero included),
deleted_markers (counts for file, directory, symlink, other), and unknown_entries.
Metadata is {state: missing}, {state: error}, or {state: present, type:
file/directory/symlink/other, size: integer, mtime_ns: integer}. No symlink targets.
Non-regular allowlisted files count as unsupported scan errors. Unreadable entries
make their containing scan error. launches.state is missing/ok/error. Invalid
launch entries increment invalid_entries and make the scan error, without naming
them. Missing paths are observations, not scan errors.

sources values are {state: ok, sha256: hex} or {state: missing/unsupported/changed/error}.
Read stability compares dev, inode, size, mtime_ns and ctime_ns before/after and
against the named file after reading. Any mismatch gives changed. Oversize and
nonregular sources give unsupported; read failures give error. Parent symlinks
are unsupported. No hashes are returned for failed reads.

ledger.state is missing/ok/invalid. Empty reservations gives ok and reserved_usd
"0". Any read/schema/entry error gives invalid and reserved_usd null. Unknown
statuses increment unknown_statuses; invalid record shape, amount or expiry
increments malformed_records (once per record); either invalidates the ledger.
Known status counts include malformed records whose status is recognized.
All records require finite nonnegative usd and expires_at. Reject bools and
non-string/non-number values. Parse decimal exactly (JSON floats as Decimal);
allow at most 32 significant digits and decimal exponent between -18 and 18,
and use local precision of 64 plus ledger-size digits with an Inexact trap;
any rounded addition invalidates the ledger instead of returning a partial sum.
This also bounds exponent expansion. Expired reserved means valid reserved record
with expires_at strictly less than observation UTC epoch; equality is not expired.
Reject duplicate JSON keys and nonstandard NaN/Infinity JSON tokens. Missing or
non-object reservations and version other than integer 1 are invalid.

errors is a sorted unique list drawn only from: invalid-root, launch-scan-error,
ledger-invalid, source-scan-error. Invalid root yields the same envelope with
launches.state error, ledger.state invalid, sources empty, and invalid-root.
No input paths or arbitrary exception text on stdout/stderr. CLI accepts exactly
one --root and --control-home; invalid usage emits {"error":"invalid-arguments"}
and no parser echo of arguments. Exit 0 means observations completed (even if
missing files/holds/pending records exist), 1 means errors is nonempty, 2 means
invalid arguments. These exit codes never indicate activation readiness.

## Tests

Add tests/factory/test_deployment_inventory.py. Resolve temporary directory
roots with Path(tempfile.mkdtemp()).resolve() for macOS /var symlinks.
Use the saved isolation-timeouts launch.json and created.json and the retained
stream-b-preparation-preflight-20261031.json to reconstruct the observed legacy
layout with only launch.json and controller.lock, using the recorded launch ID.
Separately build a guard layout including ids, deletion/spend/cleanup markers and
all three creation states. These extra envelopes and timing are authored.
Layout reconstruction and ledger examples are authored, not live proof.
Exercise missing/empty ledger, expired reserved and historical released holds,
unknown statuses, invalid/negative/nonfinite amounts, malformed/oversize files,
symlink refusal, hidden unknown filenames and poison secret strings in all
unread launch files and ledger keys/unknown fields. Assert no output contains
them. Hash current real guard sources; verify full directory bytes and mtimes
are unchanged by scans, including repeated fresh CLI processes. Cover markerless
response, pending intent, complete presence and generic read failures. Full suite:
`uv run --with numpy --with scipy python -B tests/run.py`, unique committed log
and result record, then fresh diff review. No workers or paid calls.

## Acceptance, cost and rows

One offline design/review/implementation/suite cycle. No incremental infrastructure
or factory-model spend. No Murphy row closes: the real migrated-store, ownership,
cleanup and launch/deletion proofs remain outstanding. This is an inventory tool,
not a substitute for fresh read-only VM evidence and historical provenance.

Rows 6, 27, 28, 35 and 51 and new-batch-service-1 through -4 remain open;
this inventory supplies observations only, and changes no register status.
Remaining work and spend policy: docs/reports/stream-b-remaining-20261031.md.

## Accepted round-2 clarifications

Count parked_markers and keep_markers by type like deleted_markers; a parked
worker may still run and bill. Nonregular numeric creation files also make the
item state error. Sort launch items by ID and creations by serial string (01 and
1 remain distinct). Render reserved_usd with format(total, 'f'), preserving
trailing zeros from decimal addition. Invalid ledgers retain counts computable
from parsed records; envelope/read errors leave all counts zero. CLI argument
errors go to stdout, with stderr empty. Operators pass canonical paths (realpath);
tests resolve their temporary roots. Saved created.json supplies new.N bytes in
the guard layout only. Parked and keep markers are covered in that layout.

## Full-suite integration finding

Added after design review 2; independently covered by diff review 1.

The existing worker manifest includes all factory/*.py, including this standalone
scanner. Add deployment_inventory.py to tests/tools/test_launch_manifest.py's
independent inventory; do not change bundling rules or factory/batch.py. Shipping
the inert scanner adds no invocation or state. The first full suite found this
missing expected-inventory entry (158/159 scripts passed); retain its failed
record, update the inventory, and rerun the complete suite before diff review.
This is an offline test integration failure, not a new observed live incident.

## Non-blocking diff-review follow-ups

Diff review 1 passed and found a representable-range precision edge: about 1e53
USD spread over 20,000 records could round away a 1e-18 hold. Trap Inexact and
return invalid/null, covered by a regression below the ledger size cap. Add the
explicit complete-file assertion and metadata permission-error probe requested
by the same review. Optional stricter decimal-string spelling is deferred; no
secrecy or admission change. Rerun the full suite after these changes.
