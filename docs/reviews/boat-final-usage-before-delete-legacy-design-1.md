Blocker — `docs/designs/boat-final-usage-before-delete.md`, “Explicit historical owner decision”: `budget_debit` is called strict but its exact schema and validation contract are unspecified. Define its exact keys/types, the pinned decision SHA, and how `budget_amount` validates the reservation key, original snapshot, permanent $0.036 debit and $5 ceiling. Specify whether retained evidence is required on replay. These choices currently fall to the implementer.

Blocker — same section, permanent-debit replay: explicitly protect `--finish` from rewriting `budget_debited` rows. Both existing finish branches assign `status='finished'` and save the ledger, and one also rewrites the spend file. Specify refusal or validated no-op before any provider call or write, and add a regression proving finish replay preserves the debit and every evidence byte.

## Implementer disposition

Both blockers accepted. Exact schema/hash/snapshot/key/row-equality validation and initial-versus-replay evidence are specified in the design resolution section. --finish and --settle validate and no-op before I/O or provider calls. No finding rejected. Fresh round2 follows.
