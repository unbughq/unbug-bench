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
  - `owner_server` raises the owner's failure when that failure was recorded before the body ended (it is what
    cancelled the tester).
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
  - So the owner always answers or fails before the tester's client gives up. The tester never gets a client timeout
    that the old code could not produce.
  - The end of the try cancels the owner sooner: `owner_server` sets the owner's cancel, and `await_lease` stops on it.
  - We did not use "the tester's remaining try time" as the ceiling. The client stops waiting at 600 s, so a longer owner
    wait would mean telling the tester something new (see below).
- What a real owner failure is booked as:
  - An owner that never gets a lane stops as its `ProviderWait`. That classifies as `router:provider_wait`
    (PROVIDER_LIMIT, a wait the engine sleeps out, not waste).
  - A model or transport error keeps its own stop, for example `router:process_error`.
  - The owner's own `timeout` or `call_limit` becomes `owner_invalid_answer` (`infra:owner_invalid_answer`).
    `run._author_try` scores a try that ends on `timeout` or `call_limit` as the tester's own cap. So an unmasked
    owner timeout would otherwise have scored the try.
  - When a try ends while its owner is still waiting for a lane, the stop is that wait, not `cancelled`.

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
- The blind (easy) and statement (judge breadth) identities do not change.
- Only `g10` changed in `run.py`, and `g10` is outside `sealed_audit.delivery_contract`'s roots: the pin does not change.
- No `VERDICT_CODE` file changed, so `invalid-runs-compat.json` needs no repin.

## Murphy rows

The register is not on main. The new row, to be numbered at merge:
- `new-owner-answer-cancel-1`: an exam owner answer with no free lane in 120 s cancels the strong tester, and three
  masks report `infra:cancelled` instead of the owner's error. Closed by `tests/factory/test_exam_responder.py`
  `OwnerFailureTests` (all six fail on the old code).
