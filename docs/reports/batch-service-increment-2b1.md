# Batch service increment 2b.1

Implementation: 16c5943 (verified collection/journal and gated queue).
Design resolutions: 873bcab; fresh PASS batch-service-design-10.md and
interfaces-design-18.md. Diff PASS batch-service-diff-8.md (318755e).
All earlier review rounds are retained; no blocker was rejected.

Full suite: uv run --with numpy --with scipy python -B tests/run.py
139 scripts, zero failures. Log SHA256: e2cf28feed4966d53b23ae68ad50765a4feb39a4f1a0591ebcd27d8f967d160e.
The ten collection/queue tests use saved public card/ciphertext with explicitly
authored operational bindings and D answers. They prove transport, journal,
deduplication and API contracts, not D eligibility or real batch completion.
The full suite also passes the 13 throwaway-key migration tests and the launch
guard signal test with its expanded startup allowance and failure cleanup.

Delivered: immutable local snapshots, manifest/member verification, crash repair,
(case,generation)-bound facts with immutable replay, strict pure draft D wrapper,
one child per immediate parent with J→J-r1→J-r2, ordered settlement/replacement/
exhaustion queue metadata, root grammar and replacement-policy validation.
No cumulative call admission rule. DIAGNOSIS_ENABLED remains False.
No money ACK, source transition, durability pointer, dispatch or new restore
permission is granted. Holder/bind/installer/fresh-only money behavior is unchanged.
Optional diff8 hardening nits remain before integration; no row closure relies on them.

Migration recheck: pinned plan bac461d88e3b7f413c28ea55a5e70aa83a1fe56b336153d965ac23c3e1707aa6
passes the actual wrapper --dry-run: 30 prefixes,48 archive variants,
3,251,961,841 bytes;16 key rewraps;1 absent binding. Space3,644,279,178 bytes;
estimated Mac1257s/VM493s. No identity prompt/output generations/pointer changes.
Founder migration, VM unwrap/R2 qualification and catalog activation remain pending.

Murphy rows closed: none. Spend: $0 model / $0 incremental infrastructure;
reviewer-agent usage unmeasured and outside practice receipts. No VM changes,
no workers, no exam cases, no merge or push.

Next: status implementation (status-design-6 PASS). Integration addendum waits
for D's reviewed projection implementation and exact authenticated public
coverage/reconciled-decrease shapes, as directed by the parent. Then source
transitions/holder/publication, and the bounded practice qualification.
