**Verdict: PASS.** No blockers are open. I found three optional nits.

Scope: a read-only goldfish design review of `docs/designs/stream-b-cleanup-qualification.md` revision 2 (uncommitted, base 839a096). I checked it against `docs/ENGINEERING.md` and `docs/reviews/stream-b-cleanup-qualification-design-1.md`, using the `zoom_out`, `design_critic` and `implementation_readiness` personas with the Heilmeier and implementation-readiness standards. I ran nothing on the VM, made no network or paid calls and wrote nothing.

## Review 1 findings

**B1 (output contract) is resolved.**
- **Paths:** fixed, at lines 114–117.
- **`observations.json` keys:** every key has a closed set of allowed values, at lines 134–174.
- **Error labels:** a closed list, at lines 172–174.
- **`provenance.json` and `contracts/sources.json`:** both schemas are given, at lines 176–187.
- **`report.md`:** has one row for each of the ten named questions. Each row gives its evidence, acceptance condition and missing evidence, at lines 189–196.
- **Validator test:** the path is named, and it covers extra keys, arbitrary enum strings and malformed IDs. Line 121 correctly says it proves output hygiene, not runtime qualification.
- **References checked against the code:**
  - the four `SOURCES` paths match `factory/deployment_inventory.py:13-14`;
  - `control_resume.ENVIRONMENT` exists at `factory/control_resume.py:13`;
  - the nine URLs match the two retained `sources.json` files.

**B2 (legacy evidence and decision rule) is resolved, and the strengthening is correct.**
- **Evidence collected:**
  - lstat `mtime_ns`, `ctime_ns` and `btime_ns` for the four sources and the three b275 labels;
  - read-only git HEAD and reflog;
  - the staged-release manifest hash;
  - the launch enums and presence bits, which replace the raw `launch.json` hash.
- **Rule:** blob match, source ctime before `launch.json` mtime, and directory timestamps no later than the latest child (zero tolerance). Missing metadata fails.
- **Why timestamps are only necessary:** the design treats these timestamps as necessary but not sufficient, and that is sound. Deleting an entry updates the directory's mtime. A later write to an existing child then raises that child's timestamps above the directory's. So clause (c) still holds after a deletion, and timestamp consistency cannot prove the directory history is intact.
- **What a positive verdict needs:** `execution_binding` and `intact_history` must both be true, each backed by a cited retained record. Git HEAD, the reflog and the manifest count only as candidate evidence. This is stricter than review 1's rule, and no implementer decision is left open: both flags default to false, so with no record the verdict is `unresolved`.
- **Expected outcome:** probably `unresolved`. The scope (lines 15–19 and 109–110) allows that and claims no cleanup work.
- **Cloud identity:** an absent cloud, `other`, or a present `BOAT_CMD` keeps provider identity unresolved. A known `hetzner` value makes the Boat evidence not apply, and no Hetzner query is made. Both are correct.

**M1 (lock probe) is resolved.** The lock is tried only after all five units are seen inactive. The file is opened `O_RDONLY|O_NOFOLLOW` without `O_CREAT` and released at once. The remaining race with a manual operator is stated, at lines 31–38.

**M2 (CLI multiplicity) is resolved.** The probe hashes the executable and reads its magic bytes. A binary allows no multiplicity claim. Readable source needs a review of its request and retry code, and help or version output never proves multiplicity, at lines 44–47 and 169–171.

**M3 (Heilmeier gaps) is resolved.** There is a plain objective at lines 7–9, a per-question exam in the `report.md` table, and the exact host, identity and known-hosts paths at lines 123–125.

**M4 (contract re-check) is resolved.** Exactly the nine URLs are re-fetched, unauthenticated, with hash comparison. Changed pages are kept verbatim, and a new URL is allowed only when an unresolved row names it, at lines 64–68.

**N1 and N2 are resolved.** The list uses the existing `bin/boat-call list --json` path with the VM's credential used implicitly. The base-merge sentence has been removed from the problem statement.

## Heilmeier and readiness checks

- **Heilmeier:** objective, current practice, approach, impact (B3 deployment approval consumes this report), risks, cost (the existing VM only, with zero workers and zero model calls), timeline (one cycle, with external blockers allowed) and exams are all present.
- **Readiness:** each artifact and field is fixed, the suite command is named, and the review records are named. The implementer has no design choices left.
- **YAGNI:** there is no new launch path, no dormant supervisor and no change to the scanner. That is proportionate.
- **Murphy rows:** they stay open, which is correct for an evidence-only increment.

## Nits (optional)

- **N1:** Name b275 by its full 32-hex launch ID in the `legacy.metadata` labels (line 151), so the probe cannot pick the wrong launch from a prefix.
- **N2:** Line 180 uses `verdict: unresolved|satisfied`, while review 1 used `provenance-qualified`. Use one term in `provenance.json` and the report's `legacy-provenance` row.
- **N3:** Line 119 has a stray leading space before `tests/factory/...`.

The probe may now run on the VM as designed. Diff review then checks the report's claims against the sanitized observations and the public contracts.

## Elephant response

Accepted PASS. Use satisfied consistently; full legacy ID is fixed in the probe.
No runtime qualification or Murphy closure is inferred from this design pass.
