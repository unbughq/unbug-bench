# GitHub no-reply commit identity mapping

The initial GitHub push rejected 33 unpublished commits because their author and
committer email was private. The commits were recreated with the account's GitHub
no-reply email before the first successful push. Published ancestors, commit trees,
messages, dates and parent topology were preserved. Review text remains verbatim;
this table maps any original commit IDs it cites to their published IDs.

| Original | Published | Subject |
|---|---|---|
| `28c1d93e946a` | `9ef5dd620775` | Record WP1 independent diff reviews |
| `31f84fd18e49` | `c7bbe097fe4e` | Bring reviewed artifacts and classifier into WP1 for integration fixes |
| `e1e4c4805fae` | `5c7c84d2c7dd` | WP1: address initial recovery and integration review findings |
| `77f1e6fcedd4` | `14ad40a02c5a` | WP1: reconcile unexpected executor failures before retry |
| `93438e649743` | `2386ec656c1b` | Record WP1 admission designs and replay compatibility evidence |
| `16bb907e3ee3` | `9fc0691568d2` | Record further WP1 bootstrap design reviews |
| `89633b701d1e` | `525787af13c6` | Scope WP1 to disposable databases before WP8 rollout |
| `65af26f1750d` | `869fed41c646` | Specify ADMIT and worker acquisition recovery |
| `62deb9adbb02` | `c3e3e974d28c` | Add disabled pending-admission bookkeeping |
| `ad79e215a166` | `ac943d24e8a8` | Specify no-dispatch and stale-result recovery |
| `5acefe2efa3e` | `807686eabb26` | Preserve verified seals and exercise admission replay |
| `ff22dfc8c6b3` | `67105969135c` | Record recovery review and stable acknowledgements |
| `4b2b8c01050c` | `ccce36bc878a` | Specify terminal-case and pre-reserve recovery |
| `8a3b8d646bdf` | `a86d3236deab` | Verify admission message order and cleanup completion |
| `c6b174d63de4` | `57496fa0ea50` | Record checkpoint review resolutions |
| `b29bb0c37647` | `fcfca494254a` | Record admission design and checkpoint verification |
| `8bc391b60b2b` | `ebe7dfa90166` | Add disabled budget-aware admission probes |
| `369b44f2c97d` | `523933bec4e5` | Design rate-limit and credential wait policy |
| `0af437cf9034` | `bd997b7fede2` | Address provider-wait design review |
| `4dd648be48c2` | `d32a2242ea59` | Specify credential wait integration gates |
| `73893d0c9f7a` | `c8c3ac59408a` | Fix admission wake and stop races |
| `92b2ca2da769` | `de7738c3d4cf` | Keep admission responsive to events and bound updates |
| `66d05a49f5a2` | `0db73ca5f69d` | Specify concurrent provider wait handling |
| `b4c4fde1191e` | `d9ee2faab221` | Record initial WP2 diff review |
| `41861e40bbbc` | `fc0b12d42add` | Record initial WP5a diff review |
| `b7acd27a3ce7` | `aba2e158b5eb` | Record initial WP6 and WP7 diff review |
| `ea8f705687ca` | `462b24a1b228` | Clarify current provider waits and reset bounds |
| `20f9ed94825a` | `37dcdf3567c6` | Prove admission retries under uninterrupted event traffic |
| `230d8e43cff2` | `c66883393b5c` | Keep genuine provider limits waiting and surface credential faults |
| `1fa2c8a8bcf8` | `03ab60ac64f9` | Bound event-storm evidence at the retry reservation |
| `ae1dacde1b72` | `b631bfc30472` | Verify provider waits and record runner integration gaps |
| `9e5e3ac617b8` | `a6776ee89355` | Integrate provider-limit policy into WP1 |
| `6f857894a93d` | `3ec635b3f525` | Align admission notes with provider-limit decision |
