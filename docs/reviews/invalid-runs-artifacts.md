# Artifact replay and compatibility

The committed fixtures retain public outputs copied read-only from the supplied
restore-14 bundles, VM public cards, public rehearsal, and saved public bench runs.
Sources and original SHA256 digests are embedded in the gzip JSON fixtures and
described in tests/factory/fixtures/invalid-runs-provenance.md. No real case archive was
decrypted and no source/restore bundle was changed.

The new tests replay real all-invalid resets (3 trials), a mixed G11 crash (5),
corrected G11 execution (5), valid plain/reference/refuse-all (1 each), a failed
silent window, guard traffic errors (2), verified negative controls and the saved
invalid-probe stdout. The scientific comparison uses the matching four-path
public suffix case metadata. The separate marketplace practice fixture has 64
public files and exercises prototype, retrieval and the supplied S11 patch.

116 public card snapshots cover 54 distinct case identities, including both
restore-14 cards and 56 VM cards. No original card is rewritten. The shared
calibration-validity check identifies exactly one explicit silent wrong result:

- case-20261017T125556Z-18681d: G10 passed and difficulty was hard while strong
  calibration diagnostics recorded two run_error outcomes. Those observations
  now require valid execution before G10/hardness can be established.

Other saved valid scientific outputs retain their old verdicts under differential
replay. The other public cards have unchanged card-level projections. Public cards
without raw trials cannot authenticate their hidden execution; this is not a
claim to have rescored or decrypted every sealed case.

Murphy rows 22, 23, 24, 25, 36, 38, 40 and 41 have real-artifact regression tests
in tests/factory/test_invalid_runs.py. Scanner-adjudication routing is tested by
promoting a real saved scanner suspicion to forbidden severity, then requiring an
independent verdict against the retained valid runtime evidence. The original
report is preserved in the fixture. Row 14 remains open for live qualification of
the 120-second schedule; its invalid-execution retry/feedback path is covered.

No paid calibrator, worker, Boat operation or cloud batch was launched. Fresh
goldfish reviews are the only delegated model work. Test processes use stubs for
provider/worker operations. HTTP tests replay a captured static public source
license, without authorization headers, cookies or session HTML.
