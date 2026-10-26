# Measurement round reporting and freeze instructions

The founder chose **24 cases, rule C, no interim look**, with three tries per arm
if affordable, otherwise two plus a third on cases chosen before scoring. A
non-pass means **not enough data to tell**. `report_round.py` implements that
report; the older planning studies below remain proposals and historical context.

The report answers four questions:

- **How big is the benefit?** Time saving is `1 − mean(C minutes)/mean(B minutes)`;
  safety difference is C minus B's unsafe-checkpoint rate. Each case counts equally,
  then each try within it. Establishment is excluded. Paired case-then-try bootstrap
  intervals retain whole checkpoints. The report shows two-sided 95% intervals;
  rule C uses the one-sided 95% lower saving bound (>30%) and upper safety bound
  (≤+5 percentage points). Identical safety differences cannot establish safety.
  The Newcombe interval is an unpaired, unclustered comparison, never a substitute.
- **Does it repeat?** Disagreement is the chance that two tries of the same arm on
  the same case/checkpoint have different unsafe or correctness labels. All pairs
  within a checkpoint count, then checkpoints and cases count equally. Case-weighted
  Fleiss kappa adjusts for agreement expected from label frequency; it is undefined
  if there is no label variation. Both have case-bootstrap intervals in the JSON.
- **Where is the noise?** Between-case and within-case/try variance, with case-bootstrap
  intervals, are reported for B, C and the paired difference. Minutes use
  `log(1 + total charged minutes)` so zero-minute tries stay included; the paired
  log difference is `log(1+C) − log(1+B)`, not a log of a possibly negative difference.
  Unsafe variance uses each try's checkpoint fraction, including checkpoint randomness.
  Negative component eigenvalues are set to zero; raw estimates remain visible.
- **What should the next round cost?** A conditional sizing scan uses the measured
  components in `steadiness.generate_measured_batch`, at two and three tries. It
  assumes a true 50% saving and equal safety, rather than treating today's noisy
  estimated effect as truth. It reports Monte Carlo intervals, model checks and
  null-boundary checks. It withholds an unreliable recommendation. This Gaussian
  try-summary model is an approximation; it does not regenerate individual claims
  or account for uncertainty in estimated components. More tries mostly reduce
  repeat noise; more cases address both sources.

**Freeze before scoring.** Copy the example `fixtures/measurement-round/design.json`
to a separate real-round design file; set `synthetic` to false, replace every case
ID, and list its exact maintenance step indices and `[1,2]` or `[1,2,3]` tries.
Step 1 is establishment; `bin/run-exam` numbers steps from 1. Keep the exact
`sizing_rule` text. Record how the subset was selected and hash the design, analysis
scripts and command/options with the rest of the freeze. The script records hashes
but cannot prove when files were frozen. Every planned B/C checkpoint must exist;
errors/missing pairs require adjudication under the frozen missing-data rule, not
silent removal. Any nonselected steps and other arms are counted in the audit.

Give the script the directory containing `bin/run-exam`'s `*.scorecard.json` files.
For saved `bin/score-claims` outputs (or checkpoints containing `claims_score`), add
`score_files` to the design: a list of
`{"case":"ID","try":1,"arm":"B","step":2,"path":"scores/file.json"}`
entries, with paths relative to the results directory. That format needs the sidecar
because score-claims outputs contain no case/try/step IDs. These two input modes
are alternatives; they are never merged or rescored by this script.

Every selected score must carry `adjudicated: true`, a positive integer `runs`,
and integer zero `error_runs` and `invalid_runs`. Full checkpoint inputs must
also have valid outer counts and no recorded errors; a nested `claims_score`
cannot override an invalid batch. Safety and charged minutes on unadjudicated
scores are diagnostics, not measurement outcomes. Historical standalone scores
or exam exports lacking these fields must be regenerated from their checkpoint
evidence with the current scorer/exporter. Do not add validity flags by hand or
drop failed planned checkpoints to make the report run.

For the unequal-try design, launch the selected cases with `run-exam --tries 3`
and the others with `--tries 2`. Separate exam invocations restart local try
numbering: if the third try is a separate batch, export its score-claims outputs
and assign the preplanned global try ID 3 in the explicit sidecar. Do not infer a
third try from file order, timestamps, or scores; duplicate IDs are rejected.

```bash
/tmp/unbug-steadiness-venv/bin/python -B analysis/report_round.py --self-test
# Fast demonstration; never produces a sizing recommendation:
/tmp/unbug-steadiness-venv/bin/python -B analysis/report_round.py \
  analysis/fixtures/measurement-round --design analysis/fixtures/measurement-round/design.json \
  --quick --bootstrap 299 --out /tmp/synthetic-round
```

The JSON contains estimates, intervals, diagnostics, input/script hashes and the
complete size scan. The Markdown is a short founder-readable interpretation.
The checked-in fixture is synthetic and carries no evidence about Unbug.

**Secondary checks approved on 2026-10-17.** These help interpret the measurement;
**rule C stays the only decision rule**. Freeze the example's exact `secondary_plan`
and the covariate fields before scoring. A posterior around **70% is weak evidence,
not a finding**.

- **Bayesian summary:** the sceptical prior is centred on 0% saving (SD 35 percentage
  points) and 0 safety difference (SD 10 points). This is broad enough that the prior
  alone does not certify the +5-point margin. The table also shows neutral/flat
  widths of 150/25 points and an optimistic prior centred at 50% saving/−3 safety
  points, with the sceptical widths. Saving is bounded below 100%; safety difference
  within ±100 points. Common nuisance priors are stated in the frozen plan: a broad
  log-baseline prior and heavy-tailed inverse-Wishart case/try covariance priors.
  The joint posterior retains case and try effects and cross-outcome covariance,
  sampling covariance uncertainty instead of plugging in estimates. It uses a
  **Gaussian working likelihood on paired try summaries**, including risk differences;
  it has the same case/try grouping as the mixed models, but is not a Bayesian
  logistic GLMM. The approximation can predict impossible summary observations.
  Read its synthetic calibration and convergence/Monte Carlo diagnostics before
  interpreting probabilities. Poor chains remain visible, including in calibration.
- **Mixed models:** a Gaussian random-effects model for `log(1 + minutes)` retains
  zero-minute tries; a binomial logistic model uses unsafe checkpoint counts.
  Both have paired case and try-within-case covariance, and case-bootstrap refitting
  intervals rather than Wald intervals. The logistic coefficient is a log-odds
  difference; the marginal risk difference is also reported. Singular/boundary fits,
  separation, non-convergence, unsuccessful bootstrap fits and quadrature sensitivity
  are explicit. Logistic variance is converted to the observed checkpoint-rate scale
  before sizing comparisons. Model inputs feed a secondary power check at reference
  sizes only when stable and in agreement; bootstrap components remain the reference
  when models disagree. Cross-outcome covariance comes from the reference bootstrap.
- **CUPED-style adjustment:** at most three predeclared covariates, only from factory
  difficulty testers, `bin/strategy` results, and case ingredients. The example has
  synthetic values of those types, fixed by case ID before any generated contestant
  outcome. Replace them with frozen pre-contestant values and provenance. The design
  lists each name, allowed source, `fixed_before_contestants: true`, and its frozen
  mean across the 24 cases; `covariates` maps case IDs to values. There is no automatic
  variable selection or outcome-based imputation. Four case folds are fixed by hash;
  slopes are fitted on the other folds and refitted in the case bootstrap. The JSON
  reports achieved variance reduction, including negative values when adjustment
  makes things worse. The estimand conditions on the frozen case-set covariate mean.
  Never use establishment, claims, contestant time, correctness or any other
  contestant-produced value as a covariate.

The full synthetic run records the sceptical-prior `P>0.95` crossing rate under no
difference, the 30% time boundary, the +5-point safety boundary and both boundaries
(49 studies each, binomial Monte Carlo intervals). Safety non-inferiority at no
difference is true, so safety alone is not a false claim there. Calibration uses
the existing steadiness simulator's **binary checkpoints and discrete minute
charges**, with baseline unsafe rate 15%, 30 charged minutes per checkpoint, 4–6
checkpoints, level 0 case/try variation, and the fixture's 24-case unequal-try
design. Its independent seed is 20261019. This checks the Gaussian Bayesian
approximation against a different observation process. Shorter chains record
threshold ambiguity and diagnostic failures; the result is model-conditional,
not a guarantee. For a real round, copy the completed full
synthetic JSON into the frozen results bundle, set `bayesian_calibration_file`
(relative to the results directory) and its `bayesian_calibration_sha256` in the
design. The real report verifies and reuses that pre-scoring calibration; it does
not tune priors or recalibrate them on contestant outcomes. Quick reports are not
accepted as frozen calibrations. No item response theory or post-hoc subgroups are
implemented; the frozen subgroup list is empty.

For try-to-try agreement, also freeze checkpoint alignment. If every try uses the
same scenario order, set `same_checkpoint_order_across_tries: true` in each case.
If order differs, provide `checkpoint_alignment` with one list per try ID, mapping
canonical scenario order to its run-exam step indices, for example
`{"1":[2,3,4,5],"2":[4,2,5,3]}`. Comparing two different scenarios at the same sequence
position would measure the wrong kind of disagreement. The loader rejects an
unasserted/unmapped order.

**Third-try rule.** Freeze the subset independently of outcomes, preferably using
a seeded draw balanced by writer family. Average tries *inside each case*, then
average cases equally. A third try increases that case's precision, not its weight.
Resample cases, then paired tries using each case's original try count. No checkpoint
resampling. This is unbiased for mean minutes/rates under exchangeable tries;
the ratio saving and kappa retain ordinary nonlinear finite-sample bias.
`subset_simulation` demonstrates this with a deliberately harder fixed subset and
shows the bias from pooling all tries. Missing planned tries are rejected.

**Frozen next-round sizing rule (exact text is in the design and report).** After
the completed measurement round, plug its equal-case covariance components into
the measured-component generator, retaining paired covariance. Fix the alternative
at 50% saving and zero safety difference; retain measured baseline minutes. For
each of 2 and 3 tries, scan 24, 36, 48, 72, 96, 128, 192, 256, 384 and 512 cases,
using seed 20261017, 2,500 studies and 999 nested bootstrap draws per study. Select
the first grid size whose **lower Wilson 95% Monte Carlo power bound is ≥80%**
under fixed-sample rule C, including the collapsed guard. Stop that design's
simulation scan at the first qualifying size and report every tested grid point.
Withhold the recommendation if the generator materially misses the measured
moments, either null-boundary rejection lower bound exceeds 5%, safety collapses,
or baseline minutes are zero. If no size qualifies, say beyond 512/undetermined.
Never use this to extend the current round; a future decisive round needs a new
freeze and a cost check. These are model-conditional sizes, not guaranteed power.

Full sizing exceeds the local CPU budget. Use only the existing Hetzner dev server
(first check it is running: `hcloud-dev run` otherwise creates one automatically).
Use one process, bound BLAS threads, detach, then pull the artifacts:

```bash
bin/hcloud-dev run 'nohup nice -n 10 env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -u analysis/report_round.py analysis/fixtures/measurement-round --design analysis/fixtures/measurement-round/design.json --out analysis/round_synthetic > /tmp/round-report.log 2>&1 < /dev/null &'
bin/hcloud-dev run 'tail -n 8 /tmp/round-report.log'
bin/hcloud-dev pull /home/user/unbug-bench/analysis/round_synthetic.json
bin/hcloud-dev pull /home/user/unbug-bench/analysis/round_synthetic.md
```

For the real round, replace fixture paths with the frozen scored results/design.
If NumPy/SciPy are absent, create `/tmp/v` with `python3 -m venv /tmp/v`, install
`numpy scipy` there and use `/tmp/v/bin/python` in the detached command. Do not
create/delete servers or run `hcloud-dev down`.

