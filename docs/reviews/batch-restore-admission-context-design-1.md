# Fresh goldfish design review 1

Mode REVIEW; no history. Verbatim response:

BLOCKER — `docs/designs/batch-restore-admission-context.md:18–27,33–46`: The frozen-card contract stops at `prepare_restore`. Existing `prepare()` rereads `source_sealed/CASE.scorecard.json` for `rejected_candidates` and `public_search`. In legacy restores, collection can replace that card after freezing, mixing validated frozen identity/digests with newer metadata that can release an existing reservation. Specify that candidate reservation metadata also comes from the frozen card, and add a regression that changes the source card after freezing.

BLOCKER — Tests currently prove the retained non-candidate failure, while existing candidate tests use one directory for source and history. Add an explicit candidate test with separate selected source and authoritative history, asserting that historical statements enter the snapshot and registry mutations occur under `admission_root`, preserving existing reservations.

The bounded source-context interface and separation from failed-operation recovery are otherwise sound.

## Disposition

Both findings accepted. The design now passes the parsed frozen candidate card
through prepare, with an exact candidate_cards map, including rejection/search
metadata. Tests will cover source/history separation, replay, and mutable source
card changes after freezing. No finding rejected; final diff review must verify
these corrections. No live replay or new worker is authorized by this review.
