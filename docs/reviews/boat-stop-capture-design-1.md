BLOCKERS

- **Implementation readiness — receipt/error contract:** The enum is fixed, but exception mapping is unspecified. Define how subprocess timeout/nonzero exit, spawn/filesystem errors, malformed JSON/DTOs, and proof-write failures map to `timeout/rpc/io/invalid_response`; specify behavior if writing the failure receipt itself fails. Add corresponding assertions so the implementer need not choose these semantics.
- **Implementation readiness / Heilmeier — execution plan:** Name the modified files, give an implementation sequence with testable checkpoints, and state the timeline. The design currently supplies no explicit file-change list, phases, or duration.

The bounded polling approach reuses `capture_meter`, its original deadline, and strict proof predicates. It preserves the unknown hold and correctly makes no claim about the live failure’s cause.

Disposition: both accepted; exact mapping, receipt-write failure, file list, phases and estimate appended. No findings rejected.
