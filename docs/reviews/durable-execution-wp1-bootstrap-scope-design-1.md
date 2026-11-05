# WP1 bootstrap scope design review 1

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**PASS on deferring guard implementation to a separately reviewed WP8**, provided WP1 remains unpublished and undeployed, and every wave-1 execution uses a newly created disposable test database. This is a scope recommendation, not a pass for the current WP1 diff or the queue design.

The proposed boundary avoids replaying old journals without claiming they do not exist. Queue review 2, finding 5 is resolved **for the narrowed WP1 package scope** only if the design explicitly declares prior unreviewed draft journals incompatible and prohibits using them with the new code. The rollout obligation remains open until WP8 establishes that its supported launch cannot select one of those journals. The observed `7d09dae` → `77f1e6f` failure proves incompatibility for that interrupted case and attempt; it does not prove all draft journals disappeared.

**Blocker if existing databases remain a supported WP1 input.** [Engine.launch](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:713) currently accepts an arbitrary URL and launches DBOS without checking it. Its application version is still shared with the old draft. A written warning therefore cannot establish that arbitrary calls refuse or preserve an old database. Before merging under the proposed scope, document that the package has no supported persistent-database launch path, ensure tests create and use only their own temporary databases, and make no claim that the code automatically rejects old journals. If a supported wave-1 path can use an existing or unknown database, that path needs an effective guard before it is merged.

**WP8 rollout gate.** Before constructing DBOS, `SqlLedger`, `AgeKeyService`, or another database-mutating seam, the supported initial production path must:

- Provision a genuinely new, dedicated database; verify it is empty of user objects and partial application schemas; and bind all seams to that same database.
- Establish exclusive control that prevents an older engine or another writer from racing inspection and initialization. An operator instruction, application-version change, or absence of a DBOS schema alone is insufficient proof.
- Fail closed on uncertainty and leave any discovered old or unknown database’s schema and data untouched.
- Record and verify the new database’s identity for subsequent starts. A deployment mechanism that makes selecting an old database impossible can satisfy this requirement; it need not use the specific marker protocol in the proposed queue design.

“New database” applies to **the first launch of the new generation**, not every release or reboot. Once initialized, the same database and pinned application version must survive restarts and compatible releases. Future workflow changes still require replay-safe `DBOS.patch()` coverage for independently recovered child workflows as well as their parent. If the V1 path is removed, no V1 batch may have run in the new production generation.

The later guard findings are not prerequisites for merging an undeployed WP1 that contains no such guard. They remain relevant if WP8 adopts the proposed guarded bootstrap:

- Review 3’s ordering and nonmutation concerns remain essential: eager ledger and key constructors must not run before the database is accepted.
- Review 4’s exact locking, marker, and interrupted-initialization rules apply if that protocol is chosen. Another design may satisfy the same invariants more simply.
- Reviews 5–7 identify defects in the proposed schema-validation implementation, including PostgreSQL migration states and missing or altered durable tables and constraints. They cannot be treated as fixed merely because implementation was deferred. The eventual restart design must not mistake a previously used, damaged database for an empty one or silently recreate lost ledger, key, or journal state.

**Verification obligations.** For WP1, retain the original same-generation replay and three-case, 20-kill exam on real DBOS with disposable SQLite databases, plus the applicable focused and full-suite checks. For WP8, use disposable databases to test that an old draft journal and other nonempty or partial databases cannot enter the supported launch path, and that their complete schema and data remain unchanged. Test exclusive initialization and its crash boundaries, a fresh initialization followed by restart on the same database, failure before any seam factory runs, and recovery of pending parent and child workflows across a compatible release. Exercise the production PostgreSQL path and its chosen initialization/restart protocol before enabling it. No test should inspect, delete, or modify an unknown developer journal.

**Other WP1 blockers remain.** Deferring the guard does not fix the outstanding admission-bound and recovery findings in the WP1 diff reviews. If the decision queue is chosen, its grant handoff, reaper, unknown-usage settlement, message identity, and ADMIT/SEAL recovery ordering still need implementation, fault tests, and fresh review. WP2’s uncertain-create guarantee remains a prerequisite for real Boat integration. The current parent design’s statement that the queue migration is “reviewed” is premature: its recorded reviews fail and revision 8 requests another independent review.

No files were changed, no tests were run, and no database or remote service was accessed.

---

## Resolution

| Finding | Disposition |
|---|---|
| WP1 package scope | Accepted: WP1 is not a supported deployment path; tests use disposable databases and prior draft journals are incompatible. The queue and WP1 diff still need review. |
| WP8 rollout gate | Open until WP8 implements and verifies a safe first production launch and compatible same-database restarts. |
