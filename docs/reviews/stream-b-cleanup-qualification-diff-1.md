**Verdict: PASS.** No blockers are open. I found four optional nits.

Scope: a read-only goldfish diff review of `839a096..HEAD` (97fedd1, 3de339d) in worktree `t3-ded79ec5`, `Mode: REVIEW`. I checked it against `docs/designs/stream-b-cleanup-qualification.md` revision 2 and design reviews 1 and 2, using the `zoom_out` and `implementation_readiness` personas with `implementation-readiness-standard.md` and `docs/ENGINEERING.md`. I made no writes, VM commands, network or paid calls, and I created no workers or delegates. My only local commands were git, sha256 and JSON reads.

## Design compliance

**Output contract.** Every path in the design exists. The report has no `contracts/<basename>.md` files, which is correct because all nine pages are unchanged. Under `observations.json` I compared each key with the probe's emitter and the test's validator:
- The top-level keys, `units`, `unit_file_sha256`, `locks`, `legacy.{metadata,launch,git}`, `fleet`, `cli` and `errors` all match the closed sets in the design.
- The probe's hard-coded environment tuple equals `control_resume.ENVIRONMENT` minus `UNBUG_CLOUD`/`BOAT_TYPE` (`factory/control_resume.py:13-15`). The test asserts this.
- The legacy labels use the full ID `b275ffccd6134a33833853ad1d31ed16`, as review 2's N1 asked.

**Probe behaviour.** `probe.py` matches design items 1–4:
- It embeds the scanner source and runs it in memory. The embedded source's sha256 is `cdfc92fc…3f48`, which equals the current `factory/deployment_inventory.py` (last changed in ad11720), so the scanner is unchanged.
- It captures command output in temporary files, not pipes. Failures become fixed labels, and no stderr or exception text is emitted.
- Lock checks are gated on all five units being `inactive`. Each lock file is opened `O_RDONLY|O_NOFOLLOW` with no `O_CREAT`, locked `LOCK_EX|LOCK_NB` and released at once.
- `launch.json` is reduced to enums and presence bits. The git calls are `rev-parse HEAD` and `log -g -100 --format=%H%x09%cI`, which do not read the index.
- The fleet listing uses `bin/boat-call list --json` with `BOAT_COMMAND_TIMEOUT_SECONDS=30` and `BOAT_NO_UPDATE=1`. Only validated IDs and `hasMore` are kept.
- The CLI check reads magic bytes, hashes the binary and runs `--version` with `BOAT_NO_UPDATE=1`.
- The probe makes no create, delete or resume call, and reads no secret file.

**Hygiene.** The retained JSON holds no paths beyond the four public source labels, no `@`, and no token- or key-shaped strings. The suite log has only PASS test names.

## Report claims against the evidence

**Evidence hashes.** These match the recomputed values:

| File | sha256 |
|---|---|
| `probe.py` | `4d2017d8…67e2` |
| `observations.json` | `0c86a196…a1` |
| `contracts/sources.json` | `d792fa5a…ad0` |
| suite log (gz) | `0eb23b60…3f50` |
| suite log (uncompressed) | `884896d8…e9c` |

**Units and locks.**
- All five units are `inactive`.
- The holder and the resume timer and service are `disabled`, and their unit-file hashes are present.
- Router and batch are `not-found`, with null hashes.
- All six scanner-listed locks are `free`.

**Fleet and CLI.**
- The Boat listing is readable, the page is complete, and there are no workers. The report correctly says this neither proves non-creation nor replaces deletion receipts.
- The CLI is 1.0.87, an ELF binary, sha256 `663483ab…cda`. The report discloses the difference from 1.0.85 and makes no multiplicity claim.

**b275.**
- The only entries are `launch.json` and `controller.lock`. Unknown entries are 0, there are no creations, and every marker count is 0.
- Its launch settings are cloud `boat`, type `default` and argv `launch`, with `BOAT_CMD` absent.
- The other five launches each have one creation response with no marker, plus `complete`, `spend-finished` and one deleted marker. The report correctly calls these not requalified.

**Legacy provenance check.**
- **Timestamps:** b275's `launch.json` mtime is 2026-10-23T22:06:08Z. The source ctimes are 2026-10-24T11:33Z and their mtimes 11:15Z. So `ctime_before_launch=false` for all four sources, which is correct.
- **Directory consistency:** the directory's mtime and ctime equal `launch.json`'s, so `directory_timestamp_consistent=true`. The report correctly calls this consistent but unable to prove history.
- **Git:** both queries failed (`command-failed`, head null, empty reflog), and the report gives no reason. The run's only error label comes from this.
- **Blob matches:** I recomputed them independently:
  - guards and spend match blobs `f1bab0c` and `2597e40` (in 4936347);
  - `control_resume` matches `cdd08ea` (in cfe4ad8);
  - `launch.sh` matches nothing across all 1,193 path commits.
- **Result:** `execution_binding=false`, `intact_history=false` and `verdict=unresolved` follow from the design rule, and nothing synthesises a disposition. This unresolved finding is justified.

**Contracts.** All nine URLs and old files match the two prior `sources.json` lists, with the old hash equal to the new one. I checked each verdict row against the retained pages:
- **type-rate:** `pricing.md` lines 19–22 and 78 give $0.018 / $0.036 / $0.072 / $0.200. Satisfied, with narrow scope, is correct.
- **start-charge:** `limits.md` lines 30–36 give $0.07 as the top extra-start price, with anything beyond failing. Satisfied, with narrow scope, is correct.
- **egress-charge:** `pricing.md` line 48 says "boat does not bill egress". Satisfied is correct.
- **storage-charge and proxy-charge:** `pricing.md` lines 47, 79 and 84 show saved snapshots at $0.056 per day and the AI proxy at $1 per day plus requests, both charging while stopped. Unresolved pending workload evidence is correct.
- **creation-count, exceptional-billable-seconds and cumulative-ledger:** unresolved. The cited reasons match design review 1 and the retained pages.
- **Cost bounds:** refusing to invent cleanup cost bounds and building no supervisor or ledger is consistent with the design scope and the prior reviews. Zoom-out finds no YAGNI or new-path concerns.

**Murphy rows, gates and remaining work.** No Murphy row is closed or edited. The activation and diagnosis gates are unchanged, and there are no production runtime changes (the diff is only docs, evidence and one test). The cleanup supervisor and cumulative ledger are stated as incomplete, and existing VM costs are stated as not zero.

## Tests and suite

`tests/factory/test_cleanup_qualification_evidence.py` validates the real retained output:
- full scanner schema-1 recursion;
- extra-key injection at every object path;
- arbitrary enum, ID and hash values, and a malformed worker ID;
- provenance timestamp logic recomputed from the observations;
- hashes of the nine contract files.

It proves hygiene only, as the design says.

The suite ran at 97fedd1: 162 scripts, 0 failed, exit 0, and the log includes this test at line 359. 3de339d adds only the suite JSON, the log and six lines in the report, so the suite result applies to HEAD's code and tests.

## Nits (optional)

- **N1** (`provenance.json` and the report's "initial 4936347 commit"): `matches` records one commit per blob, but blob `2597e40` appears in 605 of the `bin/boat-spend` commits I checked, and local history starts at 0af039b (2026-10-20). Say "earliest matching commit", or record that only the first match is kept.
- **N2** (report, egress-charge row): "explicitly includes network egress" can be read as billed. Quote the source: "Included at no cost … boat does not bill egress".
- **N3** (test): nothing asserts that `scanner_sha256` equals `sha256(factory/deployment_inventory.py)`. It does today (`cdfc92fc…`). A one-line assertion would pin the "unchanged scanner" claim.
- **N4** (report): the 150-second overall SSH bound and the SSH options are outside the payload, so no retained artifact records them. Either record the exact local invocation or say it is not retained.

The increment may close as an evidence-only refusal report. The Murphy rows, the cleanup supervisor, the cumulative ledger and the legacy disposition all stay open.

## Elephant response

Accepted PASS, no blockers. N1: clarified that matches retain one representative
commit per matching blob, not the repository's initial commit. N2: clarified
that Boat does not bill network egress. N4: recorded the exact local invocation
and 150-second subprocess bound as execution documentation. N3 deferred: the
embedded scanner remains an immutable historical probe; its source/hash identity
was independently checked in this review, while later scanner edits should not
invalidate this retained observation. No source/test changed after the suite.
No Murphy closure or cleanup/deployment activation is claimed.
