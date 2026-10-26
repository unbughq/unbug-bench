#!/usr/bin/env python3
"""Proposed v2 power study, standard library only; no network or paid calls.

Default: audit pilots, simulate 8 cases x 5 paired tries x 4--6 checkpoints,
then scan effects and case counts. JSON output contains Monte Carlo intervals.
All defaults are assumptions, not estimates from the one-case, zero-charge pilot.
"""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import tarfile
import tempfile
import time

from cluster_bootstrap import bootstrap, decision, intervals, json_safe, wilson


LEVELS = {
    "low": {"case_rho": 0.0, "try_rho": 0.05, "minute_case_sd": 0.15, "minute_try_sd": 0.35},
    "middle": {"case_rho": 0.03, "try_rho": 0.20, "minute_case_sd": 0.40, "minute_try_sd": 0.70},
    "high": {"case_rho": 0.10, "try_rho": 0.40, "minute_case_sd": 0.80, "minute_try_sd": 1.10},
}


def pilot_audit(root, pilot_dir):
    """Extract originals to a disposable temp directory; retain only audit facts."""
    reports = {p.name: json.loads(p.read_text()) for p in sorted((root / "report/data").glob("*.json"))}
    archives = sorted(pilot_dir.glob("*.tgz")) + sorted((pilot_dir / "round2").glob("*.tgz"))
    if not archives:
        raise FileNotFoundError(f"no pilot archives in {pilot_dir}")
    output, rows = [], []
    arm_map = {"practice-A": "A", "practice-c": "C", "practice-c0": "C0", "practice-gpt": "gpt"}
    with tempfile.TemporaryDirectory(prefix="unbug-v2-power-") as temp:
        for i, archive in enumerate(archives):
            round_id = 2 if archive.parent.name == "round2" else 1
            arm = arm_map.get(archive.stem, archive.stem)
            directory = Path(temp) / str(i)
            with tarfile.open(archive) as tar:
                tar.extractall(directory, filter="data")
            trials = list(directory.glob("*/task__*/result.json"))
            if len(trials) != 1:
                raise ValueError(f"expected one Harbor trial in {archive}, got {len(trials)}")
            trial = json.loads(trials[0].read_text())
            step_rows, mismatches = [], []
            for step in trial["step_results"]:
                name = step["step_name"]
                rewards = step["verifier_result"]["rewards"]
                cp = json.loads((trials[0].parent / "steps" / name / "verifier/checkpoint.json").read_text())
                score = cp["claims_score"]
                unsafe = int(score["unsafe_checkpoint"])
                minutes = score["human_minutes"]["total"]
                for metric, value in (("unsafe", unsafe), ("human_minutes", minutes), ("runs", cp["runs"])):
                    if rewards[metric] != value:
                        mismatches.append([name, metric, "checkpoint vs reward", value, rewards[metric]])
                report_file = "round2-unbug-v0.2.json" if arm == "C-v0.2" else f"round{round_id}.json"
                report = reports.get(report_file)
                if report is not None:
                    report_arm = arm.lower() if round_id == 1 and arm in ("C", "C0") else arm
                    saved = (report if arm == "C-v0.2" else report[report_arm])[name]
                    for metric, value in (("hm", minutes), ("runs", cp["runs"]), ("fa", score["counts"].get("false_assurance", 0)), ("reward", rewards["reward"])):
                        if saved[metric] != value:
                            mismatches.append([name, metric, "report vs checkpoint/reward", saved[metric], value])
                oversell = any(path["violated_runs"] > 0 for path in cp["paths"].values())
                row = {"round": round_id, "arm": arm, "step": name, "unsafe_original": unsafe,
                       "human_minutes": minutes, "judge_runs": cp["runs"],
                       "oracle_oversell": oversell, "false_assurance": score["counts"].get("false_assurance", 0)}
                step_rows.append(row)
                rows.append(row)
            output.append({"archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                           "round": round_id, "arm": arm, "checkpoints": len(step_rows),
                           "trial_rewards": trial["verifier_result"]["rewards"], "steps": step_rows,
                           "mismatches": mismatches})
    return {"independent_cases": 1, "numpy_installed": importlib.util.find_spec("numpy") is not None,
            "archives": output, "report_data_read": list(reports),
            "checkpoints": len(rows), "unsafe_original": sum(r["unsafe_original"] for r in rows),
            "oracle_oversell_checkpoints": sum(r["oracle_oversell"] for r in rows),
            "total_charged_minutes": sum(r["human_minutes"] for r in rows),
            "warning": "Round-1 archives/report retain four grading-driven false-assurance failures. BRIEF-v2 says these were corrected. Do not treat 4/16 as the corrected failure rate or independent new cases. No between-case variance or positive-minute variance is estimable."}


def beta_at(rng, mean, rho):
    if mean <= 0 or mean >= 1 or rho == 0:
        return mean
    concentration = 1 / rho - 1
    return rng.betavariate(mean * concentration, (1 - mean) * concentration)


def lognormal_unit(rng, sd):
    return math.exp(rng.gauss(-sd * sd / 2, sd))


def poisson(rng, mean):
    # Sum independent Poisson chunks to avoid exp(-mean) underflow.
    count = 0
    while mean > 0:
        chunk = min(mean, 20)
        limit, product, n = math.exp(-chunk), rng.random(), 0
        while product > limit:
            product *= rng.random()
            n += 1
        count += n
        mean -= chunk
    return count


def generate(rng, *, cases=8, tries=5, checkpoints=(4, 6), base_rate=0.15,
             safety_difference=0.0, saving=0.5, base_minutes=30.0,
             case_rho=0.03, try_rho=0.20, minute_case_sd=0.40,
             minute_try_sd=0.70, shared_case_rho=0.05, paired_uniform=0.0,
             harm_fraction=1.0):
    """Beta case/try probabilities; paired step count; correlated discrete charges.

    B marginal unsafe probability p; C p+delta. A shared case probability has
    mean p and rho .05. Map it affinely to preserve C's requested marginal mean.
    Arm-specific case Beta draws add heterogeneity; arm-specific try Beta draws
    cluster checkpoints. Shared uniforms optionally correlate paired outcomes.
    Non-harm costs: 5 * Poisson(lognormal demand); harm costs 60 per harmful CP.
    harm_fraction allows false assurance without oversell to have no harm charge.
    This is a charge-distribution model, not a reconstruction of query counts.
    """
    pc = base_rate + safety_difference
    if any(not math.isfinite(v) for v in (base_rate, pc, saving, base_minutes, minute_case_sd, minute_try_sd)):
        raise ValueError("rates, costs and variation must be finite")
    if not 0 <= base_rate <= 1 or not 0 <= pc <= 1 or not 0 <= saving < 1:
        raise ValueError("invalid rate/effect")
    if any(not 0 <= v < 1 for v in (case_rho, try_rho, shared_case_rho)) or not 0 <= paired_uniform <= 1:
        raise ValueError("correlations must be in [0,1)")
    if min(minute_case_sd, minute_try_sd) < 0 or cases < 2 or tries < 1 or not 1 <= checkpoints[0] <= checkpoints[1]:
        raise ValueError("invalid variance or sample size")
    if not 0 <= harm_fraction <= 1:
        raise ValueError("harm_fraction must be in [0,1]")
    nonharm = [base_minutes - 60 * base_rate * harm_fraction,
               base_minutes * (1 - saving) - 60 * pc * harm_fraction]
    if min(nonharm) < -1e-9:
        raise ValueError("target minutes below unavoidable 60-minute harm floor")
    out = []
    for _ in range(cases):
        common_p = beta_at(rng, base_rate, shared_case_rho)
        if pc <= base_rate:
            common_c = common_p * pc / base_rate if base_rate else 0
        else:
            common_c = common_p + (1 - common_p) * (pc - base_rate) / (1 - base_rate)
        p_arm = [beta_at(rng, q, case_rho) for q in (common_p, common_c)]
        common_m = lognormal_unit(rng, 0.35)
        m_arm = [common_m * lognormal_unit(rng, minute_case_sd) for _ in range(2)]
        case = []
        for _ in range(tries):
            n = rng.randint(*checkpoints)
            p_try = [beta_at(rng, q, try_rho) for q in p_arm]
            common_try_m = lognormal_unit(rng, 0.30)
            m_try = [common_try_m * m * lognormal_unit(rng, minute_try_sd) for m in m_arm]
            unsafe, minutes = [0, 0], [0, 0]
            for _ in range(n):
                shared_u = rng.random() if rng.random() < paired_uniform else None
                for a in range(2):
                    harm = (rng.random() if shared_u is None else shared_u) < p_try[a]
                    unsafe[a] += harm
                    charged_harm = harm and (harm_fraction == 1 or rng.random() < harm_fraction)
                    minutes[a] += 60 * charged_harm + 5 * poisson(rng, max(0, nonharm[a]) * m_try[a] / 5)
            case.append(((unsafe[1] - unsafe[0]) / n, minutes[0], minutes[1]))
        out.append(case)
    return out


def simulate(parameters, simulations, resamples, seed):
    digest = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).digest()
    rng = random.Random(seed + int.from_bytes(digest[:8], "big"))
    names = ("safety_noninferior", "minutes_over_30pct", "supports_H1", "falsifies_H1", "inconclusive")
    hits = dict.fromkeys(names, 0)
    raw = dict.fromkeys(names, 0)
    safety_coverage = effort_coverage = degenerate = 0
    for _ in range(simulations):
        cases = generate(rng, **parameters)
        point, safety, effort, _, informative = intervals(cases, bootstrap(cases, resamples, rng))
        for target, rules in ((hits, decision(safety, effort, informative, point[1] > 0)),
                              (raw, decision(safety, effort, True, point[1] > 0))):
            for key in names:
                target[key] += rules[key]
        safety_coverage += safety[0] <= parameters.get("safety_difference", 0) <= safety[1]
        effort_coverage += effort[0] <= parameters.get("saving", 0.5) <= effort[1]
        degenerate += not informative
    def probabilities(counts):
        return {k: {"probability": v / simulations, "monte_carlo95": wilson(v, simulations)} for k, v in counts.items()}
    return {"parameters": parameters, "simulations": simulations, "bootstrap_resamples": resamples,
            "proposed_guarded_rules": probabilities(hits), "literal_protocol_rules": probabilities(raw),
            "safety_ci_coverage": safety_coverage / simulations, "minutes_ci_coverage": effort_coverage / simulations,
            "collapsed_safety_fraction": degenerate / simulations}


def study(args):
    root = Path(__file__).resolve().parent.parent
    audit = pilot_audit(root, args.pilot_dir.expanduser())
    results = []
    cache = {}
    def run(parameters, tag):
        key = json.dumps(parameters, sort_keys=True)
        if key not in cache:
            start = time.monotonic()
            cache[key] = simulate(parameters, args.simulations, args.bootstrap, args.seed)
            r = cache[key]
            results.append(r)
            p = r["proposed_guarded_rules"]
            print(f"{tag}: safety={p['safety_noninferior']['probability']:.3f} minutes={p['minutes_over_30pct']['probability']:.3f} joint={p['supports_H1']['probability']:.3f} ({time.monotonic()-start:.1f}s)", flush=True)
        return cache[key]
    def params(level="middle", **kw):
        return dict(cases=8, tries=5, checkpoints=[args.min_checkpoints, args.max_checkpoints],
                    base_rate=args.base_rate, base_minutes=args.base_minutes,
                    safety_difference=0.0, saving=0.5, paired_uniform=args.paired_uniform,
                    **LEVELS[level]) | kw
    # No difference, exactly the margin, and a clearly larger benefit.
    for level in LEVELS:
        for saving in (0.0, 0.30, 0.50):
            run(params(level, saving=saving), f"8 cases {level} saving={saving}")
    # Pilot floor and rare-to-moderate v2 failure rates. 25% original pilot is a
    # grading artifact, retained as a stress rate rather than a calibrated truth.
    for p in (0.01, 0.05, 0.25):
        run(params(base_rate=p, saving=0.30), f"base unsafe={p} saving=.30")
    run(params(base_rate=0.0, base_minutes=0.0, saving=0.0), "pilot zero-charge floor")
    # Boundary calibration: falsely passing NI at true +5 points should be ~2.5%.
    for level in LEVELS:
        run(params(level, safety_difference=0.05, saving=0.0), f"NI boundary {level}")
    # Minimum true saving detected with 80% probability at the planned sample.
    mde = {}
    for level in LEVELS:
        effort_grid, safety_grid = [], []
        for saving in (0.30, 0.40, 0.50, 0.60, 0.65, 0.69):
            try:
                r = run(params(level, saving=saving), f"effort MDE {level} {saving}")
            except ValueError as e:
                if "harm floor" in str(e):
                    break
                raise
            effort_grid.append({"true_saving": saving, **r["proposed_guarded_rules"]["minutes_over_30pct"]})
        for delta in (0.0, -0.025, -0.05, -0.075, -0.10, -0.125, -args.base_rate):
            if delta < -args.base_rate or delta > 0:
                continue
            r = run(params(level, safety_difference=delta, saving=0.50), f"safety MDE {level} {delta}")
            safety_grid.append({"true_C_minus_B": delta, **r["proposed_guarded_rules"]["safety_noninferior"]})
        mde[level] = {"effort_grid": effort_grid, "safety_grid": safety_grid,
                      "minimum_saving_on_grid_80pct": next((v["true_saving"] for v in effort_grid if v["probability"] >= .8), None),
                      "minimum_safety_improvement_on_grid_80pct": next((-v["true_C_minus_B"] for v in safety_grid if v["probability"] >= .8), None)}
    # Fixed prospective sizes, not a license to add cases after scoring.
    size_scan = {}
    for level in LEVELS:
        scanned = []
        for n in args.case_grid:
            r = run(params(level, cases=n, saving=0.50), f"case count {level} {n}")
            p = r["proposed_guarded_rules"]
            scanned.append({"cases": n, "rules": p})
            # Stop simulation search only when MC lower bound clears 80%.
            if p["supports_H1"]["monte_carlo95"][0] >= .8:
                break
        size_scan[level] = {"grid": scanned,
                            "first_80pct_safety": next((x["cases"] for x in scanned if x["rules"]["safety_noninferior"]["probability"] >= .8), None),
                            "first_80pct_effort": next((x["cases"] for x in scanned if x["rules"]["minutes_over_30pct"]["probability"] >= .8), None),
                            "first_80pct_joint": next((x["cases"] for x in scanned if x["rules"]["supports_H1"]["probability"] >= .8), None),
                            "first_joint_MC_lower_above_80pct": next((x["cases"] for x in scanned if x["rules"]["supports_H1"]["monte_carlo95"][0] >= .8), None)}
    return {"proposal_for_protocol_freeze": True, "seed": args.seed,
            "pilot": audit, "variance_levels": LEVELS,
            "boundary_case_count_for_80pct": {"true_saving_exactly_30pct": None, "true_safety_difference_plus_5points": None,
                                               "reason": "No finite number: a valid 95% two-sided interval crosses a true decision boundary only about 2.5% of the time."},
            "mde": mde, "case_count_scan_equal_safety_50pct_saving": size_scan, "results": results}


def self_test():
    for level in LEVELS:
        cases = generate(random.Random(1), cases=8, **LEVELS[level])
        assert len(cases) == 8 and all(len(c) == 5 for c in cases)
        assert all(-1 <= t[0] <= 1 and t[1] >= 0 and t[2] >= 0 for c in cases for t in c)
    zero = generate(random.Random(1), base_rate=0, base_minutes=0, saving=0)
    assert all(t == (0, 0, 0) for c in zero for t in c)
    # Check that target marginal rates and charge expectations survive mixtures.
    cases = generate(random.Random(9), cases=2000)
    b = sum(t[1] for c in cases for t in c) / 10000
    c = sum(t[2] for cs in cases for t in cs) / 10000
    assert 140 < b < 160 and 68 < c < 82, (b, c)
    assert abs(sum(t[0] for cs in cases for t in cs) / 10000) < .02
    print("power self-test: passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--simulations", type=int, default=400)
    parser.add_argument("--bootstrap", type=int, default=499)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--base-rate", type=float, default=0.15)
    parser.add_argument("--base-minutes", type=float, default=30)
    parser.add_argument("--min-checkpoints", type=int, default=4)
    parser.add_argument("--max-checkpoints", type=int, default=6)
    parser.add_argument("--paired-uniform", type=float, default=0.0)
    parser.add_argument("--single", action="store_true", help="one custom scenario instead of the full sweep")
    parser.add_argument("--cases", type=int, default=8)
    parser.add_argument("--tries", type=int, default=5)
    parser.add_argument("--saving", type=float, default=0.50)
    parser.add_argument("--safety-difference", type=float, default=0.0)
    parser.add_argument("--case-rho", type=float, default=0.03)
    parser.add_argument("--try-rho", type=float, default=0.20)
    parser.add_argument("--minute-case-sd", type=float, default=0.40)
    parser.add_argument("--minute-try-sd", type=float, default=0.70)
    parser.add_argument("--harm-fraction", type=float, default=1.0)
    parser.add_argument("--case-grid", type=int, nargs="+", default=[8, 16, 32, 64, 96, 128, 192, 256])
    parser.add_argument("--pilot-dir", type=Path, default=Path("~/unbug-practice-jobs"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("power_results.json"))
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if args.simulations < 20 or args.bootstrap < 99:
            parser.error("need at least 20 simulations and 99 bootstrap draws")
        args.output = args.output.expanduser().resolve()
        if args.output.parent != Path(__file__).resolve().parent:
            parser.error("output must stay directly inside analysis/")
        if args.single:
            parameters = {k: getattr(args, k) for k in (
                "cases", "tries", "saving", "safety_difference", "base_rate", "base_minutes",
                "case_rho", "try_rho", "minute_case_sd", "minute_try_sd", "paired_uniform", "harm_fraction")}
            parameters["checkpoints"] = [args.min_checkpoints, args.max_checkpoints]
            result = simulate(parameters, args.simulations, args.bootstrap, args.seed)
        else:
            result = study(args)
        args.output.write_text(json.dumps(json_safe(result), indent=2, allow_nan=False) + "\n")
        print(f"Saved {args.output}")
