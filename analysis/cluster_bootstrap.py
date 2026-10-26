#!/usr/bin/env python3
"""Proposed v2 analysis. Stdlib only. Rows must already select scored maintenance steps.

Each case has equal weight; each try within a case has equal weight. Safety is
the mean of try checkpoint rates. Effort is total charged minutes per try;
reduction = 1 - mean(C total)/mean(B total), NOT mean of individual reductions.
Paired cases, try IDs, and steps are required. Checkpoints are never resampled.
"""

import argparse
import json
import math
import random
from statistics import NormalDist


def quantile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    if lo == hi or values[lo] == values[hi]:
        return values[lo]
    if not math.isfinite(values[lo]):
        return values[lo]
    if not math.isfinite(values[hi]):
        return values[hi]
    return values[lo] + (position - lo) * (values[hi] - values[lo])


def wilson(k, n, confidence=0.95):
    if n <= 0 or not 0 <= k <= n:
        raise ValueError("Wilson interval needs 0 <= k <= n and n > 0")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p, d = k / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0, center - half), min(1, center + half)]


def newcombe(k_c, n_c, k_b, n_b):
    """Unpaired Newcombe method 10 (Wilson, no continuity correction).

    Comparison only: ignores BOTH matching and case/try dependence.
    """
    lc, uc = wilson(k_c, n_c)
    lb, ub = wilson(k_b, n_b)
    pc, pb = k_c / n_c, k_b / n_b
    return [max(-1, pc - pb - math.hypot(pc - lc, ub - pb)),
            min(1, pc - pb + math.hypot(uc - pc, pb - lb))]


def prepare(rows):
    """Return cases of paired try tuples: (unsafe C-B, B minutes, C minutes)."""
    groups, counts = {}, {a: [0, 0] for a in ("B", "C")}
    for row in rows:
        if row["arm"] not in counts:
            continue
        if row["unsafe"] not in (0, 1, False, True):
            raise ValueError("unsafe must be binary, not a judge-run rate")
        minutes = row["human_minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not math.isfinite(minutes) or minutes < 0:
            raise ValueError("human_minutes must be finite and nonnegative")
        ids = [row[k] for k in ("case", "try", "step")]
        if any(not isinstance(v, (str, int)) or isinstance(v, bool) for v in ids):
            raise ValueError("case, try and step must be string or integer IDs")
        key = (row["case"], row["try"], row["arm"], row["step"])
        if key in groups:
            raise ValueError("duplicate checkpoint")
        groups[key] = (int(row["unsafe"]), minutes)
        counts[row["arm"]][0] += int(row["unsafe"])
        counts[row["arm"]][1] += 1
    cases = []
    for case in sorted({k[0] for k in groups}, key=str):
        tries = []
        for trial in sorted({k[1] for k in groups if k[0] == case}, key=str):
            arms = {a: {k[3]: v for k, v in groups.items() if k[:3] == (case, trial, a)} for a in counts}
            if not arms["B"] or arms["B"].keys() != arms["C"].keys():
                raise ValueError("unmatched arm/try/step: adjudicate missing data before analysis")
            n = len(arms["B"])
            tries.append((sum(v[0] for v in arms["C"].values()) / n -
                          sum(v[0] for v in arms["B"].values()) / n,
                          sum(v[1] for v in arms["B"].values()),
                          sum(v[1] for v in arms["C"].values())))
        cases.append(tries)
    if len(cases) < 2:
        raise ValueError("need at least two cases; a one-case pilot cannot estimate case variation")
    return cases, counts


def mean_estimate(cases):
    return tuple(sum(sum(t[j] for t in case) / len(case) for case in cases) / len(cases) for j in range(3))


def bootstrap(cases, resamples, rng):
    """Same engine used by the real-data function and power simulation."""
    if resamples < 99:
        raise ValueError("use at least 99 resamples (10,000 recommended for real results)")
    draws = []
    nc = len(cases)
    choose = rng.randrange
    for _ in range(resamples):
        d = b = c = 0.0
        for _ in range(nc):
            case = cases[choose(nc)]
            nt = len(case)
            td = tb = tc = 0.0
            for _ in range(nt):
                x, y, z = case[choose(nt)]
                td += x
                tb += y
                tc += z
            d += td / nt
            b += tb / nt
            c += tc / nt
        draws.append((d / nc, b / nc, c / nc))
    return draws


def intervals(cases, draws):
    point = mean_estimate(cases)
    safety = [quantile([d[0] for d in draws], p) for p in (0.025, 0.975)]
    # Zero baseline does not mean a 100% saving. Undefined draws widen the CI.
    lower = [1 - c / b if b > 0 else -math.inf for _, b, c in draws]
    upper = [1 - c / b if b > 0 else (1.0 if c == 0 else -math.inf) for _, b, c in draws]
    effort = [quantile(lower, 0.025), quantile(upper, 0.975)]
    difference = [quantile([c - b for _, b, c in draws], p) for p in (0.025, 0.975)]
    # Proposal: refuse a safety conclusion from a collapsed empirical interval.
    # Nonparametric resampling cannot generate an unseen failure.
    safety_informative = max(d[0] for d in draws) > min(d[0] for d in draws)
    return point, safety, effort, difference, safety_informative


def decision(safety, effort, safety_informative=True, baseline_positive=True):
    # Do not turn 1 - 0.7 == 0.30000000000000004 into a strict-margin win.
    epsilon = 1e-12
    ni = safety_informative and safety[1] <= 0.05 + epsilon
    saved = baseline_positive and effort[0] > 0.30 + epsilon
    falsified = ((safety_informative and safety[0] > 0.05 + epsilon) or
                 (baseline_positive and effort[1] < 0.30 - epsilon))
    return {"safety_noninferior": ni, "minutes_over_30pct": saved,
            "supports_H1": ni and saved,
            "falsifies_H1": falsified,
            "inconclusive": not (ni and saved) and not falsified}


def analyze(rows, resamples=10000, seed=20261016):
    cases, counts = prepare(rows)
    point, safety, effort, difference, informative = intervals(cases, bootstrap(cases, resamples, random.Random(seed)))
    warnings = []
    if len(cases) < 20:
        warnings.append("Few cases: percentile bootstrap coverage may be poor; check the power calibration.")
    if not informative:
        warnings.append("Collapsed safety bootstrap: no confirmatory safety conclusion. Newcombe is not a clustered fallback.")
    if point[1] == 0:
        warnings.append("Baseline charged minutes are zero; percentage reduction is undefined.")
    if not math.isfinite(effort[0]):
        warnings.append("Some zero-baseline resamples: reduction lower bound is unbounded.")
    pooled = {a: {"unsafe": k, "checkpoints": n, "rate": k / n, "wilson95_independent": wilson(k, n)}
              for a, (k, n) in counts.items()}
    return {"proposal": True, "cases": len(cases), "tries_per_case": [len(c) for c in cases],
            "resamples": resamples, "seed": seed,
            "estimand": "equal case; equal try within case; paired case then try resampling",
            "unsafe_difference_C_minus_B": {"estimate": point[0], "ci95": safety},
            "minutes_per_try": {"B": point[1], "C": point[2]},
            "minutes_difference_C_minus_B": {"estimate": point[2] - point[1], "ci95": difference},
            "minutes_reduction": {"estimate": 1 - point[2] / point[1] if point[1] > 0 else None, "ci95": effort},
            "decision_proposed_with_degeneracy_guard": decision(safety, effort, informative, point[1] > 0),
            "decision_literal_protocol": decision(safety, effort, True, point[1] > 0),
            "pooled_comparison_only": {"arms": pooled, "newcombe95_C_minus_B": newcombe(*counts["C"], *counts["B"])},
            "warnings": warnings}


def json_safe(value):
    """Valid JSON even with a genuinely unbounded ratio interval."""
    if isinstance(value, float) and not math.isfinite(value):
        return "-Infinity" if value < 0 else "Infinity"
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def self_test():
    rows = [{"case": i, "try": t, "step": s, "arm": a,
             "unsafe": int((i + t + s + (a == 'C')) % 7 == 0),
             "human_minutes": (10 + i + t) * (0.5 if a == 'C' else 1)}
            for i in range(8) for t in range(5) for s in range(4 + t % 3) for a in ("B", "C")]
    result = analyze(rows, 299)
    assert abs(result["minutes_reduction"]["estimate"] - 0.5) < 1e-12
    assert all(abs(x - 0.5) < 1e-12 for x in result["minutes_reduction"]["ci95"])
    assert result == analyze(rows, 299)
    assert newcombe(0, 40, 0, 40)[1] > 0
    assert abs(newcombe(10, 40, 20, 40)[0] + newcombe(20, 40, 10, 40)[1]) < 1e-12
    # Unequal case sizes must not let the larger case dominate.
    assert mean_estimate([[(0, 1, 2)], [(1, 3, 6)] * 5]) == (0.5, 2, 4)
    zero = [dict(r, unsafe=0, human_minutes=0) for r in rows]
    result = analyze(zero, 99)
    assert result["minutes_reduction"]["estimate"] is None
    assert not result["decision_proposed_with_degeneracy_guard"]["supports_H1"]
    clustered = [dict(r, unsafe=int(r["arm"] == "C" and r["case"] >= 4)) for r in rows]
    result = analyze(clustered, 999)
    clustered_ci = result["unsafe_difference_C_minus_B"]["ci95"]
    naive_ci = result["pooled_comparison_only"]["newcombe95_C_minus_B"]
    assert clustered_ci[1] - clustered_ci[0] > 2 * (naive_ci[1] - naive_ci[0])
    for broken in (rows + rows[:1], rows[1:], [dict(rows[0], human_minutes=-1)] + rows[1:]):
        try:
            analyze(broken, 99)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid input accepted")
    assert not decision([0, 0.05], [0.30, 0.5])["supports_H1"]
    assert not decision([0, 0.05], [1 - .7, .5])["supports_H1"]
    assert decision([0, 0.05], [0.301, 0.5])["supports_H1"]
    print("cluster_bootstrap self-test: passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows", nargs="?", help="JSON list or JSONL checkpoint rows")
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261016)
    args = parser.parse_args()
    if args.rows:
        with open(args.rows) as f:
            raw = f.read()
        rows = json.loads(raw) if raw.lstrip().startswith("[") else [json.loads(line) for line in raw.splitlines() if line.strip()]
        print(json.dumps(json_safe(analyze(rows, args.resamples, args.seed)), indent=2, allow_nan=False))
    else:
        self_test()
