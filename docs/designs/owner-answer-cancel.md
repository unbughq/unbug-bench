# Exam owner failures: unmasked, lane waits sat out

**What broke (root-caused 2026-11-21).** 13 GATES attempts stopped `infra:cancelled` and were booked as waste
(~56 h, ~$122).
- In G10 the strong tester asks the case owner (ask-human). The owner's answer is a reviewer call (mimo-v2.6-pro), limited to 120 s.
- The owner found no free lane within that 120 s: the Go accounts were on quota, or Neuralwatt's seats were full.
- `exam_responder.answer` then set the tester's `role_cancel`, which killed the try.
- Mask 1: `owner_channel`'s cleanup (`iptables -D`) ran through `run.sh`, which raises `cancelled` when `role_cancel` is set.
  The real error was replaced, and the owner port rule stayed.
- Mask 2: `owner_server` raised the owner's error only when the body ended cleanly. The body always ended with the
  derived `cancelled`, so the owner's error was always dropped.
- Mask 3 (G10 side by side): the two testers share `role_cancel`, so the easy tester was cancelled too. `g10` raised
  whichever tester ended first, often the easy tester's `cancelled`.

**Fix.**
- Unmask:
  - `owner_channel` runs the port cleanup on a copy whose `role_cancel` is None. This is how `release_pilot_home` and
    `dispose_diagnosis_pilot` already run their cleanup.
  - `owner_server` raises the owner's failure when that failure set the running try's `role_cancel` and the tester's
    call then ended `cancelled`.
  - A tester `timeout` or `call_limit` that races the owner failure stays the tester's own cap, and `run._author_try`
    scores it. On main, the cancelled cleanup turned such a race into `cancelled`. Keeping the tester's cap here
    adds no new scoring rule: it is how any try that ends on its own cap is scored.
  - `g10` side by side: when a tester ends `cancelled`, the attempt raises the other tester's own stop, if it has one.
- A lane wait is not an owner failure:
  - `model_router.await_lease` already waits for a lane and raises `ProviderWait` when its patience runs out.
  - On a lane `ProviderWait` (`capacity`, `quota`, `rate`, `no_route`), `answer` asks the router again (a new `model_call`).
    `await_lease` does the waiting; there is no new sleep.
  - After an interrupted call, it asks again only on a Go or Neuralwatt quota or rate (`model_runtime.go_quota_moves_on`),
    which `model_runtime` moves on from too. Any other interrupted wait first settles its usage through the engine,
    as before.
  - `credit` is never waited out: it is a financial refusal, and no new CLI starts after one.
- The ceiling: a new request starts only within `OWNER_LANE_WAIT_SECONDS` (300 s) of the question.
  - That is ask-human's 600 s client timeout, minus a minute, minus one full wait (120 s), minus the answer's 120 s run.
  - That is a margin, not a guarantee. Within one `model_call`, `model_runtime` can retry and wait again after a
    failed attempt, so one call can run past its 120 s. Usually, though, the owner answers or fails before the
    tester's client gives up.
  - The end of the try cancels the owner sooner: `owner_server` sets the owner's cancel, and `await_lease` stops on it.
  - A try that has already ended cancels no one. `owner_channel` sets `closing` as soon as the try's body ends, before
    its port cleanup, and `owner_server`'s teardown then cancels the owner. When an owner call ends after `closing` is
    set, `answer()` records the failure but leaves the tester's `role_cancel` alone. That event is shared with the
    other G10 tester and with this tester's next try.
  - One lock, `CLOSING_LOCK`, makes the check atomic. `answer()` holds it while it checks `closing` and sets
    `role_cancel`, and every `closing.set()` holds it too. So an owner failure can't cancel a try that is ending at
    that moment.
  - We did not use "the tester's remaining try time" as the ceiling. The client stops waiting at 600 s, so a longer owner
    wait would mean telling the tester something new (see below).
- What a real owner failure is booked as:
  - An owner that never gets a lane stops as its `ProviderWait`. The engine labels it with `classify_wait`, by the
    wait's reason: `router:capacity`, `router:quota`, `router:rate` or `router:no_route`. All are PROVIDER_LIMIT, a wait
    the engine sleeps out, not waste.
  - The early probe (`run.early_probe`) re-raises `provider_wait`. So a probe whose owner never gets a lane now stops
    the step as a provider wait. Before, the probe was skipped, because the error reached it as `cancelled`.
  - A model or transport error keeps its own stop, for example `router:process_error`.
  - The owner's own `timeout` or `call_limit` becomes `owner_invalid_answer` (`infra:owner_invalid_answer`).
    `run._author_try` scores a try that ends on `timeout` or `call_limit` as the tester's own cap. So an unmasked
    owner timeout would otherwise have scored the try.
  - A try can end cleanly while its question is still with the owner, for example when the tester's CLI drops
    ask-human on its own command timeout. The owner may be waiting for a lane, or its model may still be answering.
    The teardown's cancel then reaches the owner as `cancelled`. The stop becomes `owner_closed_unanswered`
    (`infra:owner_closed_unanswered`, INFRA_ERROR).
    - The try stays unscored, as before. A try that ends on its own cap keeps that cap.
    - It counts against `max_infra_retries_per_step` and leads to diagnosis like any other infra stop, as
      `infra:cancelled` did.
    - The money is unchanged: it is booked as waste exactly as `infra:cancelled` is today. The gain is a truthful
      label for diagnosis, distinct from `infra:cancelled`.
    - It is registered in `durable/classify.py` and `durable/stop_registry.py` (an open bug class, call scope).
    - We tried a provider wait here and reverted it (goldfish diff 3). A PROVIDER_LIMIT that spent money is waste
      too (`policy.settles_as_waste`). And `policy.decide` sleeps on every PROVIDER_LIMIT without counting it, so a
      trigger that keeps happening would rerun paid G10 tries every 900 s forever and never reach diagnosis.

**Unchanged (exam conditions).** When the owner fails:
- the tester is still cancelled;
- the try is still not scored;
- the tester is told nothing new.

Both ask-human and the protocol are unchanged.

**Needs a founder ruling (not built).** An owner failure could leave the try running instead of cancelling it:
- the tester would get ask-human's error and carry on, with the try scored, or the try rerun;
- or the owner could wait longer than ask-human's 600 s, with a longer client timeout.

Both change what the tester is told or how a try is scored.

**Open point.** A tester CLI's own command timeout (2 min by default in some CLIs) can stop ask-human before the owner
answers. That already happened when an answer took more than 2 min (up to 120 s lane wait plus 120 s run). The longer
lane wait makes it more likely. This is the tester's own tool, not an owner failure, and the try keeps going as it does
today.

**Identity.** `factory/exam_responder.py` is one of G10's and G16/G17's stage dependencies
(`gate_state.STAGE_DEPENDENCIES`). It is also in the exam calibration identity (`run.calibration_identity`'s `owner.files`)
and in `exam_responder.contract`.
- Saved strong-tester exam tries are set aside, and G10, G16 and G17 rerun on any case past them.
- `exam_responder.contract`'s `code_sha256` changes too. Both `sealed_audit.verify_exam_metadata` and `bin/run-exam`
  compare a sealed card's `owner_contract` with the current one. So every case sealed before this change must be
  requalified (G10 rerun) before the exam will admit it. No case is sealed yet.
- The blind (easy) and statement (judge breadth) identities do not change.
- Only `g10` changed in `run.py`, and `g10` is outside `sealed_audit.delivery_contract`'s roots: the pin does not change.
- No `VERDICT_CODE` file changed, so `invalid-runs-compat.json` needs no repin.

## Murphy rows

The register is not on main. The new row, to be numbered at merge:
- `new-owner-answer-cancel-1`: an exam owner answer with no free lane in 120 s cancels the strong tester, and three
  masks report `infra:cancelled` instead of the owner's error. Closed by `tests/factory/test_exam_responder.py`
  `OwnerFailureTests` (nine tests). The first six fail on the old code.
  - `test_a_try_that_ends_during_a_lane_wait_cancels_no_one` checks that a try ending during a lane wait leaves
    `role_cancel` clear, both on a clean end and on the tester's own timeout.
  - `test_a_try_that_ends_during_the_first_wait_or_answer_is_a_counted_infra_stop` is the diff-2 reviewer's probe.
    It also checks that the stop is `infra:owner_closed_unanswered` with no provider sleep.
  - `test_an_owner_failure_during_the_port_cleanup_cancels_no_one`.
  - `test_a_tester_cap_racing_an_owner_failure_stays_the_tester_cap`.
