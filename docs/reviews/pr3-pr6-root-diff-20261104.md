# Independent root goldfish review

Mode REVIEW; verbatim response:

PASS — no blocking finding in the combined PR3 + PR6 registry diff.

- `statement_round.py:94–108,115–119` authenticates and passes the same captured bytes. `registry.py:35–37,114–138` never reopens that ciphertext afterward. This closes diff-10.
- Candidate `bound` additionally requires the current card to name the offered digest (`statement_round.py:117–118`), preventing the swapped-card historical-only release.
- Promotion preserves stored ciphertext (`registry.py:71`); old objects and existing reservation snapshots remain unchanged.
- Historical rejection lists require a matching ciphertext binding and valid bounded list. Historical-only release also requires `completed`; complete entries retain the existing screening/building release behavior.
- Transition fencing checks the token plus status/digest/cipher under lock (`registry.py:133–134,209–214`). New reservations/promotions still include every live predecessor (`:84–85`).
- The remaining complete-entry candidate authentication window and malformed candidate-list behavior predate this diff. The release/reserve gap is documented; subsequent candidate reservation restores pairwise screening visibility.

Integration requirement: current factory `71cc52c` contains newer `source_sealed`, `card_path`, and `candidate_cards` APIs absent from this branch. Retain those during conflict resolution, using the supplied candidate card for digest binding and rejected-list extraction. Replacing the whole file with the PR version would regress current factory callers.

Read-only static review; no tests or network calls. Authored reselection cards do not close the Murphy row. The reported full suite has 197 scripts with 9 failures, so acceptance remains pending despite the code-review PASS.

PRs: https://github.com/unbughq/unbug-bench/pull/3 — `7de75d9a50f35b203cf2dff4d5d484e0a993c2e1`; https://github.com/unbughq/unbug-bench/pull/6 — `dc813839183a3a8e03a4551ce5c94ef49b2be58a`. Prior diff-10 blocker: closed by PR6. Diff-11 and this review: PASS. Checks: not green; root acceptance pending.

## Disposition

Accepted; no findings rejected. Current restore APIs and supplied candidate card
map survived the merge and were inspected. No Murphy closure or deployment.
Root integrated acceptance remains required.
