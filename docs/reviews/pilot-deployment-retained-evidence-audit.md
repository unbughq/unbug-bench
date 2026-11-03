PASS — the retained compatible release criterion in accepted B2 is now satisfied for offline dispatch replay.

Independently verified without `batch.verify`:

- All six production release files exactly match the original deployment package.
- Release/provenance digests match the pinned record `7bcbbd3d…`.
- All 831 public payload files and 57 host files match Git objects at `8a5c38fea414fe56e4152e58a53e65d4a457e811`; current host bytes also match.
- The source tar has exactly the manifest’s unique regular files, with matching hashes; manifest completeness matches the full Git tree and documented exclusions.
- The declared deployment checkout is clean at that commit.
- The independently recomputed code fingerprint matches the retained policy.
- Policy differences from the original practice policy are exactly `batch.release`, `batch.sha256`, and `code_sha256`. The practice manifest is unchanged and correctly pinned.

`test_preflight.py` now loads this retained package and policy, uses real verification and dispatch, and changes only release location and throwaway recipient during setup. It neither builds a release nor recalculates its pins. This supplies an independently frozen deployment artifact rather than the former test-generated fixture.

Limits: I inspected the replay implementation but did not rerun the reported 28 passing tests. This establishes offline evidence only; it does not establish deployment, founder unlock, live qualification, or Murphy closure. The historical round-2 FAIL remains a historical record. No files were edited.

## Parent disposition

PASS accepted. Root separately observed 28/28 preflight regression tests pass using this retained release. Accepted B2 evidence finding is resolved; the original round-two verdict remains verbatim/historical. No third preflight implementation review or new Murphy closure.
