#!/usr/bin/env python3
"""Pre-scoring secondary calibration; never changes the primary rule or priors.

Uses secondary_round.bayes unchanged and steadiness.t_flags on the SAME studies.
Run with single-thread BLAS (see README). No contestant outcomes are read.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.stats import beta

from secondary_round import PRIORS, bayes
from steadiness import EFFECTS, generate_batch, t_flags, t_statistics

SCENARIOS = ("no_difference", "time_boundary", "safety_boundary", "both_boundaries")
THRESHOLDS = (.95, .96, .97, .975, .98, .99)


def rate(count, n):
    # Exact one-sided Clopper-Pearson 95% bound, including zero successes.
    upper = float(beta.ppf(.95, count+1, n-count)) if count < n else 1.
    return {"count": int(count), "studies": n, "estimate": count/n,
            "upper_one_sided95": upper, "upper_minus_estimate": upper-count/n}


def study(job):
    scenario, tries, index, seed, draws, burn = job
    sid = SCENARIOS.index(scenario)
    # Data stream independent of MCMC effort and worker scheduling. Generating
    # three tries then slicing matches the original calibration's generator.
    # The two designs also share the first two generated tries for each study.
    data = generate_batch(np.random.default_rng(np.random.SeedSequence([seed, sid, index, 0])),
                          1, 24, 3, .15, scenario, 0.)[0, :, :tries]
    values = [np.column_stack((x[:, 1:3], np.zeros(tries), x[:, 0])) for x in data]
    rng = np.random.default_rng(np.random.SeedSequence([seed, sid, index, tries]))
    posterior = bayes(values, PRIORS["sceptical"], rng, draws, burn)
    initial_probabilities = list(posterior["probabilities"].values())
    initial_poor = not posterior["diagnostics"]["adequate"]
    initial_ambiguous = posterior["threshold_095_mc_ambiguous"]["both"]
    # Resolve posterior-threshold MC ambiguity, without selecting/dropping a
    # study. An independent longer run replaces (never pools with) the short run.
    refined = initial_ambiguous
    if refined:
        posterior = bayes(values, PRIORS["sceptical"], rng, 4000, 2000)
    p = list(posterior["probabilities"].values())
    se = posterior["posterior_probability_mcse"]
    primary = t_flags(t_statistics(data[None]), 24, .05)[0]
    return {"scenario": scenario, "tries": tries, "study": index,
            "probabilities_saving_safety_joint": p, "mcse_saving_safety_joint": se,
            "rule_C_joint_minutes_safety": primary.tolist(),
            "initial_probabilities_saving_safety_joint": initial_probabilities,
            "initial_poor_diagnostics": initial_poor,
            "initial_joint_threshold_ambiguous": initial_ambiguous,
            "refined": refined,
            "poor_diagnostics": not posterior["diagnostics"]["adequate"],
            "split_rhat": posterior["diagnostics"]["split_rhat"],
            "ess": posterior["diagnostics"]["ess"]}


def summarize(records):
    rows = []
    for tries in (3, 2):
        for scenario in SCENARIOS:
            selected = [r for r in records if r["tries"] == tries and r["scenario"] == scenario]
            if not selected:
                continue
            n = len(selected)
            p = np.array([r["probabilities_saving_safety_joint"] for r in selected])
            se = np.array([r["mcse_saving_safety_joint"] for r in selected])
            primary = np.array([r["rule_C_joint_minutes_safety"] for r in selected])
            ambiguous = np.abs(p[:, 2]-.95) <= 2*se[:, 2]
            joint = p[:, 2] > .95
            rows.append({"cases": 24, "tries": tries, "scenario": scenario,
                "true_saving": EFFECTS[scenario][0], "true_safety_difference": EFFECTS[scenario][1],
                "bayesian_joint": rate(int(joint.sum()), n),
                "rule_C_joint": rate(int(primary[:, 0].sum()), n),
                "bayesian_joint_original_short_chains": rate(sum(r["initial_probabilities_saving_safety_joint"][2] > .95 for r in selected), n),
                "bayesian_endpoint_crossings": {name: rate(int((p[:, j] > .95).sum()), n)
                    for j, name in enumerate(("saving", "safety"))},
                "rule_C_endpoint_passes": {name: rate(int(primary[:, j+1].sum()), n)
                    for j, name in enumerate(("minutes", "safety"))},
                "bayesian_joint_counting_unresolved_ambiguity_as_pass": rate(int((joint | ambiguous).sum()), n),
                "unresolved_joint_threshold_ambiguity": int(ambiguous.sum()),
                "initial_poor_diagnostics": sum(r["initial_poor_diagnostics"] for r in selected),
                "poor_diagnostics": sum(r["poor_diagnostics"] for r in selected),
                "longer_chain_refinements": sum(r["refined"] for r in selected),
                "threshold_sensitivity_same_studies": {str(t): rate(int((p[:, 2] > t).sum()), n)
                                                       for t in THRESHOLDS}})
    return rows


def self_test():
    assert abs(rate(0, 49)["upper_one_sided95"]-(1-.05**(1/49))) < 1e-12
    assert rate(2500, 2500)["upper_one_sided95"] == 1
    assert rate(0, 2500)["upper_one_sided95"] < .002
    assert rate(125, 2500)["upper_minus_estimate"] < .01
    args = ("safety_boundary", 2, 0, 20261019, 40, 30)
    a, b = study(args), study(args)
    assert a == b, "per-study seed must be deterministic"
    p = a["probabilities_saving_safety_joint"]
    assert 0 <= p[2] <= min(p[:2]) <= 1
    # Independent manual case/try SE calculation checks production t_flags use.
    from scipy.stats import t
    data = generate_batch(np.random.default_rng(np.random.SeedSequence([20261019, 2, 0, 0])),
                          1, 24, 3, .15, "safety_boundary", 0.)[0, :, :2]
    d, effort = data[..., 0], .7*data[..., 1]-data[..., 2]
    def se(x):
        means = x.mean(axis=1)
        return np.sqrt((means.var()+((x-means[:, None])**2).mean(axis=1).mean()/2)/24)
    safety = np.ptp(d) > 0 and d.mean()+t.isf(.05, 23)*se(d) <= .05+1e-12
    minutes = data[..., 1].mean() > 0 and effort.mean()-t.isf(.05, 23)*se(effort) > 1e-12
    assert a["rule_C_joint_minutes_safety"] == [bool(safety and minutes), bool(minutes), bool(safety)]
    rows = summarize([a])
    assert rows[0]["bayesian_joint"]["studies"] == 1
    print("calibrate_secondary self-check passed: exact bounds, seeded posterior, paired t rule, summary")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--studies", type=int, default=2500)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--draws", type=int, default=600)
    parser.add_argument("--burn", type=int, default=400)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("secondary_calibration.json"))
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if min(args.studies, args.workers, args.draws, args.burn) < 1:
        parser.error("all counts must be positive")
    jobs = [(s, nt, i, args.seed, args.draws, args.burn)
            for s in SCENARIOS for i in range(args.studies) for nt in (3, 2)]
    started = time.monotonic()
    records = []
    # Append-only progress contains each finished study, so interrupted compute
    # remains auditable. Final JSON contains every record too.
    with args.output.with_suffix(".jsonl").open("w") as progress:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for record in pool.map(study, jobs, chunksize=5):
                records.append(record)
                progress.write(json.dumps(record)+"\n")
                if len(records) % 100 == 0:
                    progress.flush()
                    print(f"{len(records)}/{len(jobs)} studies; {time.monotonic()-started:.1f}s", flush=True)
    scripts = ("calibrate_secondary.py", "secondary_round.py", "steadiness.py", "power.py", "cluster_bootstrap.py")
    result = {"synthetic_only": True, "decision_use": "secondary calibration only; primary rule C unchanged",
        "seed": args.seed, "studies_per_scenario_per_design": args.studies,
        "prior": PRIORS["sceptical"], "posterior_threshold_strictly_greater_than": .95,
        "initial_draws_per_chain": args.draws, "initial_burn_in": args.burn, "chains": 2,
        "ambiguity_refinement": "If joint P is within 2 MCSE of .95: independent replacement fit, 4000 draws/chain, 2000 burn-in; unresolved ambiguity counted as pass in conservative sensitivity",
        "generator": "steadiness.generate_batch; 24 cases; 3 tries generated then first 2 or all 3 retained; base unsafe .15; mean 30 minutes/checkpoint; 4-6 checkpoints; level 0; binary checkpoints and discrete charges",
        "pairing": "Bayes and t-based rule C use identical generated studies; both sizes share first two tries; data and MCMC seeds independent",
        "rule_C": "steadiness.t_statistics/t_flags(alpha=.05), df=23, nested case-then-try SE, positive baseline and noncollapsed safety guards",
        "bound": "exact one-sided 95% Clopper-Pearson binomial upper bound; pointwise, no multiplicity adjustment",
        "limitations": ["Model-conditional calibration at specified nulls; no universal type-I guarantee.",
                        "Short-chain algorithm calibration, with longer independent fits near the joint threshold; poor diagnostics retained in denominator.",
                        "No-saving/equal-safety and safety-boundary nulls do not replace calibration over all nuisance parameters.",
                        "Safety exactly +5 points is the non-inferiority boundary, not a loss strictly beyond the margin."],
        "workers": args.workers, "runtime_seconds": time.monotonic()-started,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__, "platform": platform.platform()},
        "script_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in scripts},
        "summary": summarize(records), "records": records}
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
