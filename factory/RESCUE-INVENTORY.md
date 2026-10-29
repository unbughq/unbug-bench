# Factory recovery retirement inventory

Baseline: `eeea0f1` on 2026-10-29. Locations below refer to that commit, including deleted code. Each row is one logical compatibility or exception path, not a keyword hit or every validation conditional. General fail-closed checks and accounting readers are included so that a `legacy` label is not mistaken for a retry grant.

Old generations receive no bespoke second rescue. Existing authenticated receipts can carry forward remaining allowances; they cannot reset spending, calls, freshness attempts, or stress history. D1 is a general 5000-call ceiling/default with smaller explicit limits preserved. D2 is a pinned one-round grant after a late defect, preserving the money cap. G2 archive handling applies to every case. D4 remains the existing exact-release, exact-scope evidence waiver; it authorizes restaging, never a gate pass.

Both current live cards have completed unresolved freshness reviews, so both already require a ruling before automatic recovery. Retaining pending writer authority does not bypass that stop. The real public model history contains `attacker-10` for e15450, while 873d7f has no round-9 writer/stress invocation; this corroborates retiring the former round-9 rescue and retaining the latter pending-writer rule.

## Counts by file

| File | Deleted | Generalized | Kept |
| --- | ---: | ---: | ---: |
| `factory/apply_free_model_cutover.py` | 1 | 0 | 0 |
| `factory/attack_findings.py` | 0 | 0 | 1 |
| `factory/budget.py` | 0 | 0 | 2 |
| `factory/calibration.py` | 0 | 0 | 1 |
| `factory/carry_over.py` | 0 | 0 | 5 |
| `factory/case_permissions.py` | 0 | 0 | 1 |
| `factory/coordinator.py` | 0 | 0 | 1 |
| `factory/founder_decisions.py` | 0 | 1 | 2 |
| `factory/founder_ruling.py` | 4 | 0 | 3 |
| `factory/free_model_patch.py` | 1 | 0 | 0 |
| `factory/free_models.py` | 1 | 0 | 3 |
| `factory/g11_review.py` | 1 | 0 | 0 |
| `factory/key_holder.py` | 3 | 0 | 3 |
| `factory/late_recovery.py` | 0 | 0 | 3 |
| `factory/launch.sh` | 2 | 0 | 0 |
| `factory/recovery.py` | 3 | 0 | 4 |
| `factory/restart.py` | 1 | 0 | 0 |
| `factory/restore_bundle.py` | 0 | 0 | 3 |
| `factory/restore_ledger.py` | 0 | 0 | 3 |
| `factory/restore_sync.py` | 0 | 0 | 2 |
| `factory/run.py` | 3 | 1 | 12 |
| `factory/run.py.orig` | 1 | 0 | 0 |

Total: 72 paths; 21 deleted, 2 generalized, 49 kept. The unreferenced 2425-line runner backup is counted as one deleted artifact.

## Full inventory

| Baseline file:line | Handles / affected cases or generations | Current dependency | Disposition / reason |
| --- | --- | --- | --- |
| `factory/run.py:273` | G2/G3 resume skips rewriting. Any infrastructure gate retry | General | **kept** — Gate failure shape, not case identity; no stopped VM card currently has a failed gate. |
| `factory/run.py:282` | Freshness before author/stress calls. e15450 and 873d7f | Yes | **kept** — Validate unresolved public matches before spending on construction; all cases use the same rule. |
| `factory/run.py:303` | Late defect requires authenticated ruling. Any exhausted late-defect case | Standing D2 | **kept** — One pinned round grant; no gate or stress pass is granted. |
| `factory/run.py:852` | Completed saved case inferred from attack history + G1. Old paused VM cases; both live cases | Possible | **kept** — Saved file shape is sealed; public metadata cannot prove this fallback unnecessary. |
| `factory/run.py:890` | Completed artifact bypasses new prototype admission. Both live cases; completed paused cases | Yes | **kept** — All saved completed artifacts still run freshness and final gates; legacy_completed_case is a historical output label. |
| `factory/run.py:902` | G8/G9 findings recovered from old moved-aside reviewer directories. Pre gate-details generations | No | **deleted** — All 37 stopped VM cards have no failed_gate; current repairs retain gate-details. |
| `factory/run.py:929` | Carried ruling supplies round cap. Both live cases | Yes | **kept** — Authenticated imported allowance, matching CLI caps; no reset on restore. |
| `factory/run.py:966` | Version-2 pending-writer exception. 873d7f round 8, grant through round 9 | Yes | **generalized** — Use authenticated resume.pending_writer, matching saved round, final budget stop and a remaining granted round; no case/version dispatch. |
| `factory/run.py:971` | Version-2 final-repair continuation. e15450 old round-9 generation 0e3f2c87… | No | **deleted** — Latest collected public card has completed round 10; do not replay its spent round-9 rescue. |
| `factory/run.py:1020` | Retain authorized findings as writer feedback across release bindings. 873d7f saved round-8 feedback | Yes | **kept** — Imported receipt binds report digest and round. Findings authorize writer work, never a stress pass. |
| `factory/run.py:1043` | Old distinct-binding reservations count toward release review bound. Both live cases and old paused receipts | Possible | **kept** — Accounting existing reservations prevents refreshed infrastructure allowance. |
| `factory/run.py:1077` | Always send exactly one retained finding to writer. e15450 v1 round-8 ruling | No | **deleted** — Obsolete one-finding ruling; normal independent freshness classification applies. |
| `factory/run.py:1084` | Cleared feedback requires current stress review. 873d7f; any authorized feedback | Yes | **kept** — Removing a freshness-only blocker cannot grant a new-release stress verdict. |
| `factory/run.py:1706` | Retained G2 verdict requires completion marker, snapshot, binding and TTL. Both live cases; any interrupted confirmation | Yes | **kept** — General authenticated evidence reuse; partial reviewer output never authorizes clearance. |
| `factory/run.py:2446` | Old worker image lacks parallel bench pool. Paused VM cases with older images | Unknown | **kept** — Serial capability fallback; public cards cannot attest installed worker files. |
| `factory/run.py:2507` | Restore embedded continuation ledger if worker ledger absent. Saved checkpoints, including paused VM cases | Possible | **kept** — Accounting preservation; importer and launch paths own archive authentication. |
| `factory/run.py.orig:1` | Tracked obsolete runner backup. No entrypoint references this file | No | **deleted** — Dead duplicate runner, 2425 lines; source ownership stays with run.py. |
| `factory/recovery.py:42` | Exact e15450 freshness coverage exemption. 761f3e3433c8fbfae9395f5ffa0fe762c7d437eb1b0ee0259ebd0f7ee5cfa1cb | No | **deleted** — Superseded by restore-14 generation 2675a0cb…; completed unresolved verdicts require a ruling. |
| `factory/recovery.py:55` | Exact canary pinned-version exemption. cc975a034581edab8561072468512edec6437d3be8932e02882c2cb4b9cf97a8 | No | **deleted** — Superseded by restore-14 generation d1f9174d…; no generation-hash bypass remains. |
| `factory/recovery.py:110` | Exhausted paused rounds require explicit increase. Paused VM cases | General | **kept** — Gate-only continuation is separately authenticated; a pause cannot refresh rounds. |
| `factory/recovery.py:141` | Repeat explicit prior limit increase after malformed-report stop. Saved budget_raised / rounds_raised histories | Possible | **kept** — Caller must repeat the exact explicit increase; history alone never reopens a case. |
| `factory/recovery.py:179` | Approved paid-to-free paused-generation bypass. 19 expired cohort rows; all pinned generations superseded | No | **deleted** — None of the 19 pins equals its current VM card generation; deliberate pause policy remains. |
| `factory/recovery.py:240` | Transport-specific ledger stop reconciliation. Paused/limited VM cases | Yes | **kept** — Interpret existing ledger labels without clearing history. Removed the obsolete model-cutover allowance. |
| `factory/recovery.py:262` | In-place adopter permits operational pause differently from restart. Paused VM cohort | Possible | **kept** — Existing transport contract, not a per-case exception; launch-path work owns migration. |
| `factory/restart.py:12` | Re-export two hash-exemption predicates. Only deleted freshness exemptions | No | **deleted** — Public recovery decisions stay in recovery.py. |
| `factory/founder_ruling.py:16` | v1 hardcoded allowances + authentication. e15450 f5ec8c46…; 873d7f 7298abd8… | No | **deleted** — Already applied; old generations cannot install/reset allowances again. |
| `factory/founder_ruling.py:54` | v2 exact case/round/spend/diagnosis authentication. e15450 0e3f2c87…; 873d7f 85f0da07… | No | **deleted** — Carry the existing applied receipts; do not reinstall grants for earlier generations. |
| `factory/founder_ruling.py:100` | v3 late-defect authentication/application. Any late-defect case | Standing D2 | **kept** — Hash-pinned, exact generation + ledger + prior receipt, one round, same money cap, journaled application. |
| `factory/founder_ruling.py:156` | v2 state rewrite and final/pending repair installer. Same two old v2 grant generations | No | **deleted** — No fresh allowance installation required by current cards. |
| `factory/founder_ruling.py:211` | v1 reset, backups and freshness receipt invalidation. Same two old v1 grant generations | No | **deleted** — No counter resets or obsolete invalidation journals on new imports. |
| `factory/founder_ruling.py:282` | Read authenticated already-applied authority. Both live restore-14 cases | Yes | **kept** — Archive receipt must match external post-extraction importer receipt and CLI caps. |
| `factory/founder_ruling.py:307` | Authorize retained feedback by round + raw report hash. 873d7f round 8 | Yes | **kept** — Small general rule already present; retain until the pending writer work is resolved. |
| `factory/founder_decisions.py:25` | G2 archive-check ruling. Every case | Standing G2 | **kept** — Dead URL clearance needs no archive snapshot; available archives get the same bug/version review; unknown stays blocked. |
| `factory/founder_decisions.py:29` | D1 call allowance only for two case IDs. Previously only e15450 and 873d7f | Standing D1 | **generalized** — 5000 is the general ceiling/default; explicit smaller caps remain smaller; rounds and money caps stay independent. |
| `factory/founder_decisions.py:2` | D4 exact-release and two-case restaging scope. Both live cases; release ab7f67f9… | Yes | **kept** — Plain scoped grant data and generic evidence validation; not worker verdict authority. Do not broaden an exact-release waiver. |
| `factory/key_holder.py:38` | Authenticated concurrent peer cancellation. Cases with joined concurrent model attempts | Possible | **kept** — General process/accounting evidence, not case ID inference. |
| `factory/key_holder.py:261` | Paid-to-free exception to explicit-pause attestation. Only superseded 19-cohort paused generations | No | **deleted** — An attested explicit pause needs deliberate resume; no old generation pin bypass. |
| `factory/key_holder.py:358` | Substitute configured legacy generation budget floors. Old reservations lacking original budget_calls/budget_cost | No live-bundle use | **deleted** — Both restore-14 policies have no legacy floors. Missing floors stay unresolved for explicit reconciliation. |
| `factory/key_holder.py:430` | Resolve every reservation with a listed generation. Historical resolved_generations policy overrides | No live-bundle use | **deleted** — Both restore-14 policies have empty generation overrides; future failures on the same input must remain consumed. |
| `factory/key_holder.py:430` | Resolve only reservations before fixed explicit cutoff. Both live restore-14 policies | Yes | **kept** — Each current bundle has resolved_before with retained pre-restore reconciliation evidence. Cutoff does not clear future receipts. |
| `factory/key_holder.py:555` | Read historical controller monitor-state path for retired-worker proof. Old collected-successor jobs; not enabled in either live policy | Unknown for VM policies | **kept** — VM policy/receipt files excluded by read-only public-card scope. Replace with explicit policy-selected collection evidence after migrating controller state; not a safe card-only edit. |
| `factory/launch.sh:163` | Authenticate extra original archive for digest-v1 G11 audit. Old digest-v1 audits | No | **deleted** — Both VM audit cards are digest v2; older audit digest generations now refuse before VM creation. |
| `factory/launch.sh:613` | Transfer/decrypt extra original case for digest-v1 G11 audit. Same retired digest-v1 audits | No | **deleted** — Removed obsolete transfer path; no transfer or decryption was performed. |
| `factory/g11_review.py:24` | Ambiguous digest and v1 original/copy reconstruction. Old digest-v1 audits | No | **deleted** — Only framed digest v2 continuation remains; current two audit cards use v2. |
| `factory/carry_over.py:64` | Keep unattributed historical monetary totals. Old paused/limited VM cards; live ledgers | Yes | **kept** — Immutable accounting facts; never imported allowance credit. |
| `factory/carry_over.py:103` | Active/running checkpoint becomes unknown usage. Interrupted VM ledger shapes | General | **kept** — Fail closed until worker reconciliation; not an automatic retry grant. |
| `factory/carry_over.py:112` | v0 public-card to observations migration. Historical public cards | Archival only | **kept** — Always records missing attempt history, so this cannot admit a legacy resume. |
| `factory/carry_over.py:132` | v1 monetary event migration. Historical metadata inspection | Archival only | **kept** — Retains totals/waste; cannot fabricate missing attempt/cause history. |
| `factory/carry_over.py:331` | Recompute and validate migrated historical usage. Historical metadata inspection | Archival only | **kept** — Projection tampering and unknown usage remain blocking. All 58 before/after dispositions match. |
| `factory/restore_ledger.py:53` | Embedded ledger fallback and separate-ledger agreement. Saved checkpoint formats | Possible | **kept** — Authenticated accounting boundary, required independently of generation retirement. |
| `factory/restore_ledger.py:81` | Carry already-applied ruling forward. Both live restore-14 cases | Yes | **kept** — Retained receipt must equal the public receipt; tests use actual saved cards and actual applied metadata. |
| `factory/restore_ledger.py:90` | Explicit correction authority / pinned new grant installation. Future D2 late-defect rulings | Standing D2 | **kept** — v1/v2 installations now refuse; any current correction still requires pinned authorization. |
| `factory/late_recovery.py:17` | Missing authenticated stress receipt gets no gate-only allowance. Practice/older saved checkpoints | General | **kept** — Fail-closed shape check, not a case exemption; no current card has gate_continuation. |
| `factory/late_recovery.py:58` | Freshness-only stress clearance by independent completed review. 873d7f pending feedback; any typed freshness-only finding | Possible | **kept** — Raw hashes, binding, snapshot and completion marker authenticate clearance. |
| `factory/late_recovery.py:94` | Exhausted late defect stops for one-round ruling. Any case including both live cases | Standing D2 | **kept** — Private defect details remain sealed; general rule already applies to every case. |
| `factory/free_models.py:13` | Case-specific original account validation for free provider route. 19 configured VM cohort cases | Possible | **kept** — Public VM cards do not establish original account migration evidence; no account change inferred. |
| `factory/free_models.py:26` | Deadline/cap/protected-role validation for configured transition. 19 expired cohort cases, all present on VM | Possible | **kept** — Keep existing refusal and original roles/caps. Replacing remaining cohort data needs explicit model/account migration policy. |
| `factory/free_models.py:55` | Apply old paid rotation + invalidate reused gates on model change. 19 configured VM cohort cases | Possible | **kept** — Configuration-driven role changes; current expiry still refuses automatic migration. |
| `factory/free_models.py:75` | Pin automatic pause resume to obsolete cohort generation. 19 configured cases; zero current generation matches | No | **deleted** — General deliberate-resume policy replaces the historical pin exemption. |
| `factory/apply_free_model_cutover.py:1` | Patch/freeze/restart historical existing controllers. 2026-10-19 cohort controllers and archived paths | No | **deleted** — Standalone one-off deployer has no remaining callers; no current generation matches its pause pins. |
| `factory/free_model_patch.py:1` | Literal source-seam patch and first-deployment upgrade. Historical pre-durable-receipt runner source | No | **deleted** — No runtime imports; only obsolete patch-specific tests referred to it. |
| `factory/coordinator.py:159` | Skip absent legacy whole-case cap when checking old config. Older VM public cards missing case_budget | Yes | **kept** — Do not invent issued caps; configuration validation is separate from spending admission. |
| `factory/restore_sync.py:62` | Recover omitted statement identity from unchanged search ciphertext/prior receipt. Older inputs in current restore lineage | Possible | **kept** — Other agent owns sync plumbing. General rule: only exact ciphertext + case/statement binding may supply omitted identity; never counts as a new verdict. |
| `factory/restore_sync.py:148` | Use verified .pre-restore backup during publication retry. Current restore publication history | Possible | **kept** — Other agent owns sync plumbing; generic compare-before-replace recovery, no case-specific allowance. |
| `factory/restore_bundle.py:62` | Optional old founder-ruling host file expectation. Restaging current two live bundles | Yes | **kept** — Already checks whether policy still requests a new ruling; other agent owns launcher manifest/file lists. |
| `factory/restore_bundle.py:182` | Two-case restaging caps/TTL and D1 bundle checks. Both live restore bundles | Yes | **kept** — Other agent owns this file; plain CASES scope data retained. Replace migration-only restaging constants with saved config in a separate owner-approved change. |
| `factory/restore_bundle.py:272` | Failed pre-restore launch reconciliation. Both current restore-14 policies | Yes | **kept** — Read-only proof of unchanged card/archive and disposed worker, bounded by fixed timestamp; do not remove current authorization history. |
| `factory/budget.py:51` | Attribute historical totals when per-turn role/usage missing. Older VM ledgers and current carried usage | Yes | **kept** — Financial facts must survive retirement; no synthetic free allowance. |
| `factory/budget.py:373` | Label unattributed historical invocation roles. Older retained ledger records | Possible | **kept** — Output/accounting normalization, not a resume exception. |
| `factory/attack_findings.py:15` | Recognize explicit old unfinished-validation label. 873d7f ruling expressly preserves legacy wording | Possible | **kept** — Unknown prose remains blocking; only the explicit label is separated from writer-fixable findings. |
| `factory/calibration.py:370` | Map historical no-guard reason to public aggregate labels. Old VM calibration rows | Possible | **kept** — Summary compatibility cannot grant calibration success or another attempt. |
| `factory/case_permissions.py:1` | Normalize old restrictive case-tree modes after extraction. Both live restore cases; older paused artifacts | Possible | **kept** — General permission preparation; no decrypted file inspected and no bundle changed here. |

## Real card decision replay

Read-only sources: the two `/Users/bugsincode/Developer/unbug-bench-{e15450,873d7f}-restore-14-20261029/sealed/*.scorecard.json` files and all 56 `/home/user/unbug-bench/sealed/*.scorecard.json` public cards fetched over the authorized SSH connection. The bundle copies duplicate the same two VM generations: 58 observations, 56 distinct cards, 37 stopped VM cards. No real encrypted archive, private work tree, holder state or VM policy was opened. Only the two local public restore policies were additionally read to establish cutoff/floor usage.

`tests/factory/fixtures/20261029-real-public-cards.json.gz` contains the real JSON card values, without field projection or manufactured cards. The before snapshot was recorded from baseline recovery, accounting and carry-over code before edits. Canonical SHA-256 binds each full card; `test_saved_recovery_decisions.py` compares every decision and monetary projection. Authorization metadata tests additionally carry the actual two applied receipts through the accounting boundary. This proves public policy equivalence, not encrypted worker state or archive validity.

| Observations | N | Restart eligible before → after | Holder stop eligible before → after | Changed |
| --- | ---: | ---: | ---: | ---: |
| VM stopped cards | 37 | 10 → 10 | 33 → 33 | 0 |
| VM other public cards | 19 | 0 → 0 | 0 → 0 | 0 |
| Restore-14 copies | 2 | 0 → 0 | 0 → 0 | 0 |
| Total observations | 58 | 10 → 10 | 33 → 33 | 0 |

Eligibility is the public stop decision, before ciphertext, holder-policy, account, deadline and active-worker checks. The full per-card before/after table follows; identical rows explicitly show both sides.

| Source | Card | Generation | Restart before → after | Holder before → after |
| --- | --- | --- | --- | --- |
| vm | `case-20261014T130816Z-a869de.scorecard.json` | `d93308338261cf32d468ec21ca5e619eea06b6585451a2cf51b644e2102ba9c8` | blocked → blocked | blocked → blocked |
| vm | `case-20261014T205027Z-6d8046.scorecard.json` | `1764d626273b0bc31343e403993cec2e57e634bf9760d28284a7355bf5697551` | blocked → blocked | blocked → blocked |
| vm | `case-20261015T122810Z-aeefd5.scorecard.json` | `d581872f757506d235803f95e0de451247902d105f6636deca0aea89caf43963` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T114415Z-11a9f1.scorecard.json` | `b7b1a14ea967d981667c8c8fb0d318b7ae6ac063211b659e48e1c9ca9d12fb59` | eligible → eligible | eligible → eligible |
| vm | `case-20261017T114422Z-0f3b37.scorecard.json` | `7a12f531ed64c3cdbadaa5fa551aec50ee3927a940b5b33f9e914f771cf75ac6` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T114423Z-d4a7b8.scorecard.json` | `25d259709add6b13bf04853377dad0c6ce70bfa39ccc2f50ab8553b9ae09f77e` | eligible → eligible | eligible → eligible |
| vm | `case-20261017T114426Z-fcde6b.scorecard.json` | `7f936886fe56d736f09bcfdd4cbffd148b94b0c5e82458f2113f4ea6fa8b49c6` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T114431Z-9d2b0e.scorecard.json` | `4982654da0739b3f7172709e335be1f2022c6fb2186ed5f2ee4b8ba062b209fb` | eligible → eligible | eligible → eligible |
| vm | `case-20261017T114432Z-000990.scorecard.json` | `5116be00ed8d30ec1718cb0adcac5c0ab90ceda0e937549889cbf4e836e0c8c4` | blocked → blocked | eligible → eligible |
| vm | `case-20261017T120254Z-01eae8.scorecard.json` | `1ffd01dc7db823e93d813250d7e6f4ab0402fc2ddda423e4315caed64f0cf5cb` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T120256Z-86b100.scorecard.json` | `5e7d716be35403e4f00979612255c6749679d8f5b5df3c8f150f6fc642dcc6f5` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T121257Z-195b92.scorecard.json` | `de0e87c3f39e81caaad7e04086d65dacbcdad9bf1f022ffab3767cf7bbb03a97` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T121326Z-832462.scorecard.json` | `d761b1733458fa91271f60c9edd69085de5762fbba9cbf43ea0950bb16eb2a39` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T125556Z-18681d.scorecard.json` | `90fa095feff8923aed90516356e7e975991ee9e342fb7b8f6176579b2c826a40` | blocked → blocked | blocked → blocked |
| vm | `case-20261017T153943Z-2c8a49.scorecard.json` | `75bc4d03d3af186a3986f4ed4544add80840048fe6afe314d70d06c9bbbe4135` | blocked → blocked | eligible → eligible |
| vm | `case-20261017T212113Z-5813be.scorecard.json` | `649809386bf2faf7bffc6144ba1af3c7e3d61424f5494759ea6b0b46a593a195` | blocked → blocked | eligible → eligible |
| vm | `case-20261017T212115Z-8acb5c.scorecard.json` | `19ae5159e59448be20552b5c607732fdc2d70a3f97b7f908a46897faa048a47f` | blocked → blocked | eligible → eligible |
| vm | `case-20261017T212118Z-1ad7fa.scorecard.json` | `7906dfd68277573ec45aa9ca7335b37f62e28dfb3cc165ccdcff098dd42cf992` | blocked → blocked | eligible → eligible |
| vm | `case-20261017T212118Z-ea7425.scorecard.json` | `b09d858ac398568830e3206e7cd76f7119644228022539cb09d607b079d33859` | blocked → blocked | eligible → eligible |
| vm | `case-20261018T144333Z-f46dac.scorecard.json` | `d3958e161c5b5924df62d842a976750b4f5b54f541881c75802eb06cb5d8eccd` | blocked → blocked | eligible → eligible |
| vm | `case-20261018T144339Z-8f9762.scorecard.json` | `31da41a0ec5aa20c33007fc30851f472d0e776a9c1374ee9aec705137d6d05c6` | blocked → blocked | blocked → blocked |
| vm | `case-20261018T144339Z-e5caf7.scorecard.json` | `cdb3541516143f187f9c75a8c224738c2c936aead027bbf64345a5fb37ca236b` | blocked → blocked | eligible → eligible |
| vm | `case-20261018T144343Z-2b6c68.scorecard.json` | `4df77df40067b76027a639c2fd03fd18c780109ce3a980c65eed18cdca63e203` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T022246Z-a6beee.scorecard.json` | `4aa8dbe3e4a25c6cb65223d596a5b3e7b80e7b5ce4b9d8bb835032580f364d5b` | eligible → eligible | eligible → eligible |
| vm | `case-20261019T022247Z-44c16b.scorecard.json` | `23c39df69757df1878f7cb2c9bf7c7b32baeaaa565988b27f7b17b1453ffd438` | eligible → eligible | eligible → eligible |
| vm | `case-20261019T022247Z-e5a2e9.scorecard.json` | `e15e2360a98a39c200d33a7466cbc6a47875d2b9acbff38658748fd4b2e7ab5d` | eligible → eligible | eligible → eligible |
| vm | `case-20261019T022248Z-953035.scorecard.json` | `4175971b70212ff6adfc973c83842ebabe0d8af7b873f7e162c4691c65168e1c` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T055203Z-b5521c.scorecard.json` | `b50829b90cc456270566440e0638f58c798ab34f8205dc85e49718ae4d190b8a` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T055205Z-14d35a.scorecard.json` | `a90b4bc3fe24a24755b9165a364e61159959c23a4584f41f1e7fcc49ef72e8b2` | blocked → blocked | blocked → blocked |
| vm | `case-20261019T055205Z-ce4d82.scorecard.json` | `f93b67bccedad80e4b03be394eec98eb71e47fa76df75de75c0693d6bbdc34ee` | blocked → blocked | blocked → blocked |
| vm | `case-20261019T055209Z-7d8a30.scorecard.json` | `b4f44d7aa9cc91263548535f60db8349d0ea1bd1df4aefb2135d986c7448547c` | blocked → blocked | blocked → blocked |
| vm | `case-20261019T061050Z-1bb2ad.scorecard.json` | `c913ef0e83baba300d657de0f5bc5dcdfb217c0519e13a4ca6a4163db48c7d3a` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T061055Z-798600.scorecard.json` | `0d1ff60f6140a82ef42a5fffcaa67598251ff3a49863f5f80c47f58acb96311f` | blocked → blocked | blocked → blocked |
| vm | `case-20261019T061056Z-e3b57a.scorecard.json` | `ac35a130442403fcaf7adc81888fd73addd05c130135d1e088027bdeee4e8b8b` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T061109Z-e9d919.scorecard.json` | `39a5b9b2906b6b05d02dcc133e5e7594f31dd157b3a6c25512ba4e09df9818c4` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T061116Z-3826d5.scorecard.json` | `c232b2b1e8ea9bf7a798d94cd0e9815c92ac94058b564ee1bf500e7b7327569f` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T061455Z-c4a72b.scorecard.json` | `11e06246a319ef0dbeba7da109655ef5e21ebd299eea5468e23ba30d404b2df3` | eligible → eligible | eligible → eligible |
| vm | `case-20261019T061459Z-cb5e26.scorecard.json` | `6a7f97cfe3afcab91912078f67ee6996f5c7d1a693b710cd05421e49b1f1c04e` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T061510Z-6a8a7d.scorecard.json` | `7eb0e12db6779d70d49b99f38e8eb0a22d7c209ba5bdc26c050a6be7ca05eb25` | eligible → eligible | eligible → eligible |
| vm | `case-20261019T064341Z-2a7b2a.scorecard.json` | `59c1f974b26477c3950a119211f00075cb8e592431bc16078d0d30b863bd2401` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T064344Z-03be64.scorecard.json` | `eb694a2898a37c4368673649bd2494e379da808809389a8577c86f95fb6ca041` | eligible → eligible | eligible → eligible |
| vm | `case-20261019T065843Z-22e434.scorecard.json` | `acf538b5938c11c6ef059321f388c95a0e4337d7b9f720582972bce724b82278` | blocked → blocked | eligible → eligible |
| vm | `case-20261019T072318Z-04d417.scorecard.json` | `f118ca399b92652791662886c82754f1ff6388a3601d7550fb523bbee10b7bb3` | blocked → blocked | eligible → eligible |
| vm | `case-20261020T094641Z-5a6ef3.scorecard.json` | `5ea5cfa90ed79a3e6daebfb2be74d292ad303bb718d003aaca0a350f58e932ba` | blocked → blocked | blocked → blocked |
| vm | `case-20261020T094644Z-2abb0a.scorecard.json` | `804c597e8520765f1f5fff4f3e33f9edd810d6313ee4fb79812d870a452849b0` | blocked → blocked | eligible → eligible |
| vm | `case-20261020T094704Z-a61f54.scorecard.json` | `5c3fff6cb592b6fe805e7aa6915d42991bb3e531640bbefe7e2398d9db75e551` | blocked → blocked | blocked → blocked |
| vm | `case-20261020T094712Z-eadaf2.scorecard.json` | `6846f904f73c47de47c34e9195fa1f79622e5d9ceb68c205658d229d026a0aa6` | blocked → blocked | blocked → blocked |
| vm | `case-20261020T094950Z-cae763.scorecard.json` | `31880e3e0bfa38eae759c90711679902266651aed1c86c4d838f220ee5dfe68e` | blocked → blocked | eligible → eligible |
| vm | `case-20261020T094956Z-055481.scorecard.json` | `0667f38ffda45cc455ce9802053507f61e7ba7bf9c4cfbf589dd6a9e334e30ef` | blocked → blocked | blocked → blocked |
| vm | `case-20261020T095024Z-25fbfa.scorecard.json` | `7981dc6e05b0518e35d86fc343ec4e3254fb93e1dd1437e853d77161d4e1eb43` | blocked → blocked | eligible → eligible |
| vm | `case-20261020T095039Z-091b3f.scorecard.json` | `636a7703534bee90a503508c2c83a454c5af55159548b1ed1f094cb78a5e91af` | blocked → blocked | eligible → eligible |
| vm | `case-20261023T223056Z-c7d405.scorecard.json` | `bfaace582d94c5c33840dad3e2c20a6644eff280ebf738fa2962fd4425dc261b` | eligible → eligible | eligible → eligible |
| vm | `case-20261024T043353Z-e15450.scorecard.json` | `2675a0cbaee17019e42d6412a29433b70bce9c0de9bae58d56b2f86fb17c3608` | blocked → blocked | blocked → blocked |
| vm | `case-20261024T085209Z-873d7f.scorecard.json` | `d1f9174de33ca6fe824693b90f14300f77d38bb78db44e3cdea48d51c8eb1e90` | blocked → blocked | blocked → blocked |
| vm | `g11-review-case-20261017T114426Z-fcde6b.scorecard.json` | `35de7b723d396e2e71ce09347e73173756f81ff2977d5f86d1ad8350d1387a66` | blocked → blocked | blocked → blocked |
| vm | `g11-review-case-20261017T212115Z-8acb5c.scorecard.json` | `4e67bd722510fb156d9d82d3049e25f13f7215c36a67c6f69d4cde3b8456284a` | blocked → blocked | blocked → blocked |
| bundles | `case-20261024T043353Z-e15450.scorecard.json` | `2675a0cbaee17019e42d6412a29433b70bce9c0de9bae58d56b2f86fb17c3608` | blocked → blocked | blocked → blocked |
| bundles | `case-20261024T085209Z-873d7f.scorecard.json` | `d1f9174de33ca6fe824693b90f14300f77d38bb78db44e3cdea48d51c8eb1e90` | blocked → blocked | blocked → blocked |

## Retirements and remaining founder decisions

Retired freshness exemptions: e15450 generation `761f3e3433c8fbfae9395f5ffa0fe762c7d437eb1b0ee0259ebd0f7ee5cfa1cb`; 873d7f generation `cc975a034581edab8561072468512edec6437d3be8932e02882c2cb4b9cf97a8`. Their current replacements are `2675a0cbaee17019e42d6412a29433b70bce9c0de9bae58d56b2f86fb17c3608` and `d1f9174de33ca6fe824693b90f14300f77d38bb78db44e3cdea48d51c8eb1e90`.

Retired v1/v2 installation sources, while carrying the already-applied receipts: e15450 `f5ec8c4627bf20bdb11d7132bebe4a65848aabefc2d87c415299c71f672f14f1` and `0e3f2c87ead403d5bf575ddf963a8c662da2e0c204ca7e56b3391cc6a891b61b`; 873d7f `7298abd851c77eef4b1a9870499ee5584fae53de7be4c3858b9a7af5ecb59417` and `85f0da074ae210f0f440b39f8e9c3098bf4c23874e76030796e863c3669e5e74`.

Formally retire these superseded generations, digest-v1 G11 audits, the 19 obsolete paid-to-free pause pins, and undocumented old reservation floors. This change does not retire the 19 current VM cases: their account/cap/role migration configuration remains, with its existing expired deadline. Decide the two live completed-unresolved freshness reviews before another paid attempt. To remove the remaining historical holder monitor path, supply/migrate authenticated reservation and collection state; public cards alone do not establish it. File-list, sync and scoped restaging changes remain with their assigned owners.

## Retired cohort pause pins

All 19 current VM generations differ from the old pause pins (including absent pins); the configured deadline expired on 2026-10-23. Account/role/cap validation remains.

| Case | Old pause pin | Current VM generation |
| --- | --- | --- |
| `case-20261019T072318Z-04d417` | `c20bb1d3320cabf2b2b831f6a26e5ffe95c292f6ca3cdd9a2215d55f1382234a` | `f118ca399b92652791662886c82754f1ff6388a3601d7550fb523bbee10b7bb3` |
| `case-20261019T065843Z-22e434` | `f60bb5b38714e978aa840a440ee96ced5c45bb7ffe4114207749deed45d35bbc` | `acf538b5938c11c6ef059321f388c95a0e4337d7b9f720582972bce724b82278` |
| `case-20261019T061455Z-c4a72b` | `8839ee41347c257eae12137c27c89578b0e9311f516548d6b7cb7c73e8434b37` | `11e06246a319ef0dbeba7da109655ef5e21ebd299eea5468e23ba30d404b2df3` |
| `case-20261019T055203Z-b5521c` | `88d6cc2cc76328084b50882fe91d56f2c8d1215daf14f936876acbbd20f276dc` | `b50829b90cc456270566440e0638f58c798ab34f8205dc85e49718ae4d190b8a` |
| `case-20261019T064341Z-2a7b2a` | `0bd483c02ad5e937575e09922408de28491d29e9856ce779b421e7d3fcf8ddc9` | `59c1f974b26477c3950a119211f00075cb8e592431bc16078d0d30b863bd2401` |
| `case-20261019T061055Z-798600` | `48323c4170c93f1171b60b042fb1bc13df5af7a56b7f512feec3647b44ec1eb6` | `0d1ff60f6140a82ef42a5fffcaa67598251ff3a49863f5f80c47f58acb96311f` |
| `case-20261019T064344Z-03be64` | `e9c5c93dc3e97f04fba464fff2fd378b70f4be64b3c36cff6d3a9d9478f31d67` | `eb694a2898a37c4368673649bd2494e379da808809389a8577c86f95fb6ca041` |
| `case-20261019T061056Z-e3b57a` | `29556b01d2d1711f2e7fb236a430edaf9426e871203540ee6f2ff8e56bc2ed29` | `ac35a130442403fcaf7adc81888fd73addd05c130135d1e088027bdeee4e8b8b` |
| `case-20261017T114432Z-000990` | `3f6f3a10d1e49a348145a6ef9ba29b522330eeef88160b9442026e9a52f59834` | `5116be00ed8d30ec1718cb0adcac5c0ab90ceda0e937549889cbf4e836e0c8c4` |
| `case-20261019T061109Z-e9d919` | `None` | `39a5b9b2906b6b05d02dcc133e5e7594f31dd157b3a6c25512ba4e09df9818c4` |
| `case-20261019T061050Z-1bb2ad` | `None` | `c913ef0e83baba300d657de0f5bc5dcdfb217c0519e13a4ca6a4163db48c7d3a` |
| `case-20261018T144333Z-f46dac` | `None` | `d3958e161c5b5924df62d842a976750b4f5b54f541881c75802eb06cb5d8eccd` |
| `case-20261017T212113Z-5813be` | `27e5908b4ecc258caa8505df6a696884a752579a0e48227f0115ed9d2ba4e548` | `649809386bf2faf7bffc6144ba1af3c7e3d61424f5494759ea6b0b46a593a195` |
| `case-20261019T061459Z-cb5e26` | `2f4f4fb218e6eb88d75cdfb47397ce85cf7863561e3fb0f7cc4f6c828a7094f4` | `6a7f97cfe3afcab91912078f67ee6996f5c7d1a693b710cd05421e49b1f1c04e` |
| `case-20261019T061510Z-6a8a7d` | `49721f481f4854e6245e87e6399fee53293a700f394f30d41e92dc429ae182b7` | `7eb0e12db6779d70d49b99f38e8eb0a22d7c209ba5bdc26c050a6be7ca05eb25` |
| `case-20261018T144343Z-2b6c68` | `None` | `4df77df40067b76027a639c2fd03fd18c780109ce3a980c65eed18cdca63e203` |
| `case-20261018T144339Z-e5caf7` | `None` | `cdb3541516143f187f9c75a8c224738c2c936aead027bbf64345a5fb37ca236b` |
| `case-20261018T144339Z-8f9762` | `None` | `31da41a0ec5aa20c33007fc30851f472d0e776a9c1374ee9aec705137d6d05c6` |
| `case-20261017T212118Z-1ad7fa` | `None` | `7906dfd68277573ec45aa9ca7335b37f62e28dfb3cc165ccdcff098dd42cf992` |

## Tests removed or retained

Removed obsolete grant-install/replay scripts `test_founder_ruling.py`, `test_founder_round10.py`, `test_founder_canary70.py`. Preserved their independent reviewer-deadline formula check in `test_confirm_deadline.py` and host adapter pin check in `test_qualified_adapter_pin.py`. Deleted the two e15450 hash-exemption tests in `test_loop_freshness.py`, the canary hash-exemption test in `test_freshness_restore_fixes.py`, G11 v1 migration/collision modes and the old two-archive launcher success scenario (now a pre-launch retirement-refusal check), legacy-floor substitution acceptance scenarios, old paid-to-free paused-generation approval scenarios and literal-source-patch tests. Current v2 digest integrity, current route/role/cap behavior, actual saved-card policies, and accounting checks remain.

The old sync-copy equality test referenced absent ignored infrastructure archives and was removed; the remaining sync checks now import maintained `factory/restore_sync.py`. D1 tests cover arbitrary cases and smaller explicit caps; the default-cap regression expectation is now 5000. Both the restart planner and runner use the saved effective call ceiling when flags are omitted, preserving 1000 only for old records without a saved cap. Real saved-card checks cover planner and runner cap resolution before any audit call, including standalone audit limits; the existing full runner harness verifies the recorded legacy cap.

Two unchanged baseline tests require ignored infrastructure scripts: `results/infrastructure/2026-10-29-real-relaunch/open-g2-verdicts.py` and `results/infrastructure/2026-10-26-opencode-failover/finalize-restore.py`. They were copied read-only from the supplied main checkout into this worktree's ignored results directory and checked byte-for-byte. No archived script, restore bundle or VM data was modified. These prerequisites are not part of the commit.

A pre-existing partial-usage timeout test used 150 ms for interpreter startup plus event emission and flaked under concurrent suites (no events reached the ledger). Its test-only window is now one second; the child still sleeps 60 seconds, preserving the interrupted-usage assertion.

Validation command: `uv run --with numpy --with scipy python tests/run.py`. Final result: **129 scripts, 0 failures**. The baseline had 130 scripts; removing three obsolete founder-grant scripts and adding two current checks gives 129. Log: `results/infrastructure/2026-10-29-case-factory-simplify/full-suite.log` (local ignored evidence).

Factory source removal: **624 lines removed, 63 added, 561 net removed**, plus the **2425-line dead runner backup**. Total text deletion including retired tests: 3914 lines. Added fixture/report text is audit evidence, not runtime code. Final read-only review found no remaining correctness findings.
