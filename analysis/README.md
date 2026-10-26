# Proposed statistics for v2

## Reporting the 2026-10-17 measurement round

The founder chose **24 cases, rule C, no interim look**: three tries per arm if
budget allows, otherwise two plus a third on a subset fixed before scoring.
A non-pass means **not enough data to tell**, not “Unbug failed”.

`report_round.py` writes JSON with the numbers/audit trail and a short Markdown
explanation. Each case counts equally, including cases with an extra try.

- **Effect:** charged-time saving `1 − C/B` and unsafe-rate difference `C − B`,
  with paired case-then-try bootstrap intervals. Rule C requires a one-sided 95%
  lower saving bound above 30% and upper safety bound at most +5 points. A collapsed
  safety interval cannot establish safety. Newcombe is comparison only.
- **Repeatability:** how often two tries disagree at the same checkpoint, with
  kappa alongside and case-bootstrap intervals. Kappa depends on how rare a label is.
- **Noise and next-round cost:** case versus repeat variance, per arm and paired
  difference. Minutes use `log(1 + minutes)` to retain zeros. The frozen sizing scan
  uses measured components, a true 50% saving/equal-safety alternative, and reports
  cases needed at two and three tries for an 80% joint-power target. Model checks,
  uncertainty and the “undetermined” outcome stay visible; no adding to this round.
- **Secondary checks:** a sceptical Bayesian prior (0 saving/0 safety difference;
  SDs 35/10 percentage points), a prior-sensitivity table and synthetic error-rate
  record; log-minute and logistic mixed models with bootstrap intervals and visible
  singular/non-converged fits; and CUPED adjustment using only frozen factory,
  tester, scripted-strategy and ingredient covariates. A posterior around **70% is
  weak evidence, not a finding**. These checks never change rule C. The Bayesian
  model is a Gaussian try-summary approximation with case/try covariance; bootstrap
  variance remains the sizing reference when mixed models disagree.

[Reporting and freeze guide](ROUND_REPORT.md) gives the exact sizing rule, priors,
input formats, checkpoint alignment, covariate restrictions and remote commands.
Never use establishment or any contestant output as a covariate. No item response
models or unregistered subgroup searches are implemented.

```bash
/tmp/unbug-steadiness-venv/bin/python -B analysis/report_round.py --self-test
/tmp/unbug-steadiness-venv/bin/python -B analysis/report_round.py \
  analysis/fixtures/measurement-round --design analysis/fixtures/measurement-round/design.json \
  --quick --bootstrap 99 --out /tmp/synthetic-round
```

The fixture and its outputs are synthetic, not evidence about Unbug. Quick mode
cannot recommend a size. Full scans/calibration run detached on the **existing**
Hetzner server, at `nice -n 10`, with at most three compute processes. Freeze the
real case/try/step design, third-try subset, analysis and synthetic calibration
before scoring. Do not create/delete servers or run `hcloud-dev down`.

Full validation examples: [plain-language summary](round_synthetic.md) and
[JSON estimates and diagnostics](round_synthetic.json). All self-tests passed;
both mixed models flagged singular fits, CUPED made the weak fixture covariates
worse, and the 196 binary-checkpoint calibration studies had zero joint `P>0.95`
crossings (0/49 in each scenario; 95% upper error bound 7.3%). These are synthetic
validation results, not a finding about Unbug.

## Expanded secondary false-win calibration (2026-10-17)

[Runner and self-check](calibrate_secondary.py); [JSON with all study records,
versions and source hashes](secondary_calibration.json). **2,500 studies per
scenario/design, 20,000 total, seed 20261019**. This reruns the
[existing check](secondary_round.py)'s unchanged sceptical prior and joint
**P(saving >30% AND safety difference ≤+5 points) >95%** threshold. The binary
checkpoint/discrete-charge generator is unchanged (baseline unsafe 15%, 30
minutes/checkpoint, 4–6 checkpoints, steadiness 0). Both analyses see the same
studies; two-try designs retain the first two of three generated tries.

Joint false-win/pass rates below retain the original 600-draw/400-burn-in,
two-chain calibration. Parentheses are **exact one-sided 95% Clopper–Pearson
upper bounds**, pointwise per scenario. Every tabulated upper bound is within
**0.63 percentage points** of its estimate, meeting the one-point aim.
Rule C uses [`steadiness.t_statistics/t_flags`](steadiness.py), alpha .05,
23 case degrees of freedom, paired case/try SE and the existing guards.

| Design | Synthetic truth | Bayesian joint win (upper) | Rule C joint pass (upper) |
|---|---|---:|---:|
| 24×3 | No saving; equal safety | 0.00% (0.12%) | 0.00% (0.12%) |
| 24×3 | 30% saving; equal safety | 0.96% (1.35%) | 1.48% (1.94%) |
| 24×3 | 50% saving; safety +5 points | 2.96% (3.58%) | 2.16% (2.70%) |
| 24×3 | 30% saving; safety +5 points | 0.44% (0.73%) | 0.72% (1.07%) |
| 24×2 | No saving; equal safety | 0.00% (0.12%) | 0.00% (0.12%) |
| 24×2 | 30% saving; equal safety | 0.80% (1.16%) | 1.96% (2.48%) |
| 24×2 | 50% saving; safety +5 points | 2.12% (2.66%) | 2.88% (3.49%) |
| 24×2 | 30% saving; safety +5 points | 0.16% (0.37%) | 0.44% (0.73%) |

**Freeze the sceptical prior and 95% joint threshold as-is for this secondary
check; no change is needed. The primary rule was not changed.** These are
model-conditional results at the specified nulls; +5 points is the safety
non-inferiority boundary, not a loss strictly beyond the margin. At equal safety,
safety non-inferiority alone is true and its crossings are not false wins.

There were 188 independent longer refits near the joint threshold (4,000
draws/chain, 2,000 burn-in). Refined safety-boundary rates are **3.00% (upper
3.62%) at 24×3**, **2.52% (upper 3.10%) at 24×2**. All 37 poor-diagnostic studies
remain included. Even counting every original/refined win, remaining joint
threshold ambiguity, and initial/final poor-diagnostic fit as a win gives at most
**102/2,500 = 4.08%, upper 4.79%** (24×2/safety boundary; 24×3: 92/2,500 = 3.68%,
upper 4.36%). This sensitivity is not a mathematical bound on MCMC error.

The dedicated labelled Hetzner `bayes` cx33 ran for **83.7 minutes**, four workers
at nice 10, single-thread BLAS; results were pulled/verified and the server deleted.
The local single-core benchmark was 0.34 s/study. Versions: Python 3.12.3, NumPy
2.5.4, SciPy 1.18.1. Include/hash this standalone JSON alongside the old full
`round_synthetic.json`: the existing loader still requires that legacy 49-study
format. `report_round.py` currently reports bootstrap intervals; this comparison
uses the requested t-based implementation without changing that reporting path.

```bash
# Runnable local self-check (about one second):
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 \
  /tmp/unbug-steadiness-venv/bin/python -B analysis/calibrate_secondary.py --self-test
# Full rerun; /tmp/bayes-venv needs the pinned numpy/scipy versions above:
HCLOUD_DEV=bayes bin/hcloud-dev run 'nohup env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 nice -n 10 /tmp/bayes-venv/bin/python -u -B analysis/calibrate_secondary.py --studies 2500 --workers 4 > /tmp/bayes-calibration.log 2>&1 < /dev/null &'
HCLOUD_DEV=bayes bin/hcloud-dev pull /home/user/unbug-bench/analysis/secondary_calibration.json
# Verify/copy results/remote/secondary_calibration.json into analysis/, then always:
HCLOUD_DEV=bayes bin/hcloud-dev down
```

The historical planning studies below are proposals for the founder to decide at the protocol freeze.
These numbers do not change the protocol. No scored results were used.

## What the pilot tells us

The ten Harbor archives contain 40 checkpoints on one case. All charged human
minutes are zero. The oracle found no oversells. Each archive has one try.
That cannot tell us how much different cases or positive human charges vary.
There is no measured percentage saving when both arms cost zero.

The original round-one files still mark four checkpoints unsafe for false
assurance. The brief says these were grading errors and were corrected. The
report data files retain those original scores too. The audit preserves them;
it does not silently rewrite them. All per-step rewards match their checkpoint
files and the three report data files. The rounds are not independent new cases.

The pilot used four checkpoints, including establishment. Round one used 30
judge runs per checkpoint; round two used 10. Judge runs are not extra tries.
The new study models 4–6 scored maintenance checkpoints per try and five tries
per arm per case. Real analysis must select maintenance rows before calling it.

## What eight cases can show

Eight cases give 40 tries per arm, or about 200 checkpoints. The independent
case count is still eight. More checks on the same case do not replace new cases.

The main example assumes both arms are unsafe at 15% of checkpoints. Baseline
charges average 30 minutes per checkpoint, or about 150 minutes per try.
These are planning assumptions, not pilot estimates or forecasts.

With no true difference in time or safety, the chance of claiming both benefits
is 0–0.3% in the tested range of variation. Safety alone passes about 11–16%.
Equal safety is allowed by the five-point margin. Passing that part is not a
false positive for non-inferiority. The study falsifies the full hypothesis
about 17–75% of the time; the rest is mostly inconclusive.

If time really falls by exactly 30%, only about 1–3% of studies prove a saving
above 30%. No finite sample gives an honest test 80% power at that boundary.
The same problem applies if safety is truly exactly five points worse.

If time really falls by 50% and safety stays equal, eight cases pass the time
rule about 9–48% of the time. They pass both rules about 4–16% of the time.
Eight cases are useful for finding large problems. They are a weak basis for
declaring the full product claim proven.

At eight cases, the smallest tested saving with 80% time-rule power is 65%
under low variation. Neither the middle nor high variation reaches 80% at a
69% saving. Those are grid limits, not exact thresholds. In this example,
unchanged harm charges already cost nine minutes per checkpoint. They cap
possible savings at 70% if safety stays equal.

To pass the safety rule in 80% of studies, the smallest tested true safety
improvements are 7.5, 10 and 12.5 percentage points for low, middle and high
variation. This means C is safer than B by those amounts. These are separate
endpoint results. They do not mean the joint claim has 80% power.

## Proposed decision and fixed sample

Call Unbug **clearly better** only after the full frozen sample, and only if:

- The upper end of the 95% interval for C minus B unsafe rate is at most +5 points.
- The lower end of the 95% interval for charged-minute saving is greater than 30%.
- Baseline charged minutes are positive and the safety interval has not collapsed.

Call the hypothesis falsified if the lower safety bound exceeds +5 points,
or the upper saving bound is below 30%. Other results are inconclusive.

The last condition is a proposed safeguard, not an existing protocol rule.
If all observed safety differences are zero, resampling gives a zero-width
interval. It cannot discover failures that were never observed. Treat that
result as insufficient evidence of safety. The code reports both the literal
protocol decision and the decision with this safeguard. The safeguard does not
solve every problem with having few cases.

More all-safe cases still give a collapsed bootstrap. Freeze a different valid
interval method if this outcome is expected.

The case-count scan tests equal safety and a true 50% saving. It reports the
first tested size with 80% success, and the first whose simulation uncertainty
also clears 80%. These are conditional planning numbers, not guarantees.
The first tested sizes are 64, 128 and 256 cases for low, middle and high
variation. Joint success is 85%, 88% and 91%, respectively. The simulation
intervals are 81–88%, 85–91% and 88–93%.

**Proposed fixed sample: 256 cases × 5 tries per arm** if the goal is to have
at least 80% chance of proving both claims under all three tested levels at
a true 50% saving and 15% baseline unsafe rate. That is 1,280 tries per arm.
This does not promise 80% power for every possible base rate or cost pattern.
If that is too costly, keep eight cases and label the study exploratory.

Choose a case count before freeze. Do not add cases or tries after seeing scores.
Do not stop early because results look good. At an exact 30% true saving, no
recommended case count can provide 80% success under the current decision rule.

## Assumptions to freeze

The code tries unsafe rates of 1%, 5%, 15% and 25%, plus the pilot's zero-charge
floor. The 25% value is a stress test, not the corrected pilot failure rate.

Cases share some difficulty across arms. Additional variation specific to an
arm on a case ranges from none to high. The `case_rho` values are 0, .03 and .10.
Within-try values are .05, .20 and .40. Larger values make checkpoints from the
same try more alike. These are input settings, not fitted measurements.
The shared case value is .05. The spread of positive minute demand also varies
by case (.15, .40, .80) and try (.35, .70, 1.10) on a log scale.

Charges combine 60-minute harmful outcomes with other costs in five-minute
units. This is a model of total charges. It does not model individual questions
or every pricing tier. By default every unsafe checkpoint is harmful. Set
`--harm-fraction` lower to model false assurance without a harm charge. Harm
and total minutes are therefore related; the endpoints are not independent.
Some requested savings are impossible when unchanged harm charges exceed the
target total. The code rejects those inputs.

The default assumes no extra matching of step outcomes beyond shared cases.
`--paired-uniform .5` tests stronger matching from shared seeds. Both arms
always have the same step count and matched try IDs. Cases and try IDs are
resampled together across arms. Checkpoints stay together within their try.

Every case gets equal weight. Every try within a case gets equal weight.
Safety is the average of the tries' unsafe rates. Human cost is total charged
minutes per try. Saving is one minus mean C cost divided by mean B cost.
It is not the average of each try's percentage saving. These weights need to
be frozen too, especially if checkpoint counts differ.

The intervals use the middle 95% of the resampled values. With few cases they
may miss their stated coverage. The simulation reports coverage and checks
false safety wins when C is truly five points worse. Newcombe uses all
checkpoints as independent observations. It is shown only for comparison.
It must not rescue a failed clustered result.

In the three boundary checks, the safety rule passed about 0.8–2% of the time.
Some intervals covered the truth only 93% of the time under high variation.
This is a warning about precision, not proof that the method is always valid.

The default has 400 simulated studies and 499 resamples in each. A reported
probability near 50% has about ±5 points of simulation uncertainty. Each
probability includes its own 95% simulation interval. Effect and case searches
use a grid; they do not locate exact thresholds. Real-result analysis defaults
to 10,000 resamples. A larger pre-freeze simulation can refine planning numbers.

Eight cases cannot reliably measure writer-family bias. Removing the two cases
written by the contestant's own family leaves only six. That sensitivity check,
and all secondary endpoints, cannot rescue the primary result. This study says
nothing about other shops or promises.

## Options for the founder

**Proposals only.** These do not change the protocol. Each entry is the middle-variation
estimate, followed by the range across low, middle and high variation. These ranges are
not confidence intervals. Both arms are assumed unsafe at 15% of checkpoints, baseline
cost is 30 minutes per checkpoint, and each arm has five tries per case. Passing means
passing both endpoints, with the proposed noncollapsed-safety safeguard.

| Rule | What it claims | Pass if truly 50% cheaper: 8 cases | False pass if no difference: 8 cases | Pass if truly 50% cheaper: 16 cases | False pass if no difference: 16 cases |
|---|---|---:|---:|---:|---:|
| Original (comparison) | Evidence of >30% saving; unsafe rate no more than 5 points worse. | 8.8% (3.8–15.8%) | 0% (0–0.2%) | 10.8% (6.2–23.8%) | 0% (0–0%) |
| A (proposal) | Evidence of some saving; estimate ≥30%; unsafe rate no more than 5 points worse. Does not prove a 30% saving. | 12.5% (8–16.2%) | 0.8% (0.2–1%) | 12.8% (11–24%) | 0.5% (0–1.2%) |
| B (proposal) | A with a 10-point safety margin. This weakens the safety claim. | 33% (17.8–57%) | 1.2% (0.2–2.2%) | 57.2% (35–85%) | 0.5% (0–2.5%) |
| C (proposal) | Original effect thresholds; one-sided 5% tests (central 90% limits). | 15.5% (7.2–24%) | 0% (0–0.2%) | 18% (11.8–37.8%) | 0% (0–0.2%) |

**Proposed recommendation:** use C with 24 cases × 5 tries if affordable, or 16 × 5 as an
exploratory study. Keep the five-point safety margin. At 24 cases C passes 34% of the
middle-setting studies (15–51% across variation settings), even with a true 50% saving.
None of A, B or C reliably reaches 80% joint power at 8–24 cases × 5 tries across the
original three variation settings. A failure to pass should not be treated as proof that
Unbug has no useful benefit.

C is the preferred single change **for preserving the size and safety claims**: at 8/16
cases it adds 6.75/7.25 percentage points of middle-setting power, versus 3.75/2 points
for A. Changing only the safety margin to ten points adds more raw power (8.75/18 points),
but doubles the permitted worsening; B combines that change with A. There is no common
numeric unit for weaker confidence, a weaker saving claim and weaker safety. At a 5%
base unsafe rate, a ten-point margin permits a tripling to 15%, so that tradeoff matters.

## Round-two simulation details (proposals)

All results below use the same model, weighting, paired case/try resampling, and seed
`20261016` as round one. Every rule sees the same studies and bootstrap draws within a
scenario. All 13 overlapping scenarios reproduce round-one guarded and literal joint
probabilities exactly. There are 400 studies and 499 bootstrap resamples per scenario,
384 feasible scenarios, and 24 explicitly impossible combinations. Each endpoint and
joint probability, its count and its 95% Monte Carlo interval are in
[`options_results.json`](options_results.json). Around 50%, Monte Carlo uncertainty is
about ±5 percentage points; zero observed passes in 400 studies still has a 95% upper
limit near 0.95%. Small differences should not drive the decision.

**C terminology:** the requested alpha .05 one-sided test uses the 5th/95th percentiles.
These are 95% one-sided bounds, or a central 90% interval. A literal 90% one-sided bound
would use the 10th/90th percentiles and alpha .10; that is not the proposal simulated.
Nominal confidence is not guaranteed with few cases. C still has low power at exactly
30% true saving; changing the confidence level does not remove the boundary problem.

### True effect, case count and base unsafe rate

Five tries per arm per case; 30 baseline minutes per checkpoint; equal true safety.
Entries are middle estimates (range across variation settings). At 0% true saving,
a joint pass falsely claims a time benefit. At 15%, a pass is an overstatement against
a 30% target; for A/B it is not a type-I error for their narrower claim of some saving.
None of these equal-safety scenarios measures the chance of falsely clearing safety
when Unbug is actually worse than the permitted margin.

| Base unsafe rate | Cases | Proposed rule | Pass at true 30% saving | Pass at true 50% saving | False pass at true 0% saving | Pass below target at true 15% saving |
|---:|---:|---|---:|---:|---:|---:|
| 5% | 8 | A | 11.2% (5.8–28.2%) | 25% (12.2–47%) | 1% (0–2.5%) | 3.8% (2.8–3.8%) |
| 5% | 8 | B | 19.5% (9–48.2%) | 49.2% (22–90.2%) | 1.8% (0–3.5%) | 7.2% (4.2–7.2%) |
| 5% | 8 | C | 3.2% (1.8–3.2%) | 20% (10.5–51.2%) | 0.2% (0–1.2%) | 0.5% (0–2%) |
| 5% | 12 | A | 21% (6–39%) | 34.2% (13.8–62%) | 0.8% (0–1.5%) | 6% (2–6%) |
| 5% | 12 | B | 34.2% (9.5–53%) | 72.2% (23.2–97.2%) | 1% (0–2.8%) | 9% (2.8–9%) |
| 5% | 12 | C | 4.5% (3.5–4.5%) | 26.8% (9–67.8%) | 0% (0–0.2%) | 0.2% (0–1.8%) |
| 5% | 16 | A | 21.5% (7.5–41.8%) | 44% (22.5–72%) | 1.2% (0–1.5%) | 4.5% (1.5–4.5%) |
| 5% | 16 | B | 35.5% (12.8–51.5%) | 86.8% (39–99.5%) | 2% (0–2.5%) | 6.8% (1.5–7%) |
| 5% | 16 | C | 3.5% (3.2–5.2%) | 30.5% (17.8–80.2%) | 0% (0–0.8%) | 0% (0–0.5%) |
| 5% | 24 | A | 25.2% (12.8–46.8%) | 62% (30.2–85.5%) | 0.5% (0–1%) | 10.2% (0–10.2%) |
| 5% | 24 | B | 40.5% (20–51.7%) | 95% (52.5–100%) | 1% (0–2.2%) | 13% (0–13%) |
| 5% | 24 | C | 3% (1.5–3%) | 48.5% (16.8–91.2%) | 0% (0–0.2%) | 0.2% (0–1%) |
| 15% | 8 | A | 6% (2.8–17.2%) | 12.5% (8–16.2%) | 0.8% (0.2–1%) | 2.2% (1.8–2.2%) |
| 15% | 8 | B | 15.2% (7.5–43.5%) | 33% (17.8–57%) | 1.2% (0.2–2.2%) | 4.8% (3.5–4.8%) |
| 15% | 8 | C | 2% (1.8–5.2%) | 15.5% (7.2–24%) | 0% (0–0.2%) | 0.2% (0.2–1.2%) |
| 15% | 12 | A | 10.2% (3.2–18%) | 13.5% (10.5–19.8%) | 1% (0–1%) | 3.2% (2–3.2%) |
| 15% | 12 | B | 25% (7.8–42%) | 42.8% (23.5–72.5%) | 1.5% (0–1.5%) | 6% (2.5–6%) |
| 15% | 12 | C | 2.8% (2.5–2.8%) | 16% (8.8–31.2%) | 0% (0–0%) | 0% (0–0.2%) |
| 15% | 16 | A | 13% (5–20.2%) | 12.8% (11–24%) | 0.5% (0–1.2%) | 4.5% (1–4.5%) |
| 15% | 16 | B | 35.8% (12.8–50.2%) | 57.2% (35–85%) | 0.5% (0–2.5%) | 7.8% (1–7.8%) |
| 15% | 16 | C | 4.2% (1.2–4.2%) | 18% (11.8–37.8%) | 0% (0–0.2%) | 0% (0–0.8%) |
| 15% | 24 | A | 17.8% (9–31%) | 25.5% (14–35.5%) | 0.8% (0–1.2%) | 5% (0–5%) |
| 15% | 24 | B | 43% (18.2–49.2%) | 75% (47.2–96%) | 0.8% (0–1.8%) | 7.2% (0–7.2%) |
| 15% | 24 | C | 2.8% (2.2–3.2%) | 33.8% (15–51.2%) | 0% (0–0.2%) | 0% (0–0.2%) |
| 30% | 8 | A | 5.5% (5.5–12.2%) | Impossible | 1% (0.2–1%) | 5.5% (2.8–5.5%) |
| 30% | 8 | B | 17.2% (10.8–33.2%) | Impossible | 1% (0.2–1.5%) | 10.8% (3.8–10.8%) |
| 30% | 8 | C | 2.8% (2.8–4%) | Impossible | 0% (0–0.2%) | 0% (0–0.8%) |
| 30% | 12 | A | 7% (4.2–12%) | Impossible | 0.8% (0–1%) | 4.2% (1.8–4.2%) |
| 30% | 12 | B | 24.2% (14–39.5%) | Impossible | 0.8% (0–1.2%) | 6.2% (2.2–6.2%) |
| 30% | 12 | C | 2.5% (2–3.2%) | Impossible | 0% (0–0.2%) | 0% (0–0.8%) |
| 30% | 16 | A | 6.5% (6.2–11.2%) | Impossible | 0% (0–0.8%) | 4.8% (1.5–4.8%) |
| 30% | 16 | B | 30.2% (17.2–44.2%) | Impossible | 0.2% (0–1.5%) | 7.5% (1.5–7.5%) |
| 30% | 16 | C | 1.5% (1.5–1.5%) | Impossible | 0% (0–0%) | 0.2% (0–0.5%) |
| 30% | 24 | A | 13.5% (11.8–22.2%) | Impossible | 0.2% (0–1.2%) | 4.5% (0.2–4.5%) |
| 30% | 24 | B | 38.5% (28.2–52%) | Impossible | 0.2% (0–1.8%) | 5.5% (0.2–7.8%) |
| 30% | 24 | C | 3.8% (1.8–3.8%) | Impossible | 0% (0–0%) | 0% (0–0.2%) |

At a 30% unsafe rate, unchanged harm costs average 18 minutes per checkpoint.
With a 30-minute baseline, a 50% saving requires a 15-minute total, below that floor.
The maximum possible saving is 40%. Impossible cells are not zero-power estimates.
This is a constraint of the unchanged model, not a conclusion about actual Unbug costs.

### Explicit higher-cost sensitivity (proposed assumption)

The following panel raises baseline cost to **60** minutes per checkpoint for all three
unsafe rates, so a true 50% saving is feasible and rates can be compared at the same cost.
It changes one planning assumption and is not a forecast or a replacement for the
30-minute results. Five tries per case; true 50% saving and equal safety.

| Base unsafe rate | Cases | A pass | B pass | C pass |
|---:|---:|---:|---:|---:|
| 5% | 8 | 27.5% (12.2–46%) | 48.8% (17.8–93.5%) | 17.8% (8.2–51.5%) |
| 5% | 12 | 33.5% (13.8–58.8%) | 65.5% (26.8–97%) | 19.5% (9.8–64.5%) |
| 5% | 16 | 42% (16–68.5%) | 80% (31.8–100%) | 29% (12.5–76.8%) |
| 5% | 24 | 57.8% (22.5–83%) | 94.8% (47–100%) | 46.8% (12.2–90.2%) |
| 15% | 8 | 11.5% (3–15.2%) | 30.5% (9.8–53.8%) | 10.5% (3.5–22.2%) |
| 15% | 12 | 14% (6.5–16.8%) | 41.8% (16.8–71%) | 14.2% (5–30.2%) |
| 15% | 16 | 13.2% (8.5–28.2%) | 52.5% (22.5–87.5%) | 17.5% (6–44.8%) |
| 15% | 24 | 23.8% (12.5–37.5%) | 73.8% (40.2–97%) | 29% (8.5–52%) |
| 30% | 8 | 6% (5.2–6.8%) | 18.2% (11.5–31.5%) | 7.8% (5.2–12.2%) |
| 30% | 12 | 8.8% (6.5–13.5%) | 28.5% (16.2–49.2%) | 12.5% (7.2–19%) |
| 30% | 16 | 10.5% (6.8–13.2%) | 35.5% (18.2–56%) | 15% (5.8–23.2%) |
| 30% | 24 | 14.5% (9.5–21.5%) | 55% (29.8–81.8%) | 23% (10.2–33.5%) |

The full 30%-unsafe, 60-minute panel also includes true savings 0/15/30%, five and ten
tries per case, and all variation levels in the JSON. At 16 cases, middle variation,
the false-pass chances at 0% saving are A: 0.2%, B: 0.2%, C: 0%.
The corresponding chances of passing with only a 15% saving are A: 1.8%, B: 4.5%, C: 0%.

The corrected pilot cannot tell us which rate to use: it has only one case and no unsafe
checkpoints. Across this grid, collapsed safety intervals occur in up to 0.75% of
simulated studies and cannot pass the guarded rule. An all-safe scored sample always
collapses this empirical safety bootstrap, regardless of its size. Freeze a valid
alternative safety interval before scoring if that outcome is expected.

### More tries or more cases?

True 50% saving, equal safety at 15%, and the original 30-minute baseline. Entries are
middle estimates (variation range); try counts are per arm per case.

| Cases × tries | Original joint pass | A joint pass | B joint pass | C joint pass |
|---|---:|---:|---:|---:|
| 8 × 5 | 8.8% (3.8–15.8%) | 12.5% (8–16.2%) | 33% (17.8–57%) | 15.5% (7.2–24%) |
| 8 × 10 | 10.5% (6.2–26%) | 14% (10.8–27%) | 51.2% (22.5–85.5%) | 18% (10–38.8%) |
| 12 × 5 | 8.5% (4.5–19.8%) | 13.5% (10.5–19.8%) | 42.8% (23.5–72.5%) | 16% (8.8–31.2%) |
| 12 × 10 | 16.5% (8–35.2%) | 21.5% (15–35.5%) | 69.5% (38.2–95.8%) | 26% (14.2–50%) |
| 16 × 5 | 10.8% (6.2–23.8%) | 12.8% (11–24%) | 57.2% (35–85%) | 18% (11.8–37.8%) |
| 16 × 10 | 22.2% (6.2–50.5%) | 26.2% (14–50.5%) | 80.5% (42.8–99.8%) | 34% (14–63%) |
| 24 × 5 | 23.8% (8.8–35.5%) | 25.5% (14–35.5%) | 75% (47.2–96%) | 33.8% (15–51.2%) |
| 24 × 10 | 32.8% (14.5–68.2%) | 34.8% (24.2–68.2%) | 94.2% (65–100%) | 47.2% (23–84.2%) |

Doubling tries is useful, but cannot remove case-specific differences. At the same
80-try budget per arm, C gives 18% middle-setting power for both 8 × 10 and 16 × 5.
At 120 tries, 24 × 5 gives 34%, versus 26% for 12 × 10. B gives 57% versus 51% at
80 tries, and 75% versus 70% at 120. Differences at 80 tries are within simulation
uncertainty; prefer more cases when costs are comparable, because they broaden the
case sample. Under low variation, extra tries can work just as well. Extra tries do
not make 16 cases behave like 32 independent cases.

### Rerun round two

No packages, network, paid calls, protocol edits or commits are needed. Local worker
processes only distribute the simulation calculations; they do not run model agents.

```bash
python3 -B analysis/options_power.py --self-test
python3 -B analysis/options_power.py --workers 8
```

The default run takes about seven minutes on this machine and writes only
`analysis/options_results.json`. The runner leaves the original simulator and
bootstrap unchanged. All sample sizes and whichever proposed rule is selected must
be fixed before scores are seen.

## Rerun

No packages, network, paid services or commits are needed. NumPy was not installed.
From `~/Developer/unbug-bench`:

```bash
python3 -B analysis/cluster_bootstrap.py
python3 -B analysis/power.py --self-test
python3 -B analysis/power.py
```

The full run takes several minutes and writes `analysis/power_results.json`.
It extracts the archives into a temporary directory, reads them, and removes
that temporary directory. Original archives and report data stay unchanged.
The output includes archive hashes, original scores, reconciliation checks,
decision probabilities, interval coverage, effect grids and case-count grids.

A custom scenario and a more precise planning run:

```bash
python3 -B analysis/power.py --single --cases 8 --tries 5 \
  --base-rate .05 --base-minutes 15 --saving .5 \
  --case-rho .03 --try-rho .2 --minute-case-sd .4 --minute-try-sd .7 \
  --output analysis/custom_results.json
python3 -B analysis/power.py --simulations 2000 --bootstrap 1999 \
  --output analysis/refined_results.json
```

Three saved checks change one assumption at a time. They give joint success of
8% with stronger matching, 2% without harm charges on unsafe checkpoints, and
18% with a 5% unsafe rate and 15 baseline minutes per checkpoint. They support
the same warning about eight cases. Rerun them with:

```bash
python3 -B analysis/power.py --single --paired-uniform .5 \
  --output analysis/paired_sensitivity.json
python3 -B analysis/power.py --single --harm-fraction 0 \
  --output analysis/false_assurance_sensitivity.json
python3 -B analysis/power.py --single --base-rate .05 --base-minutes 15 \
  --output analysis/lower_charge_sensitivity.json
```

For real results, pass JSON or JSONL rows with `case`, `arm`, `try`, `step`,
`unsafe` (0 or 1), and `human_minutes` (charged at that checkpoint, not cumulative).
Only B and C rows enter the primary analysis. Other arms are ignored. Duplicate,
missing or unmatched primary checkpoints are rejected. Apply the frozen missing
data rules first. Do not fill missing rows with zero. At least two cases are
required. Fewer than 20 cases cause a warning, not an automatic decision.

```bash
python3 -B analysis/cluster_bootstrap.py /path/to/maintenance_rows.jsonl \
  --resamples 10000 --seed 20261016
```

The module also exports `analyze(rows, resamples=10000, seed=20261016)`.
The return value includes estimates, 95% intervals, decisions and warnings.
JSON uses the string `"-Infinity"` for an unbounded lower saving limit.
Zero baseline cost has no defined percentage saving and cannot support H1.

Sources: `BRIEF-v2.md` sections 1, 7.2, 7.3 and 9; `V2.md`; `PROTOCOL.md`
sections 1, 5, 6 and 7; the ten pilot archives; and all three report data files.

## Round three: steadier case comparisons and pre-fixed interim looks

**Planning proposals, not protocol changes.** True benefit means 50% saving and equal
safety. Baseline cost is 30 minutes per checkpoint. Number pairs are **original / C**:
central 95% versus 95% one-sided limits, retaining >30% saving, ≤+5-point safety,
positive baseline cost and the collapsed-safety safeguard.

**2,500 studies per scenario; about ±2 points of simulation uncertainty.** There are
276 fixed scenarios plus 50 fresh sequential validations: 815,000 studies. Runtime was
**33.9 minutes** on six local workers, completed before the remote-compute policy.
Fixed results use 999 bootstrap draws. Counts, individual simulation intervals, both-
boundary checks and rejected interim results are in [steadiness_results.json](steadiness_results.json);
runner: [steadiness.py](steadiness.py). Zero observed passes still permits a 0.15% rate.

### 1. Steadiness sweep: 8 cases × 5 tries

Common share means variance from shared case difficulty: the positive **nonharm minute
demand multiplier**, and the **latent unsafe probability** at equal safety. The sweep
preserves each arm's case variance and reallocates it into common effects. Today's
minute SDs are common .35 / arm-specific .40; safety rhos are .05 / .03. Minute total
log-variance stays .2825; safety total rho stays .0785. Shared uniforms couple checkpoint
failures. Independent try noise stays unchanged: safety rho .20, minute log SD .70.

“False at 30%” holds safety equal; “false at +5” holds saving at 50%; “no difference”
means equal safety and 0% saving. All are **joint** passes. Entries are percentages.

| Steadiness | Common case variance: minutes / safety (%) | Shared uniforms (%) | Base unsafe (%) | Pass (%) O / C | False at 30% saving | False at +5 safety | False with no difference |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Today | 39.9 / 63.7 | 0 | 5 | 11.6 / 18.7 | 1.8 / 3.2 | 1.8 / 3.2 | 0.0 / 0.0 |
| Today | 39.9 / 63.7 | 0 | 15 | 7.6 / 13.2 | 1.1 / 2.6 | 1.7 / 3.8 | 0.0 / 0.1 |
| More shared | 70.0 / 81.8 | 50 | 5 | 14.1 / 22.2 | 1.2 / 2.4 | 1.7 / 3.6 | 0.0 / 0.0 |
| More shared | 70.0 / 81.8 | 50 | 15 | 9.5 / 16.6 | 1.2 / 2.4 | 1.4 / 3.0 | 0.0 / 0.1 |
| Highly shared | 88.0 / 92.7 | 80 | 5 | 16.7 / 26.0 | 1.0 / 2.5 | 1.4 / 3.2 | 0.0 / 0.0 |
| Highly shared | 88.0 / 92.7 | 80 | 15 | 10.0 / 17.2 | 1.0 / 2.4 | 1.1 / 3.0 | 0.0 / 0.0 |
| Very highly shared | 97.0 / 98.2 | 95 | 5 | 19.6 / 28.2 | 0.7 / 2.1 | 1.3 / 2.8 | 0.0 / 0.0 |
| Very highly shared | 97.0 / 98.2 | 95 | 15 | 11.0 / 19.2 | 1.6 / 2.8 | 1.1 / 2.6 | 0.0 / 0.0 |
| Nearly all shared | 99.4 / 99.6 | 99 | 5 | 18.2 / 28.3 | 0.7 / 2.0 | 1.5 / 3.4 | 0.0 / 0.0 |
| Nearly all shared | 99.4 / 99.6 | 99 | 15 | 11.8 / 18.6 | 1.1 / 2.3 | 0.7 / 1.9 | 0.0 / 0.0 |

Steadier case effects help, but do not remove repeat-to-repeat noise.  
Even fully shared case effects/uniforms leave failure correlation around .33 / .42 at 5% / 15% unsafe.  
Shared harm charges have different weights in each arm, so shared drivers do not imply identical percentage savings on every case.

### 2. Designs at similar exam cost

Tries are per arm. Factory cost is additional; 24×3 costs 50% more exam runs than 24×2.
Each row repeats the sweep's pass and false-pass definitions, original / C.

| Cases×tries | Tries / arm | Steadiness | Base unsafe (%) | Pass (%) O / C | False at 30% saving | False at +5 safety | False with no difference |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 8×5 | 40 | Today | 5 | 11.6 / 18.7 | 1.8 / 3.2 | 1.8 / 3.2 | 0.0 / 0.0 |
| 8×5 | 40 | Today | 15 | 7.6 / 13.2 | 1.1 / 2.6 | 1.7 / 3.8 | 0.0 / 0.1 |
| 8×5 | 40 | More shared | 5 | 14.1 / 22.2 | 1.2 / 2.4 | 1.7 / 3.6 | 0.0 / 0.0 |
| 8×5 | 40 | More shared | 15 | 9.5 / 16.6 | 1.2 / 2.4 | 1.4 / 3.0 | 0.0 / 0.1 |
| 8×5 | 40 | Highly shared | 5 | 16.7 / 26.0 | 1.0 / 2.5 | 1.4 / 3.2 | 0.0 / 0.0 |
| 8×5 | 40 | Highly shared | 15 | 10.0 / 17.2 | 1.0 / 2.4 | 1.1 / 3.0 | 0.0 / 0.0 |
| 8×5 | 40 | Very highly shared | 5 | 19.6 / 28.2 | 0.7 / 2.1 | 1.3 / 2.8 | 0.0 / 0.0 |
| 8×5 | 40 | Very highly shared | 15 | 11.0 / 19.2 | 1.6 / 2.8 | 1.1 / 2.6 | 0.0 / 0.0 |
| 8×5 | 40 | Nearly all shared | 5 | 18.2 / 28.3 | 0.7 / 2.0 | 1.5 / 3.4 | 0.0 / 0.0 |
| 8×5 | 40 | Nearly all shared | 15 | 11.8 / 18.6 | 1.1 / 2.3 | 0.7 / 1.9 | 0.0 / 0.0 |
| 12×3 | 36 | Today | 5 | 11.8 / 19.5 | 1.3 / 2.9 | 1.5 / 3.0 | 0.0 / 0.0 |
| 12×3 | 36 | Today | 15 | 7.7 / 13.9 | 1.0 / 2.8 | 1.9 / 3.3 | 0.0 / 0.0 |
| 12×3 | 36 | More shared | 5 | 13.3 / 22.4 | 1.4 / 3.0 | 1.7 / 3.5 | 0.0 / 0.0 |
| 12×3 | 36 | More shared | 15 | 8.5 / 14.8 | 1.1 / 2.4 | 1.7 / 3.3 | 0.0 / 0.0 |
| 12×3 | 36 | Highly shared | 5 | 14.6 / 23.6 | 1.0 / 2.5 | 1.5 / 3.3 | 0.0 / 0.0 |
| 12×3 | 36 | Highly shared | 15 | 9.3 / 16.6 | 1.0 / 2.4 | 1.2 / 2.8 | 0.0 / 0.0 |
| 12×3 | 36 | Very highly shared | 5 | 16.1 / 26.0 | 1.2 / 2.8 | 1.5 / 3.4 | 0.0 / 0.0 |
| 12×3 | 36 | Very highly shared | 15 | 10.2 / 17.5 | 1.0 / 1.9 | 1.3 / 2.8 | 0.0 / 0.0 |
| 12×3 | 36 | Nearly all shared | 5 | 16.9 / 27.2 | 1.4 / 2.7 | 2.0 / 4.1 | 0.0 / 0.0 |
| 12×3 | 36 | Nearly all shared | 15 | 10.3 / 18.6 | 0.9 / 2.3 | 1.4 / 2.6 | 0.0 / 0.0 |
| 16×3 | 48 | Today | 5 | 14.1 / 22.7 | 1.1 / 2.7 | 2.0 / 3.8 | 0.0 / 0.0 |
| 16×3 | 48 | Today | 15 | 9.4 / 16.6 | 0.8 / 2.0 | 1.1 / 2.6 | 0.0 / 0.0 |
| 16×3 | 48 | More shared | 5 | 16.1 / 26.5 | 1.2 / 2.8 | 1.4 / 2.9 | 0.0 / 0.0 |
| 16×3 | 48 | More shared | 15 | 10.5 / 18.1 | 0.7 / 1.7 | 0.8 / 1.9 | 0.0 / 0.0 |
| 16×3 | 48 | Highly shared | 5 | 20.3 / 30.6 | 1.3 / 3.0 | 2.0 / 3.2 | 0.0 / 0.0 |
| 16×3 | 48 | Highly shared | 15 | 12.4 / 20.8 | 0.8 / 2.1 | 1.1 / 2.8 | 0.0 / 0.0 |
| 16×3 | 48 | Very highly shared | 5 | 21.1 / 33.0 | 1.1 / 2.8 | 1.6 / 3.6 | 0.0 / 0.0 |
| 16×3 | 48 | Very highly shared | 15 | 12.4 / 20.7 | 0.8 / 2.0 | 1.4 / 3.0 | 0.0 / 0.0 |
| 16×3 | 48 | Nearly all shared | 5 | 21.8 / 34.2 | 0.9 / 2.2 | 1.4 / 2.6 | 0.0 / 0.0 |
| 16×3 | 48 | Nearly all shared | 15 | 13.7 / 23.2 | 0.6 / 2.0 | 1.0 / 2.8 | 0.0 / 0.0 |
| 24×2 | 48 | Today | 5 | 15.2 / 26.4 | 1.1 / 3.1 | 1.2 / 3.2 | 0.0 / 0.0 |
| 24×2 | 48 | Today | 15 | 11.1 / 18.4 | 0.9 / 2.2 | 1.6 / 3.3 | 0.0 / 0.0 |
| 24×2 | 48 | More shared | 5 | 19.7 / 30.3 | 1.7 / 3.2 | 2.4 / 4.4 | 0.0 / 0.0 |
| 24×2 | 48 | More shared | 15 | 13.4 / 21.5 | 1.0 / 2.5 | 1.3 / 2.7 | 0.0 / 0.0 |
| 24×2 | 48 | Highly shared | 5 | 22.0 / 32.6 | 1.2 / 2.6 | 2.1 / 3.7 | 0.0 / 0.0 |
| 24×2 | 48 | Highly shared | 15 | 14.5 / 23.7 | 0.8 / 2.6 | 1.2 / 2.7 | 0.0 / 0.0 |
| 24×2 | 48 | Very highly shared | 5 | 24.2 / 36.0 | 1.6 / 2.8 | 1.6 / 3.0 | 0.0 / 0.0 |
| 24×2 | 48 | Very highly shared | 15 | 13.6 / 23.1 | 1.0 / 2.6 | 1.8 / 3.6 | 0.0 / 0.0 |
| 24×2 | 48 | Nearly all shared | 5 | 23.6 / 36.6 | 0.8 / 2.1 | 2.4 / 4.4 | 0.0 / 0.0 |
| 24×2 | 48 | Nearly all shared | 15 | 15.2 / 24.9 | 0.8 / 2.2 | 1.2 / 3.1 | 0.0 / 0.0 |
| 24×3 | 72 | Today | 5 | 21.3 / 34.1 | 1.3 / 2.6 | 0.9 / 2.5 | 0.0 / 0.0 |
| 24×3 | 72 | Today | 15 | 14.2 / 22.9 | 0.9 / 2.3 | 0.8 / 2.1 | 0.0 / 0.0 |
| 24×3 | 72 | More shared | 5 | 27.0 / 40.0 | 1.2 / 3.0 | 1.1 / 2.6 | 0.0 / 0.0 |
| 24×3 | 72 | More shared | 15 | 15.5 / 25.2 | 0.8 / 2.2 | 1.2 / 2.5 | 0.0 / 0.0 |
| 24×3 | 72 | Highly shared | 5 | 30.0 / 42.9 | 0.5 / 1.9 | 1.3 / 2.9 | 0.0 / 0.0 |
| 24×3 | 72 | Highly shared | 15 | 18.5 / 28.4 | 0.8 / 2.3 | 0.9 / 2.2 | 0.0 / 0.0 |
| 24×3 | 72 | Very highly shared | 5 | 32.8 / 48.6 | 0.8 / 1.7 | 1.2 / 2.8 | 0.0 / 0.0 |
| 24×3 | 72 | Very highly shared | 15 | 19.2 / 30.8 | 1.1 / 2.1 | 1.1 / 2.1 | 0.0 / 0.0 |
| 24×3 | 72 | Nearly all shared | 5 | 35.0 / 48.0 | 1.1 / 2.4 | 1.1 / 3.2 | 0.0 / 0.0 |
| 24×3 | 72 | Nearly all shared | 15 | 19.3 / 30.9 | 0.8 / 2.0 | 1.2 / 3.0 | 0.0 / 0.0 |

Two tries estimate pooled within-case noise, contributing one variance degree of freedom per case.  
Two are too few for dependable individual-case variance, tail or correlation estimates.  
24×2 offers broader coverage than 16×3 at the same exam cost, with more factory work; small power differences are within simulation noise.

**What must eight cases show to make 24×2 reach 80% under C?** No tested case-steadiness
level does so with unchanged try noise. Even 100% common case effects and uniforms give
only **35.4% / 25.9% power** at 5% / 15% unsafe. Measure paired differences and repeat
noise together; raw case correlation cannot certify enough power. A rough necessary
safety standard error is below 2 points; the fully shared model still has 2.4 / 3.8.

The first tested two-try case counts reaching 80%, including a simulation lower bound
above 80%, were **96 / 192 cases** with today's assumptions and **72 / 128** with fully
shared effects (5% / 15% unsafe). These are conditional grid points. Fix any larger cap
or formal adaptation before scoring; eight observed cases do not authorize extra runs.

### 3. One pre-fixed interim look, then 24 cases × 2 tries

Choose **8→24 or 12→24**, not both early looks. Set case order and writer-family balance
in advance. Both endpoints must pass at the same look. Use standard
[Lan–DeMets/O’Brien–Fleming spending](https://keaven.github.io/gsDesign/reference/sfLDOF.html),
total alpha .025 / .05 per endpoint for original / C. No split across endpoints is
needed because both must pass. Stop for futility only when 99% limits put saving below
30% or the safety difference above +5 points. A wide or collapsed interval is insufficient.

**This item needs a different interval method.** Plain percentile-bootstrap spending
failed calibration: maximum joint false passes were 2.76% / 5.00%, with safety-only
crossings 3.72% / 6.08%. The table uses **Student-t limits, cases−1 degrees of freedom,
and the exact standard deviation of the paired case/try bootstrap**, validated on fresh
studies. Time uses `.7B − C > 0`, the same >30% target. Thresholds and the collapsed
safeguard stay fixed. Tables 1–2 keep percentile intervals. The failed plan is archived
under `unadjusted_percentile_sequential` in the JSON.

| Steadiness | Base unsafe (%) | Looks | Pass (%) O / C | False at 30% saving | False at +5 safety | False with no difference | Mean cases, benefit O / C | First-look stop (%), benefit O / C |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Today | 5 | 8→24 | 10.6 / 23.0 | 0.9 / 2.0 | 1.4 / 2.9 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Today | 5 | 12→24 | 10.4 / 22.2 | 0.9 / 2.0 | 1.2 / 2.8 | 0.0 / 0.0 | 24.00 / 23.99 | 0.0 / 0.1 |
| Today | 15 | 8→24 | 8.4 / 17.0 | 0.7 / 2.0 | 1.2 / 2.6 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Today | 15 | 12→24 | 8.1 / 16.6 | 0.7 / 2.0 | 1.2 / 2.6 | 0.0 / 0.0 | 24.00 / 23.93 | 0.0 / 0.6 |
| More shared | 5 | 8→24 | 13.2 / 25.7 | 0.9 / 1.9 | 0.6 / 2.4 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| More shared | 5 | 12→24 | 12.9 / 25.2 | 0.9 / 1.8 | 0.6 / 2.2 | 0.0 / 0.0 | 24.00 / 23.98 | 0.0 / 0.2 |
| More shared | 15 | 8→24 | 10.1 / 19.0 | 0.6 / 1.2 | 1.1 / 3.0 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| More shared | 15 | 12→24 | 9.9 / 18.7 | 0.6 / 1.2 | 1.1 / 2.9 | 0.0 / 0.0 | 24.00 / 23.95 | 0.0 / 0.4 |
| Highly shared | 5 | 8→24 | 14.5 / 26.7 | 0.7 / 2.1 | 1.1 / 2.8 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Highly shared | 5 | 12→24 | 14.0 / 26.2 | 0.7 / 1.8 | 1.0 / 2.7 | 0.0 / 0.0 | 24.00 / 23.96 | 0.0 / 0.4 |
| Highly shared | 15 | 8→24 | 9.7 / 20.2 | 0.6 / 1.9 | 0.8 / 2.6 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Highly shared | 15 | 12→24 | 9.6 / 19.2 | 0.6 / 1.8 | 0.8 / 2.4 | 0.0 / 0.0 | 24.00 / 23.97 | 0.0 / 0.3 |
| Very highly shared | 5 | 8→24 | 14.9 / 28.7 | 0.5 / 1.6 | 1.3 / 3.2 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Very highly shared | 5 | 12→24 | 14.6 / 28.0 | 0.5 / 1.6 | 1.3 / 3.0 | 0.0 / 0.0 | 24.00 / 23.97 | 0.0 / 0.3 |
| Very highly shared | 15 | 8→24 | 11.4 / 20.6 | 0.4 / 1.3 | 0.7 / 2.6 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Very highly shared | 15 | 12→24 | 11.2 / 20.2 | 0.4 / 1.3 | 0.6 / 2.3 | 0.0 / 0.0 | 24.00 / 23.96 | 0.0 / 0.4 |
| Nearly all shared | 5 | 8→24 | 17.5 / 31.6 | 0.3 / 1.4 | 1.4 / 3.1 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Nearly all shared | 5 | 12→24 | 17.2 / 30.9 | 0.3 / 1.4 | 1.5 / 3.0 | 0.0 / 0.0 | 24.00 / 23.96 | 0.0 / 0.4 |
| Nearly all shared | 15 | 8→24 | 11.5 / 22.6 | 0.5 / 1.6 | 1.0 / 2.4 | 0.0 / 0.0 | 24.00 / 24.00 | 0.0 / 0.0 |
| Nearly all shared | 15 | 12→24 | 11.2 / 22.0 | 0.5 / 1.4 | 0.9 / 2.3 | 0.0 / 0.0 | 24.00 / 23.96 | 0.0 / 0.4 |

Mean cases and first-stop chances above assume true benefit. Under no difference,
mean cases are 23.28–23.86 and first stops 0.9–6.0%. JSON includes these measures for
every boundary/null scenario, plus early success versus futility. The interactive
[three-table report](steadiness_table.html) lets you select the cost scenario.

Maximum joint false passing is **1.48% / 3.16%**; safety-only crossings are **2.28% / 4.12%**.
Across all 160 null comparisons, simultaneous 95% Monte Carlo upper bounds on joint
false passing are **2.496% / 4.536%**, below nominal 2.5% / 5% (exact binomial bounds,
Bonferroni corrected). Calibration is conditional on the tested model grid; t limits
and normal information remain approximations. A matched fixed-t reference in the JSON
shows at most 1.04 points of power change from adding the look; comparisons with Table 2
also include the interval-method change.

Clear early success is rare with these small samples.  
Even with no benefit, the validated interim saves less than one case on average.  
Stopping saves exam runs; it saves factory cost only if cases are built in batches.

**Recommendation:** keep the five-point margin and use C if one-sided 5% inference is
acceptable. At roughly 48 tries per arm, prefer **fixed 24×2 as exploratory**, or 16×3
when factory cost dominates. An 80% confirmatory target needs a larger pre-fixed cap
or credible evidence of lower repeat noise. The surprises were the remaining noise
after case matching and the failed naive interim calibration.

All four scripts' self-tests passed: generator moments, bootstrap equivalence, exact
bootstrap SD, two-try behavior, strict thresholds, collapsed/zero-cost safeguards and
spending boundaries. No protocol edits, model calls, paid services or commits.

### Rerun

The recorded versions were NumPy 2.5.4 and SciPy 1.18.1. Quick self-tests may stay local.
Future jobs exceeding about one minute of CPU use the **existing** Hetzner server,
`nice -n 10`, **at most three processes**, detached logging. Its Python environment
needs NumPy and SciPy. Do not create/delete servers or run `hcloud-dev down`. Sync
preserves newer remote files; pull results before using them locally.

```bash
/tmp/unbug-steadiness-venv/bin/python -B analysis/steadiness.py --self-test
bin/hcloud-dev run 'nohup nice -n 10 python3 analysis/steadiness.py --workers 3 --output analysis/steadiness_remote_results.json > /tmp/steadiness-power.log 2>&1 < /dev/null &'
bin/hcloud-dev run 'tail -n 12 /tmp/steadiness-power.log'
bin/hcloud-dev pull /home/user/unbug-bench/analysis/steadiness_remote_results.json
mv results/remote/steadiness_remote_results.json analysis/steadiness_results.json
```
