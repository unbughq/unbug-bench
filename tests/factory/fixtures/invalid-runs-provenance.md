# Invalid-run regression artifacts

All files are public artifacts copied read-only. No encrypted archive was opened.

`invalid-runs-real.json.gz` embeds source paths, file SHA256 hashes and saved JSON
for reset-invalid (3 trials), G11 mixed (5), plain/reference/refuse-all (1 each),
invalid silent-window (1 summary), guard traffic error (2 trials), and saved
negative-control reports including a genuine invalid-probe stdout log. Records
are original public-practice output, not produced by the implementation under test.

`invalid-runs-practice.json.gz` contains 64 files from the explicit public-practice
rehearsal, with per-file hashes and its source path. The adjacent S11 patch is
copied verbatim from the supplied later-release patch and applies only to a
scratch copy; the source rehearsal and restore bundles remain untouched.

`invalid-runs-public-cards.json.gz` contains both restore-14 public cards and
56 VM public cards read via the specified read-only SSH identity and known-host
configuration on 2026-10-29. Offline tests require no SSH. The earlier committed
20261029-real-public-cards.json.gz corpus contains another 58 source-card snapshots.
Public cards cannot prove hidden raw runs; compatibility claims distinguish that
limit from raw saved-output replays. No verdict file is rewritten.

`invalid-runs-http.json.gz` is a public HTTP 200 response fetched on 2026-10-29
from the Medusa source repository named by the practice freshness log. It is the static public license, without anonymous session/CSRF HTML. It includes requested/final URL, UTC
time, exact response body and SHA256, without cookies or authorization headers.
It is replayed through the trusted retrieval adapter's HTTP transport seam.
