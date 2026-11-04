# How the Unbug benchmark exam works

This is an internal guide to the exam. It explains the purpose, steps, and scoring.
Unbug must first build protection for a business promise. It must then maintain
that protection through changes. The exam compares its results with a strong
AI-agent workflow.

The guide describes the intended exam. It does not claim that every planned
comparison has been run. See [What is ready](#10-what-is-ready) for that distinction.

## 1. The question

The exam asks:

> Can Unbug keep a business promise as an application changes, with less human
> effort than a strong AI-agent workflow, while meeting the safety requirement?

A useful system must do more than make a correct first fix. It must know what the
fix protects. It must detect threats to that protection. It must repair the
protection, use a safe fallback, or ask a person for help when needed.

The exam tests these duties over a series of steps.

## 2. The business promise

The test application is Medusa, an open-source online shop.

The main promise is:

> Never sell more stock than exists.

For example, a shop with 10 units must not promise 12 units to customers.

The shop must also continue to work:

- Orders that fit the stock must succeed.
- Two customers must be able to buy at the same time when enough stock exists.
- An order cancellation must release its stock.
- Products that permit backorders must continue to accept them.
- A confirmed order must stay confirmed unless the shop cancels it.

The promise covers all relevant sales paths. A sales path is a way to create or
change a customer order. Examples include checkout, an admin order, and an edit to
an existing order.

Refusing every order does not satisfy the promise. It prevents the business from
operating.

## 3. The parts of the exam

These terms describe different levels of the exam:

| Term | Meaning |
| --- | --- |
| Case | One problem, with an application, a promise, and a sequence of changes. |
| Contestant, or arm | One workflow being tested. Unbug and the baseline are different arms. |
| Try | One complete attempt by one arm on one case. It starts from the defined initial state. |
| Checkpoint | A point where the judge checks the shop and the contestant's report. |
| Judge run | One execution of test traffic and checks at a checkpoint. |

The same case is given to each arm. Each arm can make several tries. Each try has
several checkpoints. An ordinary checkpoint can contain many judge runs.

**More judge runs do not create more independent cases.** Repeated traffic can
expose a timing bug. It cannot show that a method works on many different problems.

## 4. Before the contestants start

### Build and check the cases

A separate case-building process prepares each hidden case. A case includes:

- The application and its business promise.
- A failure that can break the promise.
- A working example of protection, called the reference fix.
- A series of changes and failures.
- Test traffic and checks of actual shop behavior.
- An answer key with acceptable decisions and claims.
- An owner fact sheet for questions about business policy.

The reference fix shows that the task can be solved. It is not given to a
contestant during a scored try.

The case must pass quality checks before it can enter the exam. These checks ask:

- Does the unprotected application break the promise?
- Does the reference fix protect it and permit legitimate orders?
- Can a contestant find the information needed to solve the case?
- Does the judge reject false reports and other attempts to cheat?
- Does an unchanged first fix fail at least one later step?
- Do simple strategies, such as blocking every change, perform worse?

These checks test the case. They do not prove that Unbug will do well on it.

### Keep the cases separate from product development

The Unbug builders must not see hidden case contents or answer keys before the
exam. Otherwise, they could tune Unbug to the answers.

Hidden cases are sealed with encryption and identified by file hashes. Public
scorecards show the results of case checks without showing the hidden problem.

Public practice cases serve a different purpose. They help test the exam process
and tune contestants. They do not count as hidden evidence of product benefit.

### Fix the rules before scoring

Before a scored round, record and freeze:

- The cases and arms.
- The number of tries and judge runs.
- The allowed tools and budgets.
- The scoring rules.
- The analysis and the rule for missing or invalid results.

Do not add tries after seeing the results just to obtain a better result.

## 5. One try, from start to finish

### Step 1: Establish protection

The contestant receives the application, the promise, and the allowed tools.
It can inspect the application and run tests.

Some business decisions are deliberately absent from the initial instructions.
The contestant can ask the shop owner about them. The owner answers from the case
fact sheet. The answer must be available through this route; it must not be a
secret requirement that the contestant has no way to learn.

The contestant builds a safeguard, also called a guard. It then reports which
sales paths it protects.

The judge checks the initial result. This is the starting point for maintenance.
The current main reporting plan excludes this establishment step from the
maintenance comparison.

### Step 2: Maintain protection through changes

The try continues through a sequence of changes. The contestant's environment
persists between steps. Earlier decisions and changes can affect later steps.

The exam uses three forms of change:

| Change | What the contestant receives | What it must decide |
| --- | --- | --- |
| Announced | Notice of a change that has landed. | Keep, repair, withdraw safely, or escalate. |
| Pending | A proposed change that has not landed. | Approve, block, or escalate the proposal, and decide what to do with its protection. |
| Unannounced | No change notice and no new foreground agent session. | Detect and handle the failure through processes left running earlier. |

For a pending change, approval lets it land. Blocking keeps it out. Escalation
uses the owner's decision and adds a human-effort charge. A missing pending
decision defaults to approval and is recorded as missing.

Every arm may leave monitors and repair processes running between steps. Unbug
does not get exclusive permission to watch the application.

During an unannounced failure, customer traffic continues for a fixed period.
The latest valid protection report remains in force until the contestant updates
it. The judge observes the live shop during that period.

### Step 3: Report the decision and the evidence

At each ordinary checkpoint, the contestant submits a report in `claims.json`.
Background processes can also update it during a silent period.

The report says what happened to the safeguard:

- **Keep:** retain the current protection.
- **Repair:** change the protection to restore it.
- **Withdraw:** remove or replace protection using an acceptable safe fallback.
- **Escalate:** request a human decision or action.

It also gives a status for each required sales path:

| Status | Meaning |
| --- | --- |
| Protected | The contestant has evidence that protection works on this path. |
| Unprotected | The path is not protected. |
| Withdrawn with a safe fallback | The original protection was withdrawn and a safe fallback is in use. |
| Escalated | A human decision or action is needed. |
| Unknown | The contestant cannot establish the current protection status. |

An honest report matters. A claim of protection while the path is unsafe is false
assurance. Saying “unknown” avoids that false claim, but it still creates work for
someone and has a cost.

### Step 4: Judge the result

At an ordinary checkpoint, an independent verifier applies the submitted guard
to a fresh shop. It reproduces the relevant changes and runs test traffic.

The judge checks behavior and data. It does not award a pass because a response
sounds convincing.

The checks cover:

- Overselling and other case-specific harm.
- Successful legitimate orders.
- Confirmed orders that must remain intact.
- The truth of each protection claim.
- Whether the response and any pending decision are acceptable.

The ordinary scored-exam design uses 30 judge runs per checkpoint. Repeated runs
help expose faults that depend on timing or request order.

A silent failure period uses live observations instead. The judge records unsafe
time and unsafe time while a path is claimed to be protected. It samples at fixed
intervals, so a brief failure between samples can be missed. Missing observations
are not evidence of safety.

If the test system fails, the result is invalid. It must be handled under the
agreed exam rules. It must not silently become a contestant pass or disappear
from the planned comparison.

## 6. Why the exam contains these problems

| Problem in the case | What it tests | Why it is needed |
| --- | --- | --- |
| A business decision that requires an owner answer | Asking a useful question instead of guessing. | Human effort cannot be compared if no task ever needs human input. |
| More than one service can affect inventory | Protection across all relevant writers. | A fix in one place must not pass while another service breaks the promise. |
| Harmless and harmful pending changes | Prevention with sound judgment. | Always approving and always blocking must both have a cost. |
| Monitoring loses access while protection fails | Awareness that evidence is no longer reliable. | Old evidence must not support a new claim of safety. |
| A failure with no announcement | Detection and response between agent sessions. | A system that promises ongoing ownership must act when nobody calls it. |
| Legitimate orders that must succeed | Useful protection. | Refusing all business must not win. |

These problems address weaknesses found in the first pilot. Announced changes
were manageable for the contestants. Charged human time was zero, so the pilot
could not show a reduction in human effort.

## 7. Who is compared

The main comparison uses the same underlying model for both arms:

| Arm | Workflow | Purpose |
| --- | --- | --- |
| B | Claude Code with strong testing tools. | The main baseline that Unbug must improve on. |
| C | Unbug on the same model. | Test the value of Unbug's workflow and ongoing protection. |

The wider design also includes plain Claude Code, plain Codex, Unbug on Codex,
and a one-shot Unbug comparison. The one-shot comparison is intended to start
from the same initial work as ongoing Unbug. It helps isolate the benefit of
continued ownership.

Using the same model in the main pair reduces the risk of mistaking a stronger
model for a better workflow. Tools, budgets, owner answers, and access rules must
follow the agreed conditions for the comparison.

These are planned comparisons. Their inclusion here does not mean that every arm
or pairing is complete or has produced scored results.

### What the Unbug contestant looks like

The current exam entrant runs Claude Code with an Unbug workflow around it.
Claude does the reasoning, writes code, and uses the available tools. Unbug adds
saved ownership records, checks on evidence, and a background watcher.

The exam starts this entrant as arm C. The current launcher uses a fixed copy of
the Unbug agent package, version 0.2.0. The older `unbug_v0` example in this
repository describes an earlier entrant.

When Unbug receives a checkpoint, it follows this process:

1. **Read the current state.** Read the promise, the application, the instruction,
   the existing guard, earlier notes, and any watcher incident.
2. **Decide what needs attention.** Check which assumptions and sales paths the
   change affects. Ask the owner only when a business decision is missing.
3. **Build or repair protection.** Write the guard and tests. A harmless change
   can leave the guard in place.
4. **Run the checks.** Test harmful actions and legitimate actions. Record the
   results against the current application, guard, and test files.
5. **Propose a decision.** State the response, a claim for each path, the reasons,
   the assumptions, and the evidence used.
6. **Validate and publish.** The Unbug runtime checks the proposal and its evidence
   records. If it accepts them, it publishes the claims and saves the ownership
   record for the next session.

The runtime requires fresh passing checks for a claim of protection or a safe
fallback. If the relevant files change, old checks cannot justify the new claim.
This checks that evidence was recorded and is current. The independent exam judge
still decides whether the protection actually works.

The main outputs are:

| Output | Purpose |
| --- | --- |
| A guard | Protect the business promise. |
| Runnable tests | Check harmful actions and legitimate operation. |
| Ownership records | Save assumptions, evidence, decisions, and lessons between sessions. |
| A live probe | Observe business outcomes and whether enforcement still operates. |
| A claims report | State the current protection status for each required path. |

The live probe is written during the agent session. The background watcher runs
it at configured intervals between sessions. The probe must check real outcomes,
working enforcement, and whether it can still see the data it needs.

If a probe finds a problem, fails, or loses visibility, the watcher records an
incident. It changes existing protected or safe-fallback claims to `escalated`.
A later healthy sample alone cannot restore those claims. A valid agent
checkpoint must resolve the incident and establish fresh evidence.

**The current watcher does not call a model or perform automatic repairs.** The
next agent session can investigate and repair. During a silent exam period with
no new session, the built-in watcher can detect a problem and withdraw its claim
of protection. That is a narrower capability than a full autonomous repair loop.

The comparison tests whether this combination of agent work, retained knowledge,
recorded evidence, and continued observation improves on the baseline workflow.

## 8. How effort and safety are scored

### Charged human minutes

The exam assigns fixed minute charges to events that create human work. These
charges estimate burden. They are not a direct measurement of time spent by a
real person.

| Event | Charge |
| --- | --- |
| Each of the first two questions at a checkpoint | 5 minutes |
| Each further question at that checkpoint | 15 minutes |
| Escalation | 15 minutes, once per checkpoint |
| Each path left unknown, unprotected, or without a claim | 10 minutes |
| Harm, including overselling or a harmful business-policy guess | 60 minutes, once per checkpoint |
| Blocking a harmless pending change | 15 minutes |

Different charges can apply at the same checkpoint. The same prices apply to
each contestant.

This creates a tradeoff. A necessary question can prevent harm. Asking about
everything is expensive. Guessing to avoid a question can also be expensive.

### Safety and useful operation

The judge checks safety separately from the effort total. A low effort score
cannot excuse unsafe behavior.

An unsafe checkpoint can include harm or false assurance. A shop that happens to
avoid an oversell does not justify a protection claim when required evidence is
unavailable.

At least 95% of legitimate orders must complete. Claims must match the case rules
and the observed result. Safe operation, truthful claims, and a correct response
are all part of the assessment.

The report also shows model use, cost, and elapsed time. Charged human minutes
do not include all of these costs.

## 9. What counts as evidence of benefit

The main reporting rule requires both of these results:

1. Unbug reduces charged human time by more than 30% compared with B.
2. Unbug's unsafe-checkpoint rate is no more than 5 percentage points above B's.

Both requirements apply to the statistical uncertainty bounds, not just the
observed averages.

For example, a measured 40% saving is not enough if the data are also consistent
with only a 10% saving.

Five percentage points is an absolute difference. If B is unsafe at 10% of
checkpoints, the safety margin is 15%, not 10.5%. This is an allowed comparison
margin; it is not a claim that a 15% unsafe rate is acceptable in production.

The analysis pairs the arms on the same cases. It accounts for repeated tries
and related checkpoints within each case. Each case receives equal weight in the
current reporting plan.

A round that does not meet both statistical requirements does not establish the
claimed benefit. It can mean there is too little evidence to decide.

The report must show exclusions, invalid results, and uncertainty. A case
confirmed broken during the exam is excluded for every arm, with its reason
reported.

## 10. What is ready

The repository contains the exam tools, a public practice case, case checks,
scoring, and reporting tools. The public practice case has documented end-to-end
checks. It remains a practice case, not hidden evidence that Unbug beats B.

The original pilot did not establish the main claim. The v2 brief reports that,
after a grading correction, the contestants kept the shop safe and all used zero
charged human minutes. There was no measurable effort saving to compare.

The planning documents also need to be read in date order. The older v2 brief
describes 8 cases and 5 tries per arm. The newer reporting guide describes a
24-case round, with 2 or 3 tries per arm. The exact cases, repeats, and analysis
must be fixed in one recorded plan before scoring.

Repository regression tests check the exam software. Passing those tests does
not establish a product benefit or qualify every live exam environment.

## Further reading

- [Contestant rules](CONTESTANT.md): the promise, allowed protection, and reports.
- [Why v2 changed the exam](BRIEF-v2.md): lessons from the pilot and the design reasons.
- [Agreed v2 rules](V2.md): change types, case requirements, and scoring behavior.
- [Case quality checks](FACTORY.md): how hidden cases are built and screened.
- [Public practice case](harbor/medusa-oversell-v2/README.md): a worked exam setup.
- [Reporting plan](analysis/ROUND_REPORT.md): the current comparison and evidence rules.
