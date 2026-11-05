# WP1 draft journal replay compatibility

An isolated offline experiment started the WP1 draft at
`7d09daee6d373eddb4e7201d32aeea0d9b2efad2` against its fake workers and a fresh
DBOS 3.4 SQLite database, waited for the first WRITER attempt to start, and killed
the engine process. It then restarted that same database and fake state with the
WP1 fixes at `77f1e6f`.

The engine process exited normally but reported the case as `engine_error` and
sealed nothing. DBOS logged these incompatible recorded operations:

- Case `case-t-1/2/writer:1/1`, step 1: `reserve_step` was recorded where the
  new code expected `DBOS.getEvent`.
- Case `case-t-1`, step 4: `attempt_workflow` was recorded where the new code
  expected `slot_workflow`.

The experiment was repeated with the same result. It used only fake workers and
a temporary local SQLite database; it did not launch a real VM or make a model
call. It demonstrates incompatibility for this particular interrupted draft
journal, not that all earlier journals are incompatible. A batch-level patch
alone does not repair the independently recovered child workflows. The design
and verification must address old journals before any rollout that may encounter
them, without deleting or modifying an unknown existing database.
