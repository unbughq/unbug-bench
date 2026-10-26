#!/usr/bin/env python3
"""Report a completed, frozen measurement round; no model or service calls.

Read run-exam *.scorecard.json files, or score-claims outputs located by the
design's score_files entries. See README.md for the deliberately explicit design.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import tempfile

import numpy as np

from cluster_bootstrap import decision, json_safe, newcombe, quantile, wilson
from steadiness import bootstrap_batch, flags, generate_measured_batch
from secondary_round import SECONDARY_PLAN, markdown_secondary, run_secondary, validate_secondary_design


SIZING_RULE = (
    "After all frozen measurement cases are scored, fit equal-case random-effects "
    "covariances to log(1 + charged minutes) and unsafe checkpoint fractions per try. "
    "Use the measured-component generator in steadiness.py, retaining case, try and "
    "paired covariance, under a fixed planning alternative of 50% time saving and "
    "zero safety difference, at the measured baseline mean minutes. For 2 and 3 tries "
    "separately, scan the frozen case grid [24,36,48,72,96,128,192,256,384,512]. "
    "Use 2500 simulated studies and 999 paired case-then-try bootstrap draws per study, "
    "seed 20261017; apply fixed-sample rule C (one-sided 95%, saving >30%, safety <=+5 "
    "points, collapsed-safety guard). Select the first grid size whose Wilson 95% "
    "Monte Carlo LOWER power bound is at least 80%; stop that design's simulation "
    "scan there and report every tested grid point. Check "
    "moment reproduction and simulate each null boundary at the candidate size; "
    "withhold a recommendation if moments differ materially, any boundary rejection "
    "LOWER Monte Carlo bound exceeds 5%, safety is collapsed, or baseline minutes "
    "are zero. If none qualifies, report beyond 512/undetermined, never extrapolate. "
    "This sizes a future separately frozen round, never adds tries or cases to this "
    "measurement round, and is conditional on estimated components and the Gaussian "
    "summary model; it does not include component-estimation uncertainty."
)
SUBSET_RULE = (
    "Freeze case IDs, maintenance steps, paired try IDs and the third-try subset before "
    "any scores are seen; choose the subset independently of outcomes (prefer a seeded "
    "random subset balanced by writer family). Average checkpoints within try for "
    "safety; sum minutes within try; average tries within case, then cases equally. "
    "Resample paired cases and then paired tries, retaining each selected case's "
    "original try count and all checkpoints. Third-try cases get no extra case weight. "
    "A fixed subset is unbiased for mean minutes/rates conditional on these cases if "
    "tries are exchangeable and subset membership is outcome-independent. The saving "
    "ratio and kappa have ordinary finite-sample nonlinear bias; no exact unbiasedness "
    "is claimed for them. Missing planned tries are an error, not a new subset."
)


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_design(design):
    if design.get("rule") != "C" or design.get("interim_look") is not False:
        raise ValueError("design must freeze rule C and interim_look: false")
    cases = design.get("cases", [])
    if len(cases) != 24 or len({c['case'] for c in cases}) != len(cases):
        raise ValueError("measurement design requires exactly 24 distinct, predeclared case IDs; no interim subsets")
    for c in cases:
        if type(c["case"]) is not str or not c["case"]:
            raise ValueError("case IDs must be nonempty strings")
        if c["tries"] not in ([1, 2], [1, 2, 3]) or any(type(t) is not int for t in c["tries"]):
            raise ValueError("freeze tries as [1,2] or [1,2,3] for each case")
        steps = c["maintenance_steps"]
        if not steps or len(set(steps)) != len(steps) or 1 in steps:
            raise ValueError("maintenance_steps must be distinct and exclude establishment step 1")
        if any(type(s) is not int or s < 2 for s in steps):
            raise ValueError("maintenance steps use run-exam's integer indices >=2")
        alignment = c.get("checkpoint_alignment", {})
        if c.get("same_checkpoint_order_across_tries") is not True:
            if set(alignment) != {str(t) for t in c["tries"]} or any(
                    sorted(alignment[str(t)]) != sorted(steps) for t in c["tries"]):
                raise ValueError("freeze checkpoint_alignment for every try, or assert same_checkpoint_order_across_tries")
    if design.get("sizing_rule") != SIZING_RULE:
        raise ValueError("design must include the exact frozen sizing_rule (see --make-fixture)")


def load_results(root, design):
    """Fail closed on incomplete pairs, error records, duplicates or unplanned tries.

    Additional arms and establishment steps are counted but not scored. Standalone
    score-claims outputs need explicit IDs because that format contains no IDs.
    """
    validate_design(design)
    lookup = {c["case"]: c for c in design["cases"]}
    expected = {(c["case"], t, a, s) for c in design["cases"]
                for t in c["tries"] for a in ("B", "C") for s in c["maintenance_steps"]}
    found, files = {}, set()
    excluded = {"establishment_or_unselected_steps": 0, "other_arm_trials": 0}

    def add(case, trial, arm, step, row, path, checkpoint=None):
        if arm not in ("B", "C"):
            return
        if case not in lookup or trial not in lookup[case]["tries"]:
            raise ValueError(f"unplanned case/try in {path}: {case}/{trial}")
        if step not in lookup[case]["maintenance_steps"]:
            excluded["establishment_or_unselected_steps"] += 1
            return
        key = (case, trial, arm, step)
        if key in found:
            raise ValueError(f"duplicate checkpoint {key} in {path}")
        for evidence in (row, checkpoint) if checkpoint is not None else (row,):
            if (evidence.get("error") or evidence.get("errors") or evidence.get("judge_error")
                    or type(evidence.get("runs")) is not int or evidence["runs"] <= 0
                    or any(type(evidence.get(k)) is not int or evidence[k] != 0
                           for k in ("error_runs", "invalid_runs"))):
                raise ValueError(f"unadjudicated error at {key}; resolve under the frozen missing-data rule")
        # Old standalone scores dropped validity metadata. Do not infer validity
        # from their positive verdicts: regenerate them from checkpoint evidence.
        if row.get("adjudicated") is not True:
            raise ValueError(f"missing adjudication at {key}; rescore from checkpoint evidence")
        unsafe = row.get("unsafe", row.get("unsafe_checkpoint"))
        correct = row.get("response_correct")
        if type(unsafe) not in (bool, int) or unsafe not in (0, 1):
            raise ValueError(f"missing/nonbinary unsafe at {key}")
        if type(correct) not in (bool, int) or correct not in (0, 1):
            raise ValueError(f"missing/nonbinary response_correct at {key}")
        m = row.get("human_minutes")
        m = m.get("total") if isinstance(m, dict) else m
        if type(m) not in (int, float) or not math.isfinite(m) or m < 0:
            raise ValueError(f"invalid charged minutes at {key}")
        found[key] = (int(unsafe), int(correct), float(m))
        files.add(str(path))

    if design.get("score_files"):
        for entry in design["score_files"]:
            path = root / entry["path"]
            obj = read_json(path)
            add(entry["case"], entry["try"], entry["arm"], entry["step"],
                obj.get("claims_score", obj), path, obj if "claims_score" in obj else None)
    else:
        for path in sorted(root.rglob("*.scorecard.json")):
            card = read_json(path)
            if "trials" not in card:
                continue  # factory scorecards are not exam results
            if card.get("error") or card.get("case_sha256_matches") is not True:
                raise ValueError(f"exam error or unverified case hash in {path}")
            for trial in card["trials"]:
                if trial["arm"] not in ("B", "C"):
                    excluded["other_arm_trials"] += 1
                    continue
                if trial.get("error"):
                    raise ValueError(f"unadjudicated trial error in {path}")
                for step in trial["steps"]:
                    add(card["case"], trial["try"], trial["arm"], step["step"], step, path)
    missing = expected - found.keys()
    if missing:
        raise ValueError(f"missing {len(missing)} planned checkpoints; first: {sorted(missing)[:3]}")
    # Per case: tries x checkpoints x arms(B,C) x (unsafe,correct,minutes).
    arrays = [np.array([[[found[c["case"], t, a, s] for a in ("B", "C")]
                         for s in c.get("checkpoint_alignment", {}).get(str(t), c["maintenance_steps"])] for t in c["tries"]], float)
              for c in design["cases"]]
    return arrays, {"files": [{"path": p, "sha256": digest(p)} for p in sorted(files)],
                    "included_checkpoints": len(found), "excluded": excluded}


def summaries(arrays):
    # Four coordinates used for components: log1p B,C minutes; B,C unsafe rates.
    return [np.column_stack((np.log1p(x[..., 2].sum(axis=1)), x[..., 0].mean(axis=1)))
            for x in arrays]


def effects(arrays, resamples, rng):
    values = [np.column_stack((x[..., 0].mean(axis=1), x[..., 2].sum(axis=1))) for x in arrays]
    point = np.mean([x.mean(axis=0) for x in values], axis=0)
    draws = np.zeros((resamples, 4))
    # Independent inner samples even when a case is selected twice.
    for j in range(len(values)):
        indices = rng.integers(len(values), size=resamples)
        for i, x in enumerate(values):
            where = np.flatnonzero(indices == i)
            if len(where):
                inner = rng.integers(len(x), size=(len(where), len(x)))
                draws[where] += x[inner].mean(axis=1) / len(values)
    delta = draws[:, 1] - draws[:, 0]
    b, c = draws[:, 2], draws[:, 3]
    saving_lo = np.where(b > 0, 1-np.divide(c, b, out=np.zeros_like(c), where=b > 0), -np.inf)
    saving_hi = np.where((b == 0) & (c == 0), 1., saving_lo)
    qs = lambda x, ps: [quantile(x.tolist(), p) for p in ps]
    safety_ci = qs(delta, [.025, .975])
    time_ci = [qs(saving_lo, [.025])[0], qs(saving_hi, [.975])[0]]
    safety_one = qs(delta, [.05, .95])
    time_one = [qs(saving_lo, [.05])[0], qs(saving_hi, [.95])[0]]
    informative = bool(np.ptp(delta) > 1e-14)
    result = decision(safety_one, time_one, informative, point[2] > 0)
    counts = {a: [int(sum(x[..., i, 0].sum() for x in arrays)),
                  sum(x.shape[0]*x.shape[1] for x in arrays)] for i, a in enumerate(("B", "C"))}
    return {
        "unsafe_difference_C_minus_B": {"estimate": float(point[1]-point[0]), "ci95": safety_ci,
            "lower_one_sided95": safety_one[0], "upper_one_sided95": safety_one[1]},
        "minutes_saving": {"estimate": float(1-point[3]/point[2]) if point[2] > 0 else None,
            "ci95": time_ci, "lower_one_sided95": time_one[0], "upper_one_sided95": time_one[1]},
        "minutes_difference_C_minus_B": {"estimate": float(point[3]-point[2]),
            "ci95": qs(draws[:, 3]-draws[:, 2], [.025, .975])},
        "minutes_per_try": dict(zip(("B", "C"), point[2:].tolist())),
        "unsafe_rate": dict(zip(("B", "C"), point[:2].tolist())),
        "safety_informative": informative, "rule_C": result,
        "interpretation": "supports H1" if result["supports_H1"] else "not enough data to tell",
        "pooled_comparison_only": {"arms": {a: {"unsafe": k, "checkpoints": n,
            "wilson95_independent": wilson(k, n)} for a, (k, n) in counts.items()},
            "newcombe95_C_minus_B": newcombe(*counts["C"], *counts["B"]),
            "warning": "Unpaired and unclustered; different pooled weights with unequal tries/steps; never a fallback."}}


def agreement_point(case_values):
    # Each element is tries x checkpoints. All pairs compare the SAME checkpoint.
    ds, ps = [], []
    for x in case_values:
        n = len(x)
        k = x.sum(axis=0)
        ds.append(float(np.mean(2*k*(n-k)/(n*(n-1)))))
        ps.append(float(x.mean()))
    d, p = float(np.mean(ds)), float(np.mean(ps))
    chance_disagreement = 2*p*(1-p)
    return d, 1-d/chance_disagreement if chance_disagreement > 1e-14 else None


def consistency(arrays, design, resamples, rng):
    result = {}
    selections = rng.integers(len(arrays), size=(resamples, len(arrays)))
    for arm, ai in (("B", 0), ("C", 1)):
        result[arm] = {}
        for metric, mi in (("unsafe", 0), ("response_correct", 1)):
            vals = [x[..., ai, mi] for x in arrays]
            point = agreement_point(vals)
            boot = [agreement_point([vals[i] for i in selected]) for selected in selections]
            kappas = [p[1] for p in boot if p[1] is not None]
            result[arm][metric] = {
                "disagreement": {"estimate": point[0],
                    "ci95": np.quantile([p[0] for p in boot], [.025, .975]).tolist()},
                "fleiss_kappa_equal_case": {"estimate": point[1],
                    "ci95_conditional_on_defined": np.quantile(kappas, [.025, .975]).tolist() if kappas else None,
                    "undefined_bootstrap_samples": resamples-len(kappas)},
                "per_case_checkpoint": [{"case": c["case"], "step": s, "tries": len(x),
                    "disagreeing_pairs": int(x[:, j].sum()*(len(x)-x[:, j].sum())),
                    "pairs": math.comb(len(x), 2)}
                    for c, x in zip(design["cases"], vals) for j, s in enumerate(c["maintenance_steps"])]}
    return result


def psd(matrix):
    eig, vec = np.linalg.eigh(matrix)
    return (vec * np.maximum(eig, 0)) @ vec.T


def components(values):
    means = np.array([x.mean(axis=0) for x in values])
    within = np.array([np.cov(x, rowvar=False, ddof=1) for x in values])
    raw = np.cov(means, rowvar=False, ddof=1) - np.mean(
        [w/len(x) for w, x in zip(within, values)], axis=0)
    return psd(raw), within.mean(axis=0), raw


def variance_report(values, resamples, rng):
    between, within, raw = components(values)
    transforms = {"B_log1p_minutes": [1, 0, 0, 0], "C_log1p_minutes": [0, 1, 0, 0],
                  "C_minus_B_log1p_minutes": [-1, 1, 0, 0],
                  "B_unsafe_rate": [0, 0, 1, 0], "C_unsafe_rate": [0, 0, 0, 1],
                  "C_minus_B_unsafe_rate": [0, 0, -1, 1]}
    boot = [components([values[i] for i in rng.integers(len(values), size=len(values))])[:2]
            for _ in range(resamples)]
    out = {"coordinates": ["log1p_B_minutes", "log1p_C_minutes", "B_unsafe_rate", "C_unsafe_rate"],
           "between_covariance": between.tolist(), "within_covariance": within.tolist(),
           "raw_between_covariance": raw.tolist(), "components": {},
           "method": "Equal-case within covariance; sample covariance of case means minus mean(S_i/n_i). "
                     "Negative eigenvalues projected to zero; raw estimates retained. Case-only percentile bootstrap.",
           "zero_minute_transform": "log(1 + total charged minutes); includes genuine zeros, no dropped tries.",
           "within_interpretation": "Includes stochastic checkpoint outcomes, not a separately identified latent agent propensity."}
    for name, v in transforms.items():
        v = np.array(v)
        out["components"][name] = {label: {"estimate": float(v @ matrix @ v),
            "ci95": np.quantile([v @ b[j] @ v for b in boot], [.025, .975]).tolist()}
            for j, (label, matrix) in enumerate((("between_case", between), ("between_try_within_case", within)))}
    return out


def sizing_parameters(variance):
    transform = np.array([[0, 0, -1, 1], [1, 0, 0, 0], [0, 1, 0, 0]])
    return tuple(transform @ np.array(variance[k]) @ transform.T
                 for k in ("between_covariance", "within_covariance"))


def generator_check(rng, between, within, base, studies=3000):
    # Extra repeats here reduce Monte Carlo cancellation in G = Var(mean)-W/n.
    # These are generator diagnostics, not a proposed twelve-try exam design.
    nt = 12
    data = generate_measured_batch(rng, studies, 8, nt, between, within, base)
    coords = np.concatenate((data[..., :1], np.log1p(data[..., 1:])), axis=-1)
    # Compare case and try covariances over many independent clusters.
    means = coords.mean(axis=2).reshape(-1, 3)
    residual = coords-coords.mean(axis=2, keepdims=True)
    w = np.einsum("ni,nj->ij", residual.reshape(-1, 3), residual.reshape(-1, 3))/(studies*8*(nt-1))
    g = np.cov(means, rowvar=False)-w/nt
    checks = []
    scales = np.sqrt(np.maximum(np.diag(between+within), 1e-12))
    vectors = list(np.eye(3)) + [np.eye(3)[i]/scales[i]-np.eye(3)[j]/scales[j]
                              for i, j in itertools.combinations(range(3), 2)]
    for label, target, got in (("between", between, g), ("within", within, w)):
        # Standardized pair contrasts also check cross-covariances, which matter
        # for joint power. Four Monte Carlo SEs prevent spurious failures near 0.
        for v in vectors:
            a, b = float(v @ target @ v), float(v @ got @ v)
            mc_tolerance = 4*math.sqrt(2/(studies*8)) * float(
                v @ (between+within/nt if label == "between" else within) @ v)
            tolerance = max(1e-10, .25*a, mc_tolerance)
            checks.append({"component": label, "contrast": v.tolist(), "target": a,
                           "achieved": b, "tolerance": tolerance,
                           "acceptable": bool(abs(a-b) <= tolerance)})
    means = data[..., 1:].mean(axis=(0, 1, 2))
    mean_ok = bool(np.all(np.abs(means/[base, base*.5]-1) < .10))
    return {"studies": studies, "diagnostic_tries": nt, "variance_checks": checks, "minute_means": means.tolist(),
            "target_minute_means": [base, base*.5],
            "acceptable": mean_ok and all(c["acceptable"] for c in checks)}


def power_at(rng, n, tries, between, within, base, simulations, resamples, saving=.5, delta=0.):
    counts = np.zeros(4, int)
    for start in range(0, simulations, 16):
        data = generate_measured_batch(rng, min(16, simulations-start), n, tries,
                                      between, within, base, saving, delta)
        ds, es = bootstrap_batch(rng, data, resamples)
        counts += flags(data, ds, es, .05).sum(axis=0)
    return {name: {"count": int(k), "probability": float(k/simulations), "monte_carlo95": wilson(int(k), simulations)}
            for name, k in zip(("joint", "minutes", "safety", "collapsed_safety"), counts)}


def next_round(variance, effect, *, quick=False):
    between, within = sizing_parameters(variance)
    base = effect["minutes_per_try"]["B"]
    output = {"rule": SIZING_RULE, "planning_only": True, "quick_validation_only": quick,
              "components_between": between.tolist(), "components_within": within.tolist(),
              "assumptions": "Gaussian case/try summary effects with measured cross-covariances; "
                  "bounded rate difference, censored shifted-lognormal minutes. Does not simulate "
                  "discrete checkpoints, or unidentified failures. Component uncertainty excluded.",
              "designs": {}}
    if not effect["safety_informative"] or base <= 0:
        output["status"] = "undetermined: collapsed safety or zero baseline cannot identify planning noise"
        return output
    rng = np.random.default_rng(20261017)
    output["generator_check"] = generator_check(rng, between, within, base, 300 if quick else 3000)
    simulations, resamples = (99, 99) if quick else (2500, 999)
    grid = [24, 48] if quick else [24, 36, 48, 72, 96, 128, 192, 256, 384, 512]
    output.update(simulations=simulations, bootstrap_resamples=resamples, case_grid=grid, seed=20261017)
    for tries in (2, 3):
        scan, candidate = [], None
        for n in grid:
            p = power_at(rng, n, tries, between, within, base, simulations, resamples)
            scan.append({"cases": n, **p})
            if not quick:
                print(f"Sizing: {n} cases x {tries} tries: joint power {p['joint']['probability']:.3f}", flush=True)
            if candidate is None and p["joint"]["monte_carlo95"][0] >= .8:
                candidate = n
                break
        row = {"scan": scan, "candidate_cases": candidate, "recommended_cases": None}
        if candidate is not None:
            boundaries = {"time_at_30pct": power_at(rng, candidate, tries, between, within, base,
                            simulations, resamples, saving=.3),
                          "safety_at_plus5pt": power_at(rng, candidate, tries, between, within, base,
                            simulations, resamples, delta=.05)}
            row["boundary_checks"] = boundaries
            calibrated = (boundaries["time_at_30pct"]["minutes"]["monte_carlo95"][0] <= .05
                          and boundaries["safety_at_plus5pt"]["safety"]["monte_carlo95"][0] <= .05)
            if calibrated and output["generator_check"]["acceptable"] and not quick:
                row["recommended_cases"] = candidate
            row["status"] = "conditional recommendation" if row["recommended_cases"] else "withheld: quick run, model mismatch or boundary miscalibration"
        else:
            row["status"] = f"beyond {grid[-1]} or undetermined on this grid"
        output["designs"][str(tries)] = row
    return output


def mixed_sizing_sensitivity(variance, effect, sizing, secondary, quick=False):
    model = secondary["mixed_effects"]["sizing_input"]
    output = {"reference": "bootstrap components always retain the primary sizing result", "comparisons": []}
    agreed = model["eligible"]
    matrices = []
    contrasts = list(np.eye(4)) + [np.array([-1, 1, 0, 0]), np.array([0, 0, -1, 1])]
    for name in ("between_covariance", "within_covariance"):
        ref, candidate = np.array(variance[name]), np.array(model[name])
        for v in contrasts:
            a, b = float(v@ref@v), float(v@candidate@v)
            okay = abs(a-b) <= max(1e-5, .25*a)
            output["comparisons"].append({"component": name, "contrast": v.tolist(), "bootstrap": a, "mixed_model": b, "agrees": okay})
            agreed &= okay
        candidate[:2, 2:] = ref[:2, 2:]
        candidate[2:, :2] = ref[2:, :2]
        projected = psd(candidate)
        agreed &= np.linalg.norm(projected-candidate) <= .1*max(1e-12, np.linalg.norm(candidate))
        matrices.append(projected)
    output["model_input_accepted_for_sensitivity"] = bool(agreed)
    if not agreed:
        output["status"] = "bootstrap reference retained: model singular/unstable or variance disagreement"
        return output
    model_variance = dict(zip(("between_covariance", "within_covariance"), matrices))
    g, w = sizing_parameters(model_variance)
    rng = np.random.default_rng(20261018)
    output["power_at_reference_candidate"] = {}
    for tries, row in sizing["designs"].items():
        if row["candidate_cases"] is not None:
            output["power_at_reference_candidate"][tries] = power_at(rng, row["candidate_cases"], int(tries), g, w,
                effect["minutes_per_try"]["B"], 99 if quick else 2500, 99 if quick else 999)
    output["status"] = "model feeds a secondary power check; frozen bootstrap sizing recommendation unchanged"
    return output


def subset_simulation(seed=41, simulations=20000):
    """Fixed, deliberately nonrepresentative subset tests equal-case weights."""
    rng = np.random.default_rng(seed)
    truth = np.linspace(.05, .65, 24)
    subset = np.arange(24) >= 16  # harder cases get try 3, fixed before all outcomes
    x = rng.binomial(1, truth[None, :, None], size=(simulations, 24, 3))
    estimates = np.where(subset[None, :], x.mean(axis=2), x[..., :2].mean(axis=2)).mean(axis=1)
    naive = (x[..., :2].sum(axis=(1, 2))+x[:, subset, 2].sum(axis=1))/(48+subset.sum())
    minutes = 100*truth
    y = minutes[None, :, None]+rng.normal(0, 3, size=x.shape)
    m = np.where(subset[None, :], y.mean(axis=2), y[..., :2].mean(axis=2)).mean(axis=1)
    return {"simulations": simulations, "seed": seed,
            "rate_truth": float(truth.mean()), "equal_case_rate_mean": float(estimates.mean()),
            "rate_bias": float(estimates.mean()-truth.mean()),
            "rate_bias_mc95": (estimates.mean()-truth.mean()+np.array([-1, 1])*1.96*estimates.std(ddof=1)/math.sqrt(simulations)).tolist(),
            "naive_pooled_rate_mean": float(naive.mean()),
            "minutes_truth": float(minutes.mean()), "equal_case_minutes_mean": float(m.mean()),
            "minutes_bias_mc95": (m.mean()-minutes.mean()+np.array([-1, 1])*1.96*m.std(ddof=1)/math.sqrt(simulations)).tolist(),
            "note": "Checkpoint rate and minute means are unbiased; the ratio saving need not be exactly unbiased."}


def report(root, design_path, resamples=10000, seed=20261017, quick=False, include_secondary=True):
    design = read_json(design_path)
    calibration = root/design["bayesian_calibration_file"] if design.get("bayesian_calibration_file") else None
    if include_secondary:
        validate_secondary_design(design, calibration)
    arrays, audit = load_results(root, design)
    rng = np.random.default_rng(seed)
    effect = effects(arrays, resamples, rng)
    variance = variance_report(summaries(arrays), resamples, rng)
    result = {"measurement_round": True, "synthetic": design.get("synthetic", False),
            "design_sha256": digest(design_path), "case_count": len(arrays),
            "tries_per_case": [len(x) for x in arrays], "bootstrap_resamples": resamples, "seed": seed,
            "source_sha256": {p: digest(Path(__file__).with_name(p)) for p in
                ("report_round.py", "cluster_bootstrap.py", "steadiness.py", "secondary_round.py")},
            "estimand": "Equal case, equal try within case; minutes summed and unsafe averaged over frozen maintenance checkpoints.",
            "audit": audit, "effects": effect,
            "consistency": consistency(arrays, design, resamples, rng), "variance": variance,
            "next_round_sizing": next_round(variance, effect, quick=quick),
            "third_try_subset_rule": SUBSET_RULE, "subset_simulation": subset_simulation(),
            "limitations": ["Percentile cluster bootstrap coverage is approximate with 24 cases, especially rare failures.",
                "Collapsed safety cannot certify non-inferiority: an empirical bootstrap cannot invent unseen failures.",
                "Kappa depends on prevalence; undefined when every label is identical. Read plain disagreement first.",
                "Variance estimates are noisy at 2–3 tries, assume exchangeable tries, and truncate negative component eigenvalues.",
                "A 95% interval is uncertainty under this case-generating design, not a guarantee for production.",
                "Freeze design, subset, scoring and script hashes before scoring; run once after completion. The script cannot verify when a file was frozen."]}
    if include_secondary:
        result["secondary"] = run_secondary(arrays, design, quick=quick, calibration_file=calibration)
        result["secondary"]["mixed_effects"]["sizing_sensitivity"] = mixed_sizing_sensitivity(
            variance, effect, result["next_round_sizing"], result["secondary"], quick)
    return result


def percent(value):
    if value is None:
        return "undefined"
    if not math.isfinite(value):
        return "unbounded"
    return f"{100*value:.1f}%"


def markdown(result):
    e = result["effects"]
    s, d = e["minutes_saving"], e["unsafe_difference_C_minus_B"]
    interval = lambda x: f"{percent(x[0])} to {percent(x[1])}"
    points_interval = lambda x: f"{100*x[0]:+.1f} to {100*x[1]:+.1f} percentage points"
    lines = ["# Measurement round" + (" — SYNTHETIC, not evidence about Unbug" if result["synthetic"] else ""), "",
        f"{result['case_count']} cases; {min(result['tries_per_case'])}–{max(result['tries_per_case'])} tries per arm. "
        f"Result: **{e['interpretation']}**. No interim look.", "",
        f"Charged human-time saving: **{percent(s['estimate'])}**, two-sided 95% interval {interval(s['ci95'])}. "
        f"Rule C's one-sided lower bound is {percent(s['lower_one_sided95'])}; it must exceed 30%.", "",
        f"Safety difference C − B: **{100*d['estimate']:+.1f} percentage points**, two-sided 95% interval "
        f"{points_interval(d['ci95'])}. Rule C's one-sided upper bound is "
        f"{100*d['upper_one_sided95']:+.1f} points; it must be at most +5 points.", "",
        f"Average charged minutes per try: B {e['minutes_per_try']['B']:.1f}; C {e['minutes_per_try']['C']:.1f}. "
        f"Newcombe comparison interval: {points_interval(e['pooled_comparison_only']['newcombe95_C_minus_B'])}; "
        "it ignores pairing/clustering and does not decide the result.", ""]
    for arm in ("B", "C"):
        for metric, label in (("unsafe", "unsafe status"), ("response_correct", "response correctness")):
            c = result["consistency"][arm][metric]
            kappa = c["fleiss_kappa_equal_case"]
            k = kappa["estimate"]
            ki = kappa["ci95_conditional_on_defined"]
            lines.append(f"- {arm}, {label}: two tries disagree {percent(c['disagreement']['estimate'])} of the time "
                f"(95% interval {interval(c['disagreement']['ci95'])}); Fleiss kappa "
                + (f"{k:.2f}" if k is not None else "undefined (no label variation)")
                + (f" (95% interval {ki[0]:.2f} to {ki[1]:.2f}, defined resamples only)." if ki else "."))
    lines += ["", "Between-case variance measures how cases differ; within-case variance measures repeat noise. "
        "The JSON gives both with intervals for each arm and the paired difference, using log(1 + minutes) "
        "and unsafe rates. More cases reduce both sources; more tries mainly reduce repeat noise.", ""]
    sizing = result["next_round_sizing"]
    for tries, row in sizing["designs"].items():
        lines.append(f"Next round at {tries} tries: " +
            (f"{row['recommended_cases']} cases conditionally recommended." if row["recommended_cases"] else row["status"]+".") )
    if not sizing["designs"]:
        lines.append("Next-round size: " + sizing["status"] + ".")
    if sizing["quick_validation_only"]:
        lines += ["", "**Quick validation only:** the reduced sizing scan cannot recommend a sample size."]
    lines += ["", "Sizing assumes a true 50% saving and equal safety; it is conditional on a model and uncertain "
        "measured variance, not a promise of 80% power. Freeze a new round separately.", "",
        "Third tries count inside their case: every case has equal weight. The subset must be chosen before "
        "scores; pooling all tries would give those cases extra weight. JSON includes a small bias simulation.", "",
        "A non-pass means **not enough data to tell**, including a wide or collapsed interval. "
        "The JSON retains the directional protocol diagnostics; this measurement round does not label Unbug a failure.", ""]
    if "secondary" in result:
        lines.extend(markdown_secondary(result["secondary"]))
    return "\n".join(lines)


def make_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(27)
    cases = [{"case": f"synthetic-{i:02}", "tries": [1, 2, 3] if i % 3 == 0 else [1, 2],
              "same_checkpoint_order_across_tries": True,
              "maintenance_steps": [2, 3, 4, 5]} for i in range(24)]
    design = {"synthetic": True, "rule": "C", "interim_look": False,
              "subset_selection": "Every third synthetic case, fixed before outcomes, demonstration only",
              "cases": cases, "sizing_rule": SIZING_RULE, "secondary_plan": SECONDARY_PLAN,
              "covariate_plan": [{"name": name, "source": source, "fixed_before_contestants": True,
                    "target_mean": 0.} for name, source in (("tester_success", "factory_difficulty"),
                        ("strategy_minutes", "scripted_strategy"), ("ingredient_count", "case_ingredients"))],
              "covariates": {c["case"]: {"tester_success": ((i*7)%11+1)/12,
                  "strategy_minutes": 20+5*(i%8), "ingredient_count": 1+i%3} for i, c in enumerate(cases)}}
    for covariate in design["covariate_plan"]:
        covariate["target_mean"] = float(np.mean([v[covariate["name"]] for v in design["covariates"].values()]))
    for c in cases:
        trials = []
        rate = rng.uniform(.08, .3)
        demand = rng.lognormal(0, .3)
        for t in c["tries"]:
            shared_u = rng.random(4)
            for arm in ("B", "C"):
                steps = [{"step": 1, "unsafe": False, "response_correct": True,
                          "human_minutes": {"total": 10000}}]  # must not enter maintenance
                for j, step in enumerate(c["maintenance_steps"]):
                    unsafe = bool((shared_u[j] if rng.random() < .5 else rng.random()) < rate)
                    steps.append({"step": step, "unsafe": unsafe,
                        "response_correct": not unsafe and bool(rng.random() < .9),
                        "human_minutes": {"total": float(5*rng.poisson(demand*(5 if arm == 'B' else 2))+60*unsafe)},
                        "error": None, "judge_error": 0, "runs": 3, "error_runs": 0,
                        "invalid_runs": 0, "adjudicated": True})
                trials.append({"arm": arm, "try": t, "steps": steps, "error": None})
        card = {"exam": c["case"]+".exam-synthetic", "case": c["case"],
                "case_sha256_matches": True, "trials": trials, "synthetic": True}
        (root/(c["case"]+".scorecard.json")).write_text(json.dumps(card, indent=2)+"\n")
    (root/"design.json").write_text(json.dumps(design, indent=2)+"\n")
    return root/"design.json"


def self_test():
    with tempfile.TemporaryDirectory(prefix="round-report-") as tmp:
        root = Path(tmp)
        dp = make_fixture(root)
        design = read_json(dp)
        arrays, audit = load_results(root, design)
        try:
            validate_design(dict(design, cases=design["cases"][:8]))
        except ValueError:
            pass
        else:
            raise AssertionError("interim case subset accepted")
        assert len(arrays) == 24 and audit["excluded"]["establishment_or_unselected_steps"] == 112
        assert audit["included_checkpoints"] == 448
        e = effects(arrays, 199, np.random.default_rng(6))
        assert e == effects(arrays, 199, np.random.default_rng(6))
        assert e["minutes_per_try"]["B"] < 10000
        assert agreement_point([np.array([[0, 1], [1, 0]])]) == (1., -1.)
        assert agreement_point([np.zeros((3, 2))]) == (0., None)
        assert agreement_point([np.array([[0], [0], [1]])])[0] == 2/3
        assert agreement_point([np.zeros((2, 1)), np.array([[0], [0], [1]])])[0] == 1/3
        unequal = [np.zeros((n, 1, 2, 3)) for n in (2, 3)]
        unequal[0][..., 2] = 10
        unequal[1][..., 2] = 30
        unequal[1][..., 0] = 1
        eq = effects(unequal, 99, np.random.default_rng(8))
        assert eq["minutes_per_try"]["B"] == 20 and eq["unsafe_rate"]["B"] == .5
        # Known variance components, with uneven try counts and paired covariance.
        rng = np.random.default_rng(91)
        common = rng.normal(size=(12000, 1, 4))*[2, 1, .2, .1]
        noise = rng.normal(size=(12000, 3, 4))*[1, .5, .1, .05]
        values = [x[:2+i % 2] for i, x in enumerate(common+noise)]
        g, w, _ = components(values)
        assert np.allclose(np.diag(g), [4, 1, .04, .01], rtol=.07)
        assert np.allclose(np.diag(w), [1, .25, .01, .0025], rtol=.07)
        # Constant paired saving, zero baseline and the collapsed guard.
        fixed = [x.copy() for x in arrays]
        for x in fixed:
            x[..., 0] = 0
            x[..., 2] = 10
            x[..., 1, 2] = 5
        f = effects(fixed, 99, rng)
        assert f["minutes_saving"]["estimate"] == .5
        assert f["minutes_saving"]["ci95"] == [.5, .5]
        assert not f["rule_C"]["supports_H1"] and not f["safety_informative"]
        for x in fixed:
            x[..., 2] = 0
        f = effects(fixed, 99, rng)
        assert f["minutes_saving"]["estimate"] is None and not f["rule_C"]["supports_H1"]
        assert not decision([0, .05], [.3, .8])["supports_H1"]
        assert decision([0, .05], [.301, .8])["supports_H1"]
        # Score-claims format is ID-free: explicit sidecar maps it to pairs.
        mapping = []
        for ci, c in enumerate(design["cases"]):
            for ti, t in enumerate(c["tries"]):
                for ai, a in enumerate(("B", "C")):
                    for sj, s in enumerate(c["maintenance_steps"]):
                        path = f"score-{ci}-{t}-{a}-{s}.json"
                        v = arrays[ci][ti, sj, ai]
                        (root/path).write_text(json.dumps({"adjudicated": True, "runs": 3, "error_runs": 0,
                            "invalid_runs": 0, "unsafe_checkpoint": bool(v[0]),
                            "response_correct": bool(v[1]), "human_minutes": {"total": v[2]}}))
                        mapping.append({"case": c["case"], "try": t, "arm": a, "step": s, "path": path})
        standalone = dict(design, score_files=mapping)
        other, _ = load_results(root, standalone)
        assert all(np.array_equal(x, y) for x, y in zip(arrays, other))
        aligned_cases = []
        for c in design["cases"]:
            aligned_cases.append(dict(c, same_checkpoint_order_across_tries=False,
                checkpoint_alignment={str(t): list(reversed(c["maintenance_steps"])) if t == 2 else c["maintenance_steps"]
                                      for t in c["tries"]}))
        swapped = [dict(e, step=7-e["step"]) if e["try"] == 2 else e for e in mapping]
        aligned, _ = load_results(root, dict(design, cases=aligned_cases, score_files=swapped))
        assert all(np.array_equal(x, y) for x, y in zip(arrays, aligned))
        # Missing, duplicate and failed checkpoints must not quietly disappear.
        for entries in (mapping[1:], mapping+mapping[:1]):
            try:
                load_results(root, dict(design, score_files=entries))
            except ValueError:
                pass
            else:
                raise AssertionError("incomplete/duplicate data accepted")
        bad_path = root/mapping[0]["path"]
        bad = read_json(bad_path)
        for field, val in (("human_minutes", -1), ("response_correct", None), ("unsafe_checkpoint", .1), ("judge_error", True)):
            bad_path.write_text(json.dumps(dict(bad, **{field: val})))
            try:
                load_results(root, standalone)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid {field} accepted")
        bias = subset_simulation()
        assert abs(bias["rate_bias"]) < .002
        assert abs(bias["naive_pooled_rate_mean"]-bias["rate_truth"]) > .02
        assert abs(bias["equal_case_minutes_mean"]-bias["minutes_truth"]) < .03
        result = report(root, dp, 99, quick=True, include_secondary=False)
        json.dumps(json_safe(result), allow_nan=False)
        assert "not enough data to tell" in markdown(result) or "supports H1" in markdown(result)
        assert all(r["recommended_cases"] is None for r in result["next_round_sizing"]["designs"].values())
        from secondary_round import self_test as secondary_self_test
        secondary_self_test(arrays, design)
    print("report_round self-test: PASS (formats, maintenance selection, pairing/errors, effects/guards, "
          "Fleiss/disagreement, variance recovery, subset bias, sizing smoke, strict JSON/Markdown)")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("results", type=Path, nargs="?")
    p.add_argument("--design", type=Path)
    p.add_argument("--out", type=Path, default=Path("analysis/round_report"), help="output prefix for .json and .md")
    p.add_argument("--bootstrap", type=int, default=10000)
    p.add_argument("--seed", type=int, default=20261017)
    p.add_argument("--quick", action="store_true", help="sizing smoke only; never recommends a size")
    p.add_argument("--make-fixture", type=Path, metavar="DIR")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    if args.make_fixture:
        if args.make_fixture.exists() and any(args.make_fixture.iterdir()):
            p.error("fixture directory must be empty to avoid overwriting results")
        print(make_fixture(args.make_fixture))
        return
    if args.results is None or args.design is None:
        p.error("results directory and --design are required")
    if args.bootstrap < 99:
        p.error("use at least 99 bootstrap draws (10000 for the completed round)")
    result = report(args.results, args.design, args.bootstrap, args.seed, args.quick)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps(json_safe(result), indent=2, allow_nan=False)+"\n")
    args.out.with_suffix(".md").write_text(markdown(result))
    print(f"Wrote {args.out.with_suffix('.json')} and {args.out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
