# Measurement round — SYNTHETIC, not evidence about Unbug

24 cases; 2–3 tries per arm. Result: **supports H1**. No interim look.

Charged human-time saving: **42.6%**, two-sided 95% interval 30.1% to 53.0%. Rule C's one-sided lower bound is 32.2%; it must exceed 30%.

Safety difference C − B: **-2.6 percentage points**, two-sided 95% interval -11.1 to +5.7 percentage points. Rule C's one-sided upper bound is +4.3 points; it must be at most +5 points.

Average charged minutes per try: B 148.2; C 85.1. Newcombe comparison interval: -9.3 to +4.9 percentage points; it ignores pairing/clustering and does not decide the result.

- B, unsafe status: two tries disagree 30.2% of the time (95% interval 20.1% to 41.7%); Fleiss kappa 0.03 (95% interval -0.15 to 0.22, defined resamples only).
- B, response correctness: two tries disagree 34.4% of the time (95% interval 24.0% to 45.8%); Fleiss kappa 0.08 (95% interval -0.12 to 0.27, defined resamples only).
- C, unsafe status: two tries disagree 29.2% of the time (95% interval 20.1% to 38.9%); Fleiss kappa -0.05 (95% interval -0.20 to 0.14, defined resamples only).
- C, response correctness: two tries disagree 35.4% of the time (95% interval 25.3% to 45.8%); Fleiss kappa -0.05 (95% interval -0.22 to 0.14, defined resamples only).

Between-case variance measures how cases differ; within-case variance measures repeat noise. The JSON gives both with intervals for each arm and the paired difference, using log(1 + minutes) and unsafe rates. More cases reduce both sources; more tries mainly reduce repeat noise.

Next round at 2 tries: 192 cases conditionally recommended.
Next round at 3 tries: 128 cases conditionally recommended.

Sizing assumes a true 50% saving and equal safety; it is conditional on a model and uncertain measured variance, not a promise of 80% power. Freeze a new round separately.

Third tries count inside their case: every case has equal weight. The subset must be chosen before scores; pooling all tries would give those cases extra weight. JSON includes a small bias simulation.

A non-pass means **not enough data to tell**, including a wide or collapsed interval. The JSON retains the directional protocol diagnostics; this measurement round does not label Unbug a failure.


Secondary analyses do not change rule C. A posterior around **70% is weak evidence, not a finding**. The Bayesian calculation keeps the case/try hierarchy and cross-outcome covariance. It uses a Gaussian approximation to paired try summaries, while the separate mixed-model checks use log(1 + minutes) and a logistic model for unsafe checkpoints.

| Frozen prior | P(saving >30%) | P(safety ≤+5pt) | P(both) | Chains adequate |
|---|---:|---:|---:|---|
| sceptical | 96.4% | 97.2% | 95.0% | True |
| neutral/flat | 97.4% | 97.1% | 95.8% | True |
| optimistic | 98.5% | 98.4% | 97.5% | True |

Sceptical prior: saving centred at 0, SD 35 percentage points; safety difference centred at 0, SD 10 points. Neutral/flat widths are 150 and 25 points. Optimistic centres are 50% saving and −3 safety points, with sceptical widths. Population saving is below 100% and safety difference within ±100 points. Common baseline/covariance priors, posterior intervals and Monte Carlo errors are in JSON.

The sceptical joint probability is within Monte Carlo uncertainty of 95%; do not treat the displayed rounding as a threshold finding.

- Log-minute model: C−B log(1 + minutes) coefficient -0.643; converged=True; singular/boundary=True. Case-bootstrap intervals and unsuccessful fits are recorded.
- Unsafe logistic model: marginal C−B safety difference -2.3 points (conditional log-odds coefficient -0.000); converged=True; singular/boundary=True. Case-bootstrap intervals and unsuccessful fits are recorded.

Covariate adjustment uses only the frozen factory/tester/strategy/ingredient covariates, never establishment or contestant outputs. Fixture variance reductions (negative means worse):

- minutes_difference_C_minus_B: -80.2%.
- unsafe_difference_C_minus_B: -47.2%.
- saving: -70.2%.

Sceptical-prior synthetic P>0.95 calibration (saving / safety / joint threshold crossings; binomial intervals in JSON). At no difference, safety non-inferiority alone is true, so its crossings are not false claims:

- no_difference: saving 0/49; safety 19/49; joint 0/49; poor chain diagnostics in 0 studies.
- time_boundary: saving 0/49; safety 16/49; joint 0/49; poor chain diagnostics in 0 studies.
- safety_boundary: saving 15/49; safety 0/49; joint 0/49; poor chain diagnostics in 1 study.
- both_boundaries: saving 1/49; safety 1/49; joint 0/49; poor chain diagnostics in 0 studies.

Even zero joint crossings leaves a 95% Monte Carlo upper error bound of 7.3% here; this does not establish a controlled 5% error rate.

These secondary checks are model-conditional. The JSON records numerical failures and posterior threshold ambiguity. Bootstrap variance remains the sizing reference if mixed models disagree. No unregistered subgroups or item response theory.
