# Provider waits policy diff review 3

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed WP1 at `b5babec`. Verbatim response:

---

**BLOCKED:** Both test-evidence gaps remain at `b5babec`.

- The second card can be read before attempt 2 finishes; the later action timestamp does not establish when the card was observed.
- The restart test does not establish that recovered execution reaches the credential sleep before its recorded wake.

No tests were run. WP5a and WP8 integration gates remain open.

---

## Resolution

| Finding | Disposition |
|---|---|
| Card observation order | Open; observe the current card after the matching attempt finishes and verify the cleared running state between waits. |
| Replay enters pending sleep | Open; record entry into the sleep on each process and assert replay enters before the stored wake. |
