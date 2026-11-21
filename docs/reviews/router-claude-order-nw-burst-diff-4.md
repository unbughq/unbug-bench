# Diff review 4 (confirm): lane config reload fix d5348ea1..4f4523e5 (goldfish)

Reviewer: fresh general-purpose subagent (zoom_out, implementation_readiness; Mode: REVIEW).

## Verbatim review (condensed only in table formatting)

Fix commit 4f4523e5 passes. The blocking finding from review 3 is fixed: a reload now refuses exactly the files startup refuses and accepts exactly the ones it accepts, and startup itself behaves the same. Six non-blocking nits remain.

Tests (on a `git archive 4f4523e5` copy): test_neuralwatt_routes 16 OK; test_model_router 53 OK; test_router_capacity 10 OK.

**Startup and reload refuse the same files.** Probe (`diff_probe.py`): startup side = `config_lanes`, the `database` check, then `Store.__init__` on a copy of a ledger with $1 booked; reload side = a running Store, an edited file, an RPC, then which log line appears. 67 file variants: the live config with one key changed at a time, plus non-object files (`[]`, `"str"`, `5`, `null`, `{}`) and broken JSON. Accounts: null, a string, an empty string, `[]`, `{}`, a dict, an int, `['bogus']`, a nested list, `true`. `paid_ceiling_usd`: 0, `'0'`, 0.5, `'1'` (equal to booked spending), just under and over $1, false, true, -1, exactly 2^63-1 nanos, 2^63 nanos, 1e30, NaN, Infinity, `'1e2'`, `[]`, `{}`. Lane keys: odd types and edge values. `database`: null and a string. Result: **0 mismatches**. Startup before and after the fix gave the same answer on every variant.
- Odd account types: `config_lanes` (`model_router.py:456`) iterates `config.get('accounts', ACCOUNTS)` the same way `Store.__init__` (481) iterates `tuple(accounts)`.
- Ceiling edge values: both use `_nano(..., ROUND_FLOOR)` with the same `> 2**63 - 1` bound (457, 476).
- Ceiling below spending: `_reload` (520–522) applies `<` against `_paid_counts(...)[0]`, the same test as `Store.__init__` (497–499); the `<=` mutation is caught.
- `production_database` (338): its only file check is the `database` key, repeated by `config_lanes`; `UNBUG_CONTROL_HOME` is the process environment and the symlink check is on the ledger path, so leaving both out of reload is correct.

**Startup unchanged for valid configs.** `main()` (1296) passes validated outputs into `Store`, which runs `lanes()` again; `lanes()` is idempotent on its output. Error order changed (`config_lanes` before `production_database`); both end in the same `SystemExit`. `--reconcile-once` and `--lift-credit` validate what they did before.

**DB ceiling check inside the RPC transaction.** Read only (`SELECT` on the connection holding `BEGIN IMMEDIATE`). Invalid ledger does not crash the RPC: a row with a negative `hold` plus a valid burst edit → `capacity` returned `{'slots': 3}`, logged `router config not reloaded …: ValueError`, `burst_capacities` stayed `{}`; `config_seen` already recorded, so not retried every RPC; startup would also refuse that ledger. Cost: one scan per file change. The `paid_reserve` live re-call hits an unchanged `config_seen`; `_reload` makes no DB writes. `reconcile_forever`, `reconcile`, `lift_credit` never call `rpc`.

**Success log on the first RPC.** No functional problem; nothing parses router stderr. It makes the rollout check ambiguous (NIT 1).

**Mutations:** reload calls `lanes()` only — caught (3); spending check dropped — caught; `<` → `<=` — caught; `accounts` check dropped — caught; `database` check dropped — caught (2); success log dropped — caught; lanes applied before the ceiling check — caught; parse half of the ceiling check dropped — survives, equivalent; `isinstance(dict)` dropped — survives, equivalent; `main()` not calling `config_lanes` — survives, equivalent; `2**63-1` bound dropped from `config_lanes` — **survives** (NIT 2); change key back to `(mtime_ns, size)` — **survives** (NIT 3); `_reload` before `BEGIN IMMEDIATE` — survives, comment only.

**Findings**
- NIT 1 (`model_router.py:513-524`, design `:125-130`): `config_seen` starts `None`, so every router logs `router config reloaded` on its first RPC after a restart; if the wrong file is replaced, the journal still shows a `reloaded` line from the restart. Step 3's `status` check catches it. Skip the log on first load, or say in step 2 to look for a second line after the `mv`.
- NIT 2 (`:457`): the `> 2**63 - 1` ceiling bound has no test (reload would accept `1e30`; startup refuses it in `Store.__init__`). Add a `paid_ceiling_usd: 1e30` subtest.
- NIT 3 (`:513`): the `(mtime_ns, ctime_ns, inode, size)` key has no test; a same-size `mv` with `os.utime` to the old value would pin it.
- NIT 4 (`test_neuralwatt_routes.py:270-274`): the "what startup does" block is loose (`assertRaises(Exception)` around three statements; Store built without lane keys on an empty ledger). Does not weaken the reload-side assertions.
- NIT 5 (`:526`): a refusal from an invalid ledger logs `ValueError`, same as a bad file. Acceptable; `status` fails loudly on the same ledger.
- NIT 6 (`:527-528`): `except OSError` does not cover `ValueError` from `print` on a closed stderr. Unlikely under systemd.

Zoom-out: minimal; one shared function serves `main()` and `_reload`; design text matches the code; rollout path agrees with `neuralwatt-routes.md:443`.

**Verdict: PASS**

## Response (elephant)
- NIT 1: rollout step 2 now says the line also appears on every start, so look for a second one after the `mv`. No code change.
- NITs 2-6: not changed (optional; each is either equivalent, covered by startup, or unlikely).

## Added after review 4: verdict-code repin
`model_router.py` / `model_runtime.py` are in `durable/checkpoints.MODEL_CODE`; `invalid-runs-compat.json` `model.to` is repinned to the new raw digest `a8c991fb…` (from `802bfc8f…`, unchanged), as earlier router releases did, so live cases keep their model-stage receipt folders. Reviewed in diff review 5.
