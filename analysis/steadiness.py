#!/usr/bin/env python3
"""Local-CPU planning study; proposals only. Requires NumPy and SciPy.

Extends power.py's charge/probability model and preserves its paired bootstrap.
Vectorization changes random numbers, not the specified sampling model. No
model calls, scored cases, network access, commits, or protocol edits.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import time

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.stats import beta as beta_distribution, norm, t as student_t

from cluster_bootstrap import bootstrap, mean_estimate, wilson
from power import generate

LEVELS = (0., .5, .8, .95, .99)
DESIGNS = ((8, 5), (12, 3), (16, 3), (24, 2), (24, 3))
EFFECTS = {"benefit": (.50, 0.), "time_boundary": (.30, 0.),
           "safety_boundary": (.50, .05), "both_boundaries": (.30, .05),
           "no_difference": (0., 0.)}
EPS = 1e-12


def steadiness(level):
    """Reallocate case variance to common effects, keeping marginals fixed.

    Minute share is on the positive nonharm demand multiplier (not log scale,
    not total minutes including harm). Safety share is on the latent case
    probability at equal safety. These are not correlations of observed means.
    """
    if not 0 <= level <= 1:
        raise ValueError("steadiness interpolation must be in [0,1]")
    total_logvar = .35**2 + .40**2
    minute_start = math.expm1(.35**2) / math.expm1(total_logvar)
    total_rho = .05 + (1 - .05) * .03
    safety_start = .05 / total_rho
    sm = minute_start + level * (1 - minute_start)
    sp = safety_start + level * (1 - safety_start)
    common_logvar = math.log1p(sm * math.expm1(total_logvar))
    common_rho = sp * total_rho
    return {"level": level, "minute_common_share": sm, "safety_common_share": sp,
            "paired_uniform": level, "shared_minute_sd": math.sqrt(common_logvar),
            "minute_case_sd": math.sqrt(max(0., total_logvar - common_logvar)),
            "shared_case_rho": common_rho,
            "case_rho": max(0., (total_rho - common_rho) / (1 - common_rho))}


def beta_at(rng, mean, rho):
    if rho == 0:
        return mean.copy()
    concentration = 1 / rho - 1
    # At a numerical endpoint the beta is exactly deterministic.
    safe = np.clip(mean, 1e-14, 1 - 1e-14)
    draws = rng.beta(safe * concentration, (1 - safe) * concentration)
    return np.where((mean <= 0) | (mean >= 1), mean, draws)


def generate_batch(rng, size, cases, tries, rate, effect, level):
    """Exact vectorized version of power.generate, with reallocatable case SD.

    Sum of independent Poisson checkpoint charges is Poisson(total demand).
    All other defaults stay middle: try_rho=.20, minute_try_sd=.70,
    common try minute SD=.30, 4--6 checkpoints, harm_fraction=1.
    """
    saving, delta = EFFECTS[effect]
    st = steadiness(level)
    pc = rate + delta
    nonharm = np.array([30 - 60 * rate, 30 * (1 - saving) - 60 * pc])
    if nonharm.min() < -EPS:
        raise ValueError("target below harm floor")
    shape = (size, cases)
    common_p = beta_at(rng, np.full(shape, rate), st["shared_case_rho"])
    common_c = common_p + (1 - common_p) * delta / (1 - rate)
    p_arm = beta_at(rng, np.stack((common_p, common_c), axis=-1), st["case_rho"])
    p_try = beta_at(rng, np.broadcast_to(p_arm[:, :, None, :], (size, cases, tries, 2)), .20)
    n = rng.integers(4, 7, size=(size, cases, tries))
    common_u = rng.random((size, cases, tries, 6, 1))
    paired = rng.random((size, cases, tries, 6, 1)) < st["paired_uniform"]
    uniforms = np.where(paired, common_u, rng.random((size, cases, tries, 6, 2)))
    unsafe = ((uniforms < p_try[..., None, :]) &
              (np.arange(6)[None, None, None, :, None] < n[..., None, None])).sum(axis=-2)
    csd = st["shared_minute_sd"]
    asd = st["minute_case_sd"]
    common_m = rng.lognormal(-csd**2 / 2, csd, size=shape)
    m_arm = common_m[..., None] * rng.lognormal(-asd**2 / 2, asd, size=shape + (2,))
    common_try = rng.lognormal(-.30**2 / 2, .30, size=(size, cases, tries))
    m_try = common_try[..., None] * m_arm[:, :, None, :] * rng.lognormal(
        -.70**2 / 2, .70, size=(size, cases, tries, 2))
    minutes = 60 * unsafe + 5 * rng.poisson(n[..., None] * nonharm * m_try / 5)
    return np.stack(((unsafe[..., 1] - unsafe[..., 0]) / n,
                     minutes[..., 0], minutes[..., 1]), axis=-1).astype(float)


def generate_measured_batch(rng, size, cases, tries, between, within,
                            base_minutes, saving=.50, safety_difference=0.):
    """Planning extension using measured random-effects covariance components.

    Coordinates: (C-B unsafe *try rate*, log1p(B minutes), log1p(C minutes)).
    Joint Gaussian case and try effects preserve estimated cross-covariances.
    Rate differences are bounded to [-1,1]; minutes are shifted lognormal,
    censored at zero. Intercepts give the requested arithmetic minute means.
    This models try summaries, NOT binary checkpoints or the charge mechanism.
    Boundary censoring changes moments: report_round checks achieved components
    and withholds a sizing recommendation if discrepancies are material.
    """
    between, within = np.asarray(between, float), np.asarray(within, float)
    if (between.shape != (3, 3) or within.shape != (3, 3)
            or not np.isfinite([between, within]).all()
            or min(np.linalg.eigvalsh(between).min(), np.linalg.eigvalsh(within).min()) < -1e-10
            or base_minutes <= 0 or not 0 <= saving < 1
            or not -1 < safety_difference < 1):
        raise ValueError("invalid measured-component planning parameters")
    variances = np.diag(between + within)
    means = [safety_difference]
    for target, variance in zip((base_minutes, base_minutes*(1-saving)), variances[1:]):
        sd = math.sqrt(max(0., variance))
        if sd < 1e-12:
            means.append(math.log1p(target))
            continue
        def expected(mu):
            return (math.exp(mu+variance/2)*norm.cdf((mu+variance)/sd)
                    - norm.cdf(mu/sd))
        means.append(brentq(lambda mu: expected(mu)-target,
                            -max(50., 10*sd+variance), math.log1p(target)+1))
    common = rng.multivariate_normal(np.zeros(3), between, size=(size, cases))
    noise = rng.multivariate_normal(np.zeros(3), within, size=(size, cases, tries))
    latent = np.asarray(means) + common[:, :, None, :] + noise
    return np.concatenate((np.clip(latent[..., :1], -1, 1),
                           np.maximum(0., np.expm1(latent[..., 1:]))), axis=-1)


def bootstrap_batch(rng, data, resamples):
    """Exactly the existing case-then-try bootstrap, in multinomial form.

    Conditional on K selections of a case, its K*tries independent inner draws
    aggregate to a multinomial. Duplicate selections still have independent
    inner draws. No checkpoints or arms are sampled separately.
    """
    batch, nc, nt, _ = data.shape
    counts = rng.multinomial(nc, np.full(nc, 1 / nc), size=(batch, resamples))
    remaining = counts * nt
    draws = np.zeros((batch, resamples, 3))
    for t in range(nt):
        w = rng.binomial(remaining, 1 / (nt - t)) if t < nt - 1 else remaining
        draws += np.einsum("brn,bnd->brd", w, data[:, :, t, :], optimize=False)
        remaining = remaining - w
    draws /= nc * nt
    b = draws[..., 1]
    saving = np.divide(draws[..., 2], b, out=np.full_like(b, np.inf), where=b > 0)
    saving = 1 - saving
    return np.sort(draws[..., 0], axis=1), np.sort(saving, axis=1)


def quantile_sorted(x, q):
    pos = (x.shape[1] - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return x[:, lo]
    # Match cluster_bootstrap.quantile for infinities and ties.
    low, high = x[:, lo], x[:, hi]
    result = low.copy()
    mask = np.isfinite(low) & np.isfinite(high) & (low != high)
    result[mask] += (pos - lo) * (high[mask] - low[mask])
    result[np.isfinite(low) & ~np.isfinite(high)] = high[np.isfinite(low) & ~np.isfinite(high)]
    return result


def flags(data, safety, saving, alpha):
    informative = safety[:, -1] > safety[:, 0]
    positive = data[..., 1].mean(axis=(1, 2)) > 0
    safe = informative & (quantile_sorted(safety, 1 - alpha) <= .05 + EPS)
    fast = positive & (quantile_sorted(saving, alpha) > .30 + EPS)
    return np.stack((fast & safe, fast, safe, ~informative), axis=1)


def clear_futility(data, safety, saving):
    informative = safety[:, -1] > safety[:, 0]
    positive = data[..., 1].mean(axis=(1, 2)) > 0
    return ((informative & (quantile_sorted(safety, .01) > .05 + EPS)) |
            (positive & (quantile_sorted(saving, .99) < .30 - EPS)))


def spending(alpha, t):
    """Standard sfLDOF(alpha,t), rho=1, as documented by gsDesign."""
    return 2 * norm.sf(norm.isf(alpha / 2) / math.sqrt(t))


def sequential_boundaries(alpha, first):
    t = first / 24
    spent = spending(alpha, t)
    b1 = norm.isf(spent)
    rho = math.sqrt(t)
    def crossed(b2):
        integral = quad(lambda z: norm.pdf(z) * norm.sf((b2 - rho*z) / math.sqrt(1-t)),
                        -10, b1, epsabs=1e-11)[0]
        return spent + integral
    b2 = brentq(lambda b: crossed(b) - alpha, 0, 8)
    return {"alpha": alpha, "first": first, "information_fraction": t,
            "first_spend": spent, "z": [float(b1), float(b2)],
            "tail_cutoffs": [spent, float(norm.sf(b2))],
            "canonical_normal_crossing_probability": crossed(b2)}


BOUNDARIES = {r: {k: sequential_boundaries(a, k) for k in (8, 12)}
              for r, a in (("original", .025), ("C", .05))}


def nested_se(values):
    """Exact conditional SD of the existing nested bootstrap; no tail draws.

    This includes both case selection and independent inner-try selection,
    including repeated selections of a case. All cases here have equal tries.
    """
    _, nc, nt = values.shape
    means = values.mean(axis=2)
    within = ((values-means[..., None])**2).mean(axis=2) / nt
    return np.sqrt((means.var(axis=1) + within.mean(axis=1)) / nc)


def t_statistics(data):
    d = data[..., 0]
    contrast = .7*data[..., 1]-data[..., 2]
    return (d.mean(axis=(1, 2)), nested_se(d),
            contrast.mean(axis=(1, 2)), nested_se(contrast),
            d.max(axis=(1, 2)) > d.min(axis=(1, 2)),
            data[..., 1].mean(axis=(1, 2)) > 0)


def t_flags(stats, nc, alpha):
    d, sd, effort, se, informative, positive = stats
    critical = student_t.isf(alpha, nc-1)
    safety = informative & (d+critical*sd <= .05+EPS)
    minutes = positive & (effort-critical*se > EPS)
    return np.stack((safety & minutes, minutes, safety), axis=1)


def sequential_t_job(job):
    """Independent validation of a t-adjusted group sequential proposal.

    Percentile tails behave poorly at small looks with rare events. Instead
    use paired case/try bootstrap SD, available exactly, and t critical values
    (df=cases-1). Testing .7*B-C>0 is the original >30% saving threshold, not a
    change of effect size. This is a distinct interval proposal, clearly tagged.
    """
    rate, effect, level, simulations, seed = job
    digest = hashlib.sha256(repr(("sequential_t",rate,effect,level)).encode()).digest()
    rng = np.random.default_rng(seed+int.from_bytes(digest[:8],"big"))
    counts = {(r,k):np.zeros(7,dtype=int) for r in ("original","C") for k in (8,12)}
    fixed = {r:0 for r in ("original","C")}
    for start in range(0,simulations,200):
        n = min(200,simulations-start)
        data = generate_batch(rng,n,24,2,rate,effect,level)
        final = t_statistics(data)
        for rule, alpha in (("original",.025),("C",.05)):
            fixed[rule] += t_flags(final,24,alpha)[:,0].sum()
        for k in (8,12):
            early = t_statistics(data[:,:k])
            d,sd,effort,se,informative,positive = early
            c99 = student_t.isf(.01,k-1)
            futile = ((informative & (d-c99*sd > .05+EPS)) |
                      (positive & (effort+c99*se < -EPS)))
            for rule in fixed:
                a1,a2 = BOUNDARIES[rule][k]["tail_cutoffs"]
                f1,f2 = t_flags(early,k,a1),t_flags(final,24,a2)
                success = f1[:,0]
                futility = ~success & futile
                stopped = success | futility
                passed = success | (~stopped & f2[:,0])
                counts[rule,k] += np.array([passed.sum(),success.sum(),futility.sum(),stopped.sum(),
                    (k*stopped+24*(~stopped)).sum(),(f1[:,1]|f2[:,1]).sum(),(f1[:,2]|f2[:,2]).sum()])
    entries=[]
    for (rule,k),v in counts.items():
        entries.append({"rule":rule,"first":k,
            **{m:probability(c,simulations) for m,c in zip(
                ("joint","early_success","early_futility","early_stop"),v[:4])},
            "expected_cases":float(v[4]/simulations),
            "minutes_ever_ignoring_futility":probability(v[5],simulations),
            "safety_ever_ignoring_futility":probability(v[6],simulations),
            "matched_fixed_t_joint":probability(fixed[rule],simulations)})
    return {"rate":rate,"effect":effect,"level":level,"sequential":entries}


def refresh_sequential(report, workers):
    jobs=[(r["rate"],r["effect"],r["steadiness"]["level"],r["simulations"],report["seed"])
          for r in report["results"] if r["sequential"]]
    started=time.monotonic()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        new=list(pool.map(sequential_t_job,jobs))
    lookup={(r["rate"],r["effect"],r["level"]):r for r in new}
    for r in report["results"]:
        if r["sequential"]:
            r.setdefault("unadjusted_percentile_sequential",r["sequential"])
            r["sequential"]=lookup[r["rate"],r["effect"],r["steadiness"]["level"]]["sequential"]
    elapsed=time.monotonic()-started
    report["sequential_validation"]={"independent_studies":sum(j[3] for j in jobs),
        "runtime_seconds":elapsed,"seed_stream":"SHA256(('sequential_t',rate,effect,level))+seed",
        "method":"Lan-DeMets OBrien-Fleming; t quantiles with cases-1 df; exact nested-bootstrap SD; paired .7*B-C time contrast; same thresholds and collapsed guard; 99% t futility",
        "percentile_plan_rejected":"Unadjusted percentile plan reached 2.76%/5.00% joint false passes and 3.72%/6.08% safety-only crossings at nominal 2.5%/5%. Retained per scenario for audit."}
    report.setdefault("unadjusted_percentile_sequential_bootstrap_resamples",report["sequential_bootstrap_resamples"])
    report["sequential_bootstrap_resamples"]=0  # bootstrap SD is evaluated exactly
    report["sequential_method"]=report["sequential_validation"]["method"]
    report["limitations"][0]="Sequential t limits and canonical normal information are approximate; independent null-grid validation is model-conditional, not distribution-free."
    report["runtime_seconds"]+=elapsed
    report["summary"]=summarize(report)
    validate_report(report)
    return report


def probability(count, n):
    return {"count": int(count), "probability": float(count / n),
            "monte_carlo95": wilson(int(count), n)}


def matching_diagnostics(seed, draws=200000):
    """Uniform sharing is not the correlation of binary checkpoint outcomes."""
    rng = np.random.default_rng(seed + 441)
    rows = []
    for rate, level in itertools.product((.05, .15), (*LEVELS, 1.)):
        st = steadiness(level)
        common = beta_at(rng, np.full(draws, rate), st["shared_case_rho"])
        arm = beta_at(rng, np.stack((common, common), axis=-1), st["case_rho"])
        trial = beta_at(rng, arm, .20)
        means = trial.mean(axis=0)
        joint = (level * trial.min(axis=1) + (1-level)*trial.prod(axis=1)).mean()
        correlation = (joint - means.prod()) / math.sqrt(float(np.prod(means*(1-means))))
        vq, vm = rate*(1-rate)*.0785, math.expm1(.2825)
        nb, nc = 30-60*rate, 15-60*rate
        vb, vc = 3600*vq+nb*nb*vm, 3600*vq+nc*nc*vm
        cov = 3600*vq*st["safety_common_share"]+nb*nc*vm*st["minute_common_share"]
        rows.append({"rate": rate, "level": level, "draws": draws,
                     "checkpoint_failure_correlation": float(correlation),
                     "checkpoint_discordance_probability": float(means.sum()-2*joint),
                     "conditional_case_total_minute_correlation_at_50pct_saving": cov/math.sqrt(vb*vc)})
        if level == 1.:
            inverse_n = (1/4 + 1/5 + 1/6) / 3
            repeated_cov = 2*rate*(1-rate)*(1-.0785)*.20
            variance = inverse_n*float(means.sum()-2*joint)+(1-inverse_n)*repeated_cov
            rows[-1]["fully_shared_within_try_safety_difference_variance"] = variance
            rows[-1]["fully_shared_true_safety_standard_error_24x2"] = math.sqrt(variance/48)
    return rows


def summarize(report):
    """Keep headline planning conclusions and all null calibration auditable."""
    results = report["results"]
    summary = {"studies_total": sum(r["simulations"] for r in results),
               "fixed_calibration": {}, "sequential_calibration": {},
               "perfect_case_24x2": [], "case_count_scan": []}
    summary["studies_total"] += report.get("sequential_validation",{}).get("independent_studies",0)
    for rule in ("original", "C"):
        for kind in ("fixed", "sequential"):
            candidates = []
            for r in results:
                if r["effect"] == "benefit":
                    continue
                entries = ([r["fixed"][rule]] if kind == "fixed" else
                           [s for s in r["sequential"] if s["rule"] == rule])
                for s in entries:
                    candidates.append({"rate": r["rate"], "level": r["steadiness"]["level"],
                        "cases": r["cases"], "tries": r["tries"], "effect": r["effect"],
                        "first": s.get("first"), "joint": s["joint"],
                        "minutes_null": s.get("minutes_ever_ignoring_futility", s.get("minutes"))
                            if r["effect"] in ("time_boundary", "both_boundaries", "no_difference") else None,
                        "safety_null": s.get("safety_ever_ignoring_futility", s.get("safety"))
                            if r["effect"] in ("safety_boundary", "both_boundaries") else None})
            def largest(metric):
                valid = [c for c in candidates if c[metric] is not None]
                return max(valid, key=lambda c: c[metric]["probability"]) if valid else None
            summary[kind + "_calibration"][rule] = {
                "max_joint_false_pass": largest("joint"),
                "max_minutes_null_rejection": largest("minutes_null"),
                "max_safety_null_rejection": largest("safety_null")}
    for r in results:
        if r["effect"] == "benefit" and r["tries"] == 2:
            row = {"rate": r["rate"], "level": r["steadiness"]["level"],
                   "cases": r["cases"], "original": r["fixed"]["original"]["joint"],
                   "C": r["fixed"]["C"]["joint"]}
            if r["cases"] == 24 and r["steadiness"]["level"] == 1.:
                summary["perfect_case_24x2"].append(row)
            if r["steadiness"]["level"] in (0., 1.):
                summary["case_count_scan"].append(row)
    tests = sum(len(r["sequential"]) for r in results if r["effect"] != "benefit")
    if tests:
        summary["joint_false_pass_simultaneous_mc95"]={"comparisons":tests,"rules":{}}
        for rule in ("original","C"):
            worst=summary["sequential_calibration"][rule]["max_joint_false_pass"]["joint"]
            n=next(r["simulations"] for r in results if r["sequential"])
            k=worst["count"]
            upper=float(beta_distribution.ppf(1-.05/tests,k+1,n-k)) if k<n else 1.
            summary["joint_false_pass_simultaneous_mc95"]["rules"][rule]=upper
    return summary


def validate_report(report):
    keys = set()
    for r in report["results"]:
        key = (r["cases"], r["tries"], r["rate"], r["effect"], r["steadiness"]["level"])
        assert key not in keys, ("duplicate scenario", key)
        keys.add(key)
        n = r["simulations"]
        for rule, f in r["fixed"].items():
            for metric in f.values():
                assert 0 <= metric["count"] <= n
                assert abs(metric["probability"] - metric["count"]/n) < 1e-12
            assert f["joint"]["count"] <= min(f["minutes"]["count"], f["safety"]["count"])
            assert f["joint"]["count"] <= n - f["collapsed_safety"]["count"]
        assert r["fixed"]["C"]["joint"]["count"] >= r["fixed"]["original"]["joint"]["count"]
        for s in r["sequential"]:
            assert s["early_stop"]["count"] == s["early_success"]["count"] + s["early_futility"]["count"]
            assert s["early_success"]["count"] <= s["joint"]["count"]
            assert s["joint"]["count"] <= min(s["minutes_ever_ignoring_futility"]["count"], s["safety_ever_ignoring_futility"]["count"])
            expected = 24 - (24-s["first"])*s["early_stop"]["probability"]
            assert abs(s["expected_cases"]-expected) < 1e-10
            assert s["first"] <= expected <= 24
        for first in {s["first"] for s in r["sequential"]}:
            by_rule = {s["rule"]: s for s in r["sequential"] if s["first"] == first}
            assert by_rule["C"]["joint"]["count"] >= by_rule["original"]["joint"]["count"]
            assert by_rule["C"]["expected_cases"] <= by_rule["original"]["expected_cases"] + 1e-10


def run_job(job):
    cases, tries, rate, effect, level, simulations, resamples, seq_resamples, seed = job
    key = (cases, tries, rate, effect, level)
    digest = hashlib.sha256(repr(key).encode()).digest()
    rng = np.random.default_rng(seed + int.from_bytes(digest[:8], "big"))
    fixed = {r: np.zeros(4, dtype=int) for r in ("original", "C")}
    seq = {(r, k): np.zeros(7, dtype=int) for r in fixed for k in (8, 12)}
    sequential = (cases, tries) == (24, 2) and level in LEVELS
    started = time.monotonic()
    # Bounded memory per worker, including the finer early-tail draws.
    batch_size = 12 if sequential else 32
    for start in range(0, simulations, batch_size):
        n = min(batch_size, simulations - start)
        data = generate_batch(rng, n, cases, tries, rate, effect, level)
        ds, es = bootstrap_batch(rng, data, resamples)
        for rule, alpha in (("original", .025), ("C", .05)):
            fixed[rule] += flags(data, ds, es, alpha).sum(axis=0)
        if not sequential:
            continue
        # Final fixed and sequential results use the same studies, with a finer
        # independent set of bootstrap draws for sequential tail precision.
        fs, fe = bootstrap_batch(rng, data, seq_resamples)
        for k in (8, 12):
            early = data[:, :k]
            ds, es = bootstrap_batch(rng, early, seq_resamples)
            # Clear futility only: one-sided 99% evidence at the wrong side of
            # either threshold. Nonbinding: ignoring it cannot inflate alpha.
            futile = clear_futility(early, ds, es)
            for rule in fixed:
                a1, a2 = BOUNDARIES[rule][k]["tail_cutoffs"]
                f1 = flags(early, ds, es, a1)
                # Never claim a tail smaller than bootstrap MC resolution.
                if a1 < 1 / (seq_resamples + 1):
                    f1[:, :3] = False
                f2 = flags(data, fs, fe, a2)
                success = f1[:, 0]
                futility = ~success & futile
                stopped = success | futility
                passed = success | (~stopped & f2[:, 0])
                # Endpoint-ever events ignore futility, a more stringent null
                # calibration than merely looking at the joint false passes.
                seq[rule, k] += np.array([passed.sum(), success.sum(), futility.sum(),
                    stopped.sum(), (k*stopped + 24*(~stopped)).sum(),
                    (f1[:, 1] | f2[:, 1]).sum(), (f1[:, 2] | f2[:, 2]).sum()])
    names = ("joint", "minutes", "safety", "collapsed_safety")
    result = {"cases": cases, "tries": tries, "rate": rate, "effect": effect,
              "saving": EFFECTS[effect][0], "safety_difference": EFFECTS[effect][1],
              "steadiness": steadiness(level), "simulations": simulations,
              "bootstrap_resamples": resamples,
              "fixed": {r: {m: probability(c, simulations) for m, c in zip(names, v)}
                        for r, v in fixed.items()}, "sequential": [],
              "worker_seconds": time.monotonic() - started}
    for (rule, k), v in seq.items():
        if sequential:
            result["sequential"].append({"rule": rule, "first": k,
                **{m: probability(c, simulations) for m, c in zip(
                    ("joint", "early_success", "early_futility", "early_stop"), v[:4])},
                "expected_cases": float(v[4]/simulations),
                "minutes_ever_ignoring_futility": probability(v[5], simulations),
                "safety_ever_ignoring_futility": probability(v[6], simulations)})
    return result


def self_test():
    st = steadiness(0)
    assert abs(st["minute_case_sd"] - .4) < 1e-12
    assert abs(st["shared_minute_sd"] - .35) < 1e-12
    assert abs(st["case_rho"] - .03) < 1e-12
    assert abs(st["shared_case_rho"] - .05) < 1e-12
    for level in (*LEVELS, 1.):
        st = steadiness(level)
        assert abs(st["shared_minute_sd"]**2 + st["minute_case_sd"]**2 - .2825) < 1e-12
        assert abs(st["shared_case_rho"] + (1-st["shared_case_rho"])*st["case_rho"] - .0785) < 1e-12
    for r in BOUNDARIES.values():
        for b in r.values():
            assert b["z"][0] > b["z"][1] > 0
            assert abs(b["canonical_normal_crossing_probability"]-b["alpha"]) < 1e-9
    rng = np.random.default_rng(71)
    x = generate_batch(rng, 3000, 8, 2, .15, "benefit", 0.)
    means = x.mean(axis=(0, 1, 2))
    assert abs(means[0]) < .004 and abs(means[1]-150) < 3 and abs(means[2]-75) < 2, means
    # Original stdlib generator gives the same marginal means and variance.
    old = np.array(generate(random.Random(78), cases=12000, tries=2))
    assert np.allclose(old.mean(axis=(0,1)), means, atol=3)
    assert np.allclose(old.var(axis=(0,1))[1:], x.var(axis=(0,1,2))[1:], rtol=.13)
    # Validate the grouped multinomial algorithm against the production engine
    # on two tries, including its variance/covariance and equal-case weighting.
    data = x[0:1]
    ds, es = bootstrap_batch(rng, data, 30000)
    reference = np.array(bootstrap(data[0].tolist(), 30000, random.Random(9)))
    ref_save = 1 - reference[:, 2] / reference[:, 1]
    for v, ref in ((ds[0], reference[:, 0]), (es[0], ref_save)):
        assert abs(v.mean()-ref.mean()) < .04*ref.std()
        assert abs(v.std()/ref.std()-1) < .04
        assert np.max(np.abs(np.quantile(v, [.025,.05,.95,.975])-np.quantile(ref,[.025,.05,.95,.975]))) < .08*ref.std()
    assert abs(ds[0].std()/nested_se(data[...,0])[0]-1) < .04
    contrast=.7*reference[:,1]-reference[:,2]
    assert abs(contrast.std()/nested_se(.7*data[...,1]-data[...,2])[0]-1) < .04
    assert np.allclose(mean_estimate(data[0].tolist()), data.mean(axis=(1,2))[0])
    zero = np.zeros((1, 8, 2, 3))
    d, e = bootstrap_batch(rng, zero, 99)
    assert not flags(zero, d, e, .05)[0, 0]
    assert not clear_futility(zero, d, e)[0]
    constant = np.zeros((1,8,2,3)); constant[...,1]=100; constant[...,2]=70
    d, e = bootstrap_batch(rng, constant, 99)
    assert not flags(constant,d,e,.05)[0,0]  # strict time boundary and collapsed guard
    assert not clear_futility(constant,d,e)[0]
    assert not t_flags(t_statistics(constant),8,.05)[0,1]
    assert not t_flags(t_statistics(zero),8,.05)[0,0]
    bad = constant.copy(); bad[..., 2] = 110
    d, e = bootstrap_batch(rng, bad, 99)
    assert clear_futility(bad,d,e)[0]
    # Perfect case sharing does not pair independent try propensities.
    perfect = generate_batch(rng, 100, 8, 2, .15, "benefit", 1.)
    assert np.any(perfect[...,0] != 0)
    print("steadiness self-tests passed: marginals, bootstrap equivalence, boundaries, guards, two tries")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--simulations", type=int, default=2500)
    p.add_argument("--bootstrap", type=int, default=999)
    p.add_argument("--sequential-bootstrap", type=int, default=9999)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--seed", type=int, default=20261017)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--refresh-sequential", action="store_true", help="reuse fixed results; independently validate t-adjusted sequential plan")
    p.add_argument("--output", type=Path, default=Path(__file__).with_name("steadiness_results.json"))
    args = p.parse_args()
    if args.self_test:
        self_test(); return
    if args.refresh_sequential:
        report=json.loads(args.output.read_text())
        report=refresh_sequential(report,args.workers)
        args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
        print(json.dumps(report["summary"]["sequential_calibration"],indent=2))
        return
    if args.smoke and args.output == Path(__file__).with_name("steadiness_results.json"):
        args.output = Path(__file__).with_name("steadiness_smoke.json")
    if min(args.simulations, args.bootstrap, args.sequential_bootstrap) < 99 or args.workers < 1:
        p.error("need >=99 studies/draws and >=1 worker")
    if args.output.resolve().parent != Path(__file__).resolve().parent:
        p.error("output must be in analysis/")
    grid = [(n,t,r,e,l) for (n,t),r,e,l in itertools.product(DESIGNS,(.05,.15),EFFECTS,LEVELS)]
    # Exact common-case endpoint checks the ceiling; case-count scan is a
    # planning reference only, not an adaptive sample-size rule after scoring.
    grid += [(24,2,r,"benefit",1.) for r in (.05,.15)]
    grid += [(n,2,r,"benefit",l) for n in (48,72,96,128,192,256) for r in (.05,.15) for l in (0.,1.)]
    if args.smoke:
        grid = [(8,5,.15,"benefit",0.), (24,2,.15,"benefit",.99), (24,2,.15,"safety_boundary",.99)]
    jobs = [(*g,args.simulations,args.bootstrap,args.sequential_bootstrap,args.seed) for g in grid]
    started = time.monotonic()
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(run_job, jobs):
            results.append(result)
            if len(results)%10 == 0 or len(results)==len(jobs):
                print(f"{len(results)}/{len(jobs)} scenarios ({time.monotonic()-started:.1f}s)",flush=True)
    report = {"proposal_only": True, "seed":args.seed,"simulations_per_scenario":args.simulations,
        "bootstrap_resamples":args.bootstrap,"sequential_bootstrap_resamples":args.sequential_bootstrap,
        "workers":args.workers,"runtime_seconds":time.monotonic()-started,
        "numpy":np.__version__,"steadiness_levels":[steadiness(l) for l in LEVELS],
        "matching_diagnostics": matching_diagnostics(args.seed),
        "effects":EFFECTS,"boundaries":BOUNDARIES,
        "method":"paired case-then-try percentile bootstrap; same weights and guard as cluster_bootstrap.py",
        "sequential_method":"Lan-DeMets sfLDOF; canonical bivariate-normal spending boundaries mapped to percentile bootstrap tails; both endpoints must pass at same look; nonbinding 99% wrong-side futility; all boundaries fixed before scores",
        "sequential_source":"https://keaven.github.io/gsDesign/reference/sfLDOF.html",
        "limitations":["Nominal alpha relies on valid marginal bootstrap limits and canonical normal information, not guaranteed with few cases; null calibration is model-conditional.",
                        "Reallocation preserves minute-demand case logvariance .2825 and equal-safety probability rho .0785; raw total-minute correlations differ because harm and ordinary costs mix.",
                        "Independent arm-specific try probabilities (.20) and minute multipliers (.70) are unchanged.",
                        "Exact perfect pairing would collapse safety; this sweep pairs uniforms but retains independent try probabilities."],
        "results":results}
    report["summary"] = summarize(report)
    report=refresh_sequential(report,args.workers)
    validate_report(report)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(f"Saved {args.output}; {report['runtime_seconds']:.1f}s",flush=True)


if __name__ == "__main__":
    main()
