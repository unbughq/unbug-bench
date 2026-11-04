# Fresh native Codex review

Mode REVIEW; no conversation history. Verbatim response follows.

PASS — no blocking finding in `origin/factory-simplify...9d4202918c654e1fda03ab0f5c1ae7ae4f49b9a1` for inactive release preparation.

- Shared transfer preserves source authority and ACK/artifact validation (`factory/batch_transfer.py:180`, `factory/batch_holder.py:156`), pins the snapshot before export, and carries omitted liabilities (`factory/batch_transfer.py:212` onward).
- Independently checked: EXPECTED equals the tracked -4 manifest; embedded predecessor equals original -3 bytes; source policy, snapshot digest, all 15 fixture hashes, archived predecessor manifest and founder decisions match their retained bindings.
- Carry coverage checks exact case/generation, $0.01 held commitment, zero prior model total, every restore member, replay and altered-pin refusal (`tests/factory/test_practice4_carry.py:88`, `:107`).
- The final Clock is confined to authored admission/configuration setup (`tests/factory/test_boat_retirement.py:37`, `:51`). It does not replace `boat_lifecycle` clocks or saved stop/meter DTOs. Corruption, bypass, recheck and immutable settlement assertions remain intact (`:414`, `:428`, `:438`).

Qualification limits: this is source review, not live lifecycle qualification. No tests or external calls were run by this reviewer. The exact-head full suite remains required (`docs/designs/practice4-checkpoint-carry.md:77`). Imported -4 retirement is explicitly untested offline (`tests/factory/test_boat_retirement.py:45`); live snapshot revalidation, stopped-meter proof, exact-worker deletion and settlement remain required (`docs/designs/practice4-checkpoint-carry.md:103`). Practice dormancy after -4 opt-in remains procedural (`tests/factory/test_practice4_carry.py:134`).

Disposition: accepted; no findings rejected. No merge or live qualification claimed.
