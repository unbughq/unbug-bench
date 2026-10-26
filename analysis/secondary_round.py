"""Pre-registered SECONDARY checks. Never used by report_round's rule C.

NumPy/SciPy only. Bayesian analysis uses a joint Gaussian working likelihood on
paired try summaries, with case and try covariance. Mixed-model checks separately
use log1p minutes and a binomial logistic GLMM. The grouping is the same; the
Gaussian risk-summary approximation is explicitly not a Bayesian logistic GLMM.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp
from scipy.stats import invwishart

from cluster_bootstrap import wilson
from steadiness import generate_batch


PRIORS = {
    "sceptical": {"saving_mean": 0., "saving_sd": .35, "safety_mean": 0., "safety_sd": .10},
    "neutral_flat": {"saving_mean": 0., "saving_sd": 1.5, "safety_mean": 0., "safety_sd": .25},
    "optimistic": {"saving_mean": .5, "saving_sd": .35, "safety_mean": -.03, "safety_sd": .10},
}
SECONDARY_PLAN = {
    "chosen_before_scoring": True, "decision_use": "none; rule C alone decides",
    "bayesian_priors": PRIORS,
    "bayesian_likelihood": "Joint Gaussian paired try summaries (B minutes/100, C minutes/100, C-B unsafe fraction), case and try covariance; bounded population effects, not bounded Gaussian observations",
    "bayesian_covariance_prior": "Independent inverse-Wishart G,W: df=5, scale=diag(.25,.25,.01); prior mean component SD scales 50 minutes, 50 minutes, 10 safety points; heavy tails; same for every effect prior",
    "bayesian_baseline_prior": "log(B population mean minutes/100) Normal(0,2.5); saving <1; safety difference in [-1,1]",
    "bayesian_draws_per_chain": 2000, "bayesian_burn_in": 1000, "bayesian_chains": 2,
    "calibration_studies_per_scenario": 49, "calibration_draws_per_chain": 600,
    "calibration_burn_in": 400, "calibration_prior": "sceptical",
    "calibration_seed": 20261019,
    "calibration_generator": "steadiness.generate_batch: binary checkpoints and discrete charges, base unsafe .15, base minutes 30/checkpoint, level 0; same 24-case unequal-try design as fixture",
    "calibration_note": "Shorter chains for computational calibration; record diagnostics and threshold Monte Carlo ambiguity. Model-conditional error rate, not a universal frequentist guarantee.",
    "mixed_model_bootstrap": 199, "logistic_quadrature_nodes_per_dimension": 5,
    "mixed_sizing_agreement": "Both fits must converge without singularity or quadrature sensitivity; each model marginal and paired variance within 25% of reference (absolute tolerance 1e-5). Reference cross-outcome covariance retained and resulting covariance projected PSD only if relative change <=10%. Reference sizes remain primary; model feeds a power sensitivity at the reference candidate sizes.",
    "cuped_folds": 4, "seed": 20261017,
    "subgroups": [],
}


def raw_summaries(arrays):
    return [np.column_stack((x[..., 2].sum(axis=1), x[..., 0].mean(axis=1))) for x in arrays]


def covariance(values):
    within = np.array([np.cov(x, rowvar=False) for x in values])
    raw = np.cov([x.mean(axis=0) for x in values], rowvar=False) - np.mean(
        [v/len(x) for v, x in zip(within, values)], axis=0)
    e, v = np.linalg.eigh(raw)
    return (v*np.maximum(e, 1e-8))@v.T, within.mean(axis=0)+np.eye(values[0].shape[1])*1e-8


def chain_diagnostics(chains):
    """Split R-hat and initial-positive-sequence ESS for reported estimands."""
    m, n, d = chains.shape
    half = n//2
    split = np.concatenate((chains[:, :half], chains[:, -half:]), axis=0)
    w = split.var(axis=1, ddof=1).mean(axis=0)
    b = half*split.mean(axis=1).var(axis=0, ddof=1)
    rhat = np.sqrt(np.maximum(1., ((half-1)/half*w+b/half)/np.maximum(w, 1e-20)))
    ess = []
    for j in range(d):
        x = chains[:, :, j]-chains[:, :, j].mean(axis=1, keepdims=True)
        fft = np.fft.rfft(x, n=2*n, axis=1)
        ac = np.fft.irfft(fft*fft.conj(), axis=1)[:, :n].mean(axis=0)
        ac /= max(ac[0], 1e-20)
        total = 0.
        for k in range(1, n-1, 2):
            pair = ac[k]+ac[k+1]
            if pair < 0:
                break
            total += pair
        ess.append(float(min(m*n, m*n/max(1., 1+2*total))))
    return {"split_rhat": rhat.tolist(), "ess": ess,
            "constant_coordinates": np.flatnonzero(w <= 1e-14).tolist(),
            "adequate": bool(np.max(rhat) < 1.05 and min(ess) >= 100 and np.all(w > 1e-14))}


def bayes(values, prior, rng, draws=2000, burn=1000):
    """Metropolis-within-Gibbs, integrating case effects in the mean update.

    Mean vector is (mB/100, mC/100, risk difference); its induced prior has the
    Jacobian mB^-2 from (log mB, saving, delta). G and W are sampled, not plugged in.
    The three outcomes retain their cross-covariance, so joint P is not a product.
    """
    y = [np.column_stack((x[:, :2]/100, x[:, 3]-x[:, 2])) for x in values]
    ns = np.array([len(x) for x in y])
    means = np.array([x.mean(axis=0) for x in y])
    scatter = sum((x-x.mean(axis=0)).T@(x-x.mean(axis=0)) for x in y)
    n, total = len(y), int(ns.sum())
    scale = np.diag([.25, .25, .01])
    initial_g, initial_w = covariance(y)

    def log_prior(beta):
        b, c, delta = beta
        if b <= 0 or c <= 0 or not -1 < delta < 1:
            return -math.inf
        saving = 1-c/b
        return (-.5*(math.log(b)/2.5)**2 - 2*math.log(b)
                -.5*((saving-prior["saving_mean"])/prior["saving_sd"])**2
                -.5*((delta-prior["safety_mean"])/prior["safety_sd"])**2)

    chains, acceptances = [], []
    for chain in range(2):
        g, w = initial_g.copy(), initial_w.copy()
        beta = means.mean(axis=0)
        beta[:2] = np.maximum(beta[:2], .01)
        beta[2] = np.clip(beta[2], -.99, .99)
        samples, accepted = [], 0
        for iteration in range(burn+draws):
            inv_case = np.linalg.inv(g[None]+w[None]/ns[:, None, None])
            precision = inv_case.sum(axis=0)
            v = np.linalg.inv(precision)
            mean = v@np.einsum("nij,nj->i", inv_case, means)
            chol = np.linalg.cholesky(v)
            lp = log_prior(beta)
            # Independence proposal is the integrated Gaussian likelihood;
            # likelihood/proposal cancel, leaving exactly the prior ratio.
            for _ in range(3):
                proposal = mean+chol@rng.normal(size=3)
                proposed_lp = log_prior(proposal)
                if math.log(rng.random()) < proposed_lp-lp:
                    beta, lp = proposal, proposed_lp
                    accepted += 1
            gi, wi = np.linalg.inv(g), np.linalg.inv(w)
            post = np.linalg.inv(gi[None]+ns[:, None, None]*wi[None])
            rhs = ns[:, None]*(means-beta)@wi
            u = np.einsum("nij,nj->ni", post, rhs) + np.einsum(
                "nij,nj->ni", np.linalg.cholesky(post), rng.normal(size=(n, 3)))
            g = invwishart.rvs(df=5+n, scale=scale+u.T@u, random_state=rng)
            deviations = means-beta-u
            ss = scatter+np.einsum("n,ni,nj->ij", ns, deviations, deviations)
            w = invwishart.rvs(df=5+total, scale=scale+ss, random_state=rng)
            if iteration >= burn:
                samples.append([1-beta[1]/beta[0], beta[2]])
        chains.append(samples)
        acceptances.append(accepted/(3*(burn+draws)))
    chains = np.array(chains)
    samples = chains.reshape(-1, 2)
    events = np.column_stack((samples[:, 0] > .3, samples[:, 1] <= .05))
    joint = events.all(axis=1)
    diagnostics = chain_diagnostics(chains)
    diagnostics["adequate"] &= min(acceptances) > .01
    # Indicator ESS matters near a 0.95 posterior threshold.
    event_chains = np.column_stack((events, joint)).reshape(2, draws, 3).astype(float)
    indicator_diagnostics = chain_diagnostics(event_chains)
    probabilities = np.r_[events.mean(axis=0), joint.mean()]
    # Finite simulation never certifies P=0 or P=1 with exactly zero MC error.
    adjusted = (probabilities*samples.shape[0]+.5)/(samples.shape[0]+1)
    mcses = np.sqrt(adjusted*(1-adjusted)/np.maximum(1, indicator_diagnostics["ess"]))
    return {"probabilities": dict(zip(("saving_over_30pct", "safety_at_most_plus5pt", "both"), probabilities.tolist())),
            "threshold_095_mc_ambiguous": dict(zip(("saving_over_30pct", "safety_at_most_plus5pt", "both"),
                (np.abs(probabilities-.95) <= 2*mcses).tolist())),
            "credible95": {"saving": np.quantile(samples[:, 0], [.025, .975]).tolist(),
                           "safety_difference": np.quantile(samples[:, 1], [.025, .975]).tolist()},
            "posterior_mean": dict(zip(("saving", "safety_difference"), samples.mean(axis=0).tolist())),
            "posterior_probability_mcse": mcses.tolist(),
            "diagnostics": diagnostics, "indicator_diagnostics": indicator_diagnostics,
            "mean_update_acceptance": acceptances, "draws_per_chain": draws, "burn_in": burn,
            "warning": "Gaussian try-summary approximation; assumes exchangeable case effects independent of planned try count and may assign impossible observation values. "
                       "This is a joint hierarchical posterior with full covariance uncertainty; not a logistic Bayesian GLMM or a rule-C decision."}


def bayes_calibration(values, rng, studies=49, draws=600, burn=400):
    result = {"studies_per_scenario": studies, "prior": "sceptical", "draws_per_chain": draws,
              "burn_in": burn, "seed": 20261019, "generator": SECONDARY_PLAN["calibration_generator"],
              "scenarios": {}}
    for name, saving, delta in (("no_difference", 0., 0.), ("time_boundary", .3, 0.),
                                ("safety_boundary", .5, .05), ("both_boundaries", .3, .05)):
        count, ambiguous, poor = np.zeros(3, int), np.zeros(3, int), 0
        for study in range(studies):
            vals = []
            simulated = generate_batch(rng, 1, len(values), 3, .15, name, 0.)[0]
            for x, generated in zip(values, simulated):
                z = generated[:len(x)]
                # Bayes uses the unsafe contrast, so an equivalent (0,delta)
                # encoding avoids pretending we retained individual arm counts.
                vals.append(np.column_stack((z[:, 1:3], np.zeros(len(x)), z[:, 0])))
            posterior = bayes(vals, PRIORS["sceptical"], rng, draws, burn)
            p = np.array(list(posterior["probabilities"].values()))
            se = np.array(posterior["posterior_probability_mcse"])
            count += p > .95
            ambiguous += np.abs(p-.95) <= 2*se
            poor += not posterior["diagnostics"]["adequate"]
            if studies >= 49 and (study+1) % 10 == 0:
                print(f"Bayesian calibration: {name} {study+1}/{studies}", flush=True)
        false = (["saving", "both"] if name in ("no_difference", "time_boundary") else
                 ["safety", "both"] if name == "safety_boundary" else ["saving", "safety", "both"])
        result["scenarios"][name] = {"true_saving": saving, "true_safety_difference": delta,
            "false_or_boundary_claims": false,
            "posterior_over_095": {k: {"count": int(c), "rate": float(c/studies), "monte_carlo95": wilson(int(c), studies),
                "threshold_mc_ambiguous": int(a)} for k, c, a in zip(("saving", "safety", "both"), count, ambiguous)},
            "poor_chain_diagnostics": int(poor),
            "note": "No-difference safety non-inferiority is true, so its threshold crossing alone is not a false finding. "
                    "All studies, including poor diagnostics, remain in the denominator; this is algorithm calibration."}
    return result


def chol_cov(parameters):
    a, b, c = parameters
    l = np.array([[a, 0.], [b, c]])
    return l@l.T


def cov_start(matrix):
    l = np.linalg.cholesky(matrix+np.eye(2)*1e-5)
    return [l[0, 0], l[1, 0], l[1, 1]]


def fit_lmm(values):
    y = [np.log1p(x[:, :2]) for x in values]
    ns = np.array([len(x) for x in y])
    means = np.array([x.mean(axis=0) for x in y])
    scatter = sum((x-x.mean(axis=0)).T@(x-x.mean(axis=0)) for x in y)
    g0, w0 = covariance(y)

    def profile(theta, details=False):
        g, w = chol_cov(theta[:3]), chol_cov(theta[3:])+np.eye(2)*1e-9
        v = g[None]+w[None]/ns[:, None, None]
        vi = np.linalg.inv(v)
        a = vi.sum(axis=0)
        beta = np.linalg.solve(a, np.einsum("nij,nj->i", vi, means))
        residual = means-beta
        objective = ((ns-1).sum()*np.linalg.slogdet(w)[1]
                     +np.linalg.slogdet(w[None]+ns[:, None, None]*g[None])[1].sum()
                     +np.trace(np.linalg.solve(w, scatter))
                     +np.einsum("ni,nij,nj", residual, vi, residual)
                     +np.linalg.slogdet(a)[1])/2  # REML
        return (beta, g, w) if details else objective
    bounds = [(0, 10), (-10, 10), (0, 10)]*2
    opt = minimize(profile, cov_start(g0)+cov_start(w0), bounds=bounds, method="L-BFGS-B",
                   options={"maxiter": 300, "ftol": 1e-9})
    beta, g, w = profile(opt.x, True)
    result = fit_record(opt, beta, g, w, "Gaussian REML on log(1+charged minutes); try covariance is within-case residual covariance")
    result["upper_parameter_boundary"] = bool(np.max(np.abs(opt.x)) >= 9.99)
    result["boundary_or_singular"] |= result["upper_parameter_boundary"]
    return result


def fit_record(opt, beta, g, w, method):
    eig = np.r_[np.linalg.eigvalsh(g), np.linalg.eigvalsh(w)]
    boundary = bool(eig.min() <= 1e-6*max(1., eig.max()))
    return {"method": method, "converged": bool(opt.success), "optimizer_message": str(opt.message),
            "boundary_or_singular": boundary, "covariance_eigenvalues": eig.tolist(),
            "fixed_effect_B_C": beta.tolist(), "C_minus_B": float(beta[1]-beta[0]),
            "between_case_covariance": g.tolist(), "within_case_try_covariance": w.tolist(),
            "variance_components": {name: {"B": float(matrix[0, 0]), "C": float(matrix[1, 1]),
                "C_minus_B": float(matrix[0, 0]+matrix[1, 1]-2*matrix[0, 1])}
                for name, matrix in (("between_case", g), ("between_try_within_case", w))}}


def quadrature(q):
    nodes, weights = np.polynomial.hermite.hermgauss(q)
    mesh = np.array(np.meshgrid(nodes, nodes)).reshape(2, -1).T*math.sqrt(2)
    logweights = np.log(np.outer(weights, weights).ravel()/math.pi)
    return mesh, logweights


def fit_glmm(arrays, q=5):
    ns = np.array([len(x) for x in arrays])
    maxtries = int(ns.max())
    k = np.zeros((len(arrays), maxtries, 2))
    n = np.zeros_like(k)
    for i, x in enumerate(arrays):
        k[i, :len(x)] = x[..., 0].sum(axis=1)
        n[i, :len(x)] = x.shape[1]
    nodes, logweights = quadrature(q)

    def objective(theta):
        beta = theta[:2]
        cg = np.array([[theta[2], 0.], [theta[3], theta[4]]])
        cw = np.array([[theta[5], 0.], [theta[6], theta[7]]])
        logits = beta+(nodes@cg.T)[:, None, :]+(nodes@cw.T)[None, :, :]
        # Shape case x try x case-node x try-node x arm.
        ll = (k[:, :, None, None, :]*logits[None, None]
              -n[:, :, None, None, :]*np.logaddexp(0, logits)[None, None]).sum(axis=-1)
        per_try = logsumexp(ll+logweights[None, None, None, :], axis=-1)
        return -float(logsumexp(per_try.sum(axis=1)+logweights[None], axis=-1).sum())
    p = np.clip(k.sum(axis=(0, 1))/n.sum(axis=(0, 1)), .005, .995)
    initial = [*np.log(p/(1-p)), .3, 0., .3, .5, 0., .5]
    bounds = [(-12, 12)]*2+[(0, 4), (-4, 4), (0, 4)]*2
    opt = minimize(objective, initial, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 250, "ftol": 1e-8})
    beta, g, w = opt.x[:2], chol_cov(opt.x[2:5]), chol_cov(opt.x[5:8])
    result = fit_record(opt, beta, g, w, "Binomial logistic GLMM; paired bivariate case and try-within-case random effects; Gaussian-Hermite integration")
    result["quadrature_nodes_per_dimension"] = q
    result["coefficient_scale"] = "conditional C-B log odds, not a risk difference"
    result["upper_parameter_boundary"] = bool(np.max(np.abs(opt.x[2:])) >= 3.99)
    result["fixed_effect_boundary_or_separation"] = bool(np.max(np.abs(beta)) >= 11.99 or np.any((k.sum(axis=(0, 1)) == 0) | (k.sum(axis=(0, 1)) == n.sum(axis=(0, 1)))))
    result["boundary_or_singular"] |= result["fixed_effect_boundary_or_separation"]
    nodes1, weights1 = np.polynomial.hermite.hermgauss(31)
    marginal = (expit(beta[None]+nodes1[:, None]*np.sqrt(2*np.diag(g+w))[None])
                *weights1[:, None]/math.sqrt(math.pi)).sum(axis=0)
    result["marginal_unsafe_B_C"] = marginal.tolist()
    result["marginal_C_minus_B"] = float(marginal[1]-marginal[0])
    return result


def model_intervals(arrays, values, rng, bootstraps=199, q=5):
    lmm, glmm = fit_lmm(values), fit_glmm(arrays, q)
    replicates = {"log_minutes": [], "unsafe_glmm": []}
    failures = {"log_minutes": 0, "unsafe_glmm": 0}
    boundaries = dict(failures)
    for bootstrap_index in range(bootstraps):
        idx = rng.integers(len(arrays), size=len(arrays))
        for name, fitter, data in (("log_minutes", fit_lmm, [values[i] for i in idx]),
                                   ("unsafe_glmm", lambda x: fit_glmm(x, q), [arrays[i] for i in idx])):
            try:
                fit = fitter(data)
                boundaries[name] += fit["boundary_or_singular"]
                if not fit["converged"]:
                    failures[name] += 1
                    continue
                g, w = np.array(fit["between_case_covariance"]), np.array(fit["within_case_try_covariance"])
                replicates[name].append([fit["C_minus_B"], g[0, 0], g[1, 1], g[0, 0]+g[1, 1]-2*g[0, 1],
                                        w[0, 0], w[1, 1], w[0, 0]+w[1, 1]-2*w[0, 1],
                                        fit.get("marginal_C_minus_B", fit["C_minus_B"])])
            except (ValueError, np.linalg.LinAlgError, FloatingPointError):
                failures[name] += 1
        if bootstraps >= 99 and (bootstrap_index+1) % 25 == 0:
            print(f"Mixed-model bootstrap: {bootstrap_index+1}/{bootstraps}", flush=True)
    for name, fit in (("log_minutes", lmm), ("unsafe_glmm", glmm)):
        draws = np.array(replicates[name])
        fit.update(bootstrap_requested=bootstraps, bootstrap_successes=len(draws),
                   bootstrap_failed=failures[name], bootstrap_boundary_fits=boundaries[name],
                   interval_method="case-bootstrap refitting, no Wald intervals; conditional on successful fits")
        labels = ("C_minus_B", "case_variance_B", "case_variance_C", "case_variance_C_minus_B",
                  "try_variance_B", "try_variance_C", "try_variance_C_minus_B", "marginal_C_minus_B")
        fit["bootstrap_ci95"] = dict(zip(labels, np.quantile(draws, [.025, .975], axis=0).T.tolist())) if len(draws) >= .8*bootstraps and len(draws) >= 10 else None
        fit["intervals_reliable"] = bool(fit["converged"] and fit["bootstrap_ci95"] is not None and not fit["boundary_or_singular"])
    # Check integration at a finer resolution by a full fit, rather than silently
    # assuming low-order quadrature is accurate. Never use unstable GLMM for sizing.
    finer = fit_glmm(arrays, q+2)
    glmm["finer_quadrature_check"] = {"nodes": q+2, "converged": finer["converged"],
        "log_odds_difference": finer["C_minus_B"], "marginal_difference": finer["marginal_C_minus_B"],
        "sensitive": bool(abs(finer["C_minus_B"]-glmm["C_minus_B"]) > .2
                          or abs(finer["marginal_C_minus_B"]-glmm["marginal_C_minus_B"]) > .01)}
    nodes, lw = quadrature(q+2)
    def root(matrix):
        eig, vec = np.linalg.eigh(matrix)
        return vec*np.sqrt(np.maximum(eig, 0))
    gc, wc = np.array(glmm["between_case_covariance"]), np.array(glmm["within_case_try_covariance"])
    probabilities = expit(np.array(glmm["fixed_effect_B_C"])+(nodes@root(gc).T)[:, None]+(nodes@root(wc).T)[None])
    weights = np.exp(lw)
    case_means = np.einsum("t,cta->ca", weights, probabilities)
    overall = weights@case_means
    bg = np.einsum("c,ci,cj->ij", weights, case_means-overall, case_means-overall)
    residuals = probabilities-case_means[:, None]
    bw = np.einsum("c,t,cti,ctj->ij", weights, weights, residuals, residuals)
    inverse_steps = np.mean([1/x.shape[1] for x in arrays])
    bw += np.diag(np.einsum("c,t,cta->a", weights, weights, probabilities*(1-probabilities))*inverse_steps)
    # Separate outcome models do not identify cross-outcome random covariance.
    # Retain those reference covariances later; these are marginal sensitivity inputs.
    matrices = []
    for key, safety in (("between_case_covariance", bg), ("within_case_try_covariance", bw)):
        matrix = np.zeros((4, 4))
        matrix[:2, :2] = lmm[key]
        matrix[2:, 2:] = safety
        matrices.append(matrix.tolist())
    eligible = (lmm["intervals_reliable"] and glmm["intervals_reliable"] and not lmm["boundary_or_singular"]
                and not glmm["boundary_or_singular"] and not glmm["upper_parameter_boundary"]
                and finer["converged"] and not glmm["finer_quadrature_check"]["sensitive"])
    return {"log_minutes": lmm, "unsafe_glmm": glmm,
            "sizing_input": {"eligible": bool(eligible), "between_covariance": matrices[0],
                "within_covariance": matrices[1],
                "unsafe_conversion": "Marginal probability-scale case covariance plus try propensity covariance and binomial checkpoint noise. Assumes conditionally independent checkpoint Bernoullis; not latent logit variances plugged into a rate generator.",
                "cross_outcome_covariance": "Unidentified by separate models; use bootstrap reference cross-covariances when comparing a model sensitivity input."},
            "sizing_policy": "Bootstrap variance components remain the reference. Mixed-model components are an explicitly secondary sensitivity input, never an override."}


def cuped(arrays, design, rng, bootstraps=999):
    plan = design.get("covariate_plan", [])
    if not plan:
        return {"status": "not run: no pre-contestant covariates frozen; never substitute establishment or contestant outputs"}
    allowed = {"factory_difficulty", "scripted_strategy", "case_ingredients"}
    for p in plan:
        if p.get("source") not in allowed or p.get("fixed_before_contestants") is not True:
            raise ValueError("CUPED accepts only frozen factory difficulty, scripted strategy or case ingredient covariates")
    ids = [c["case"] for c in design["cases"]]
    names = [p["name"] for p in plan]
    if len(names) != len(set(names)) or len(names) > 3:
        raise ValueError("freeze at most three distinct covariates for 24 cases")
    x = np.array([[design["covariates"][case][name] for name in names] for case in ids], float)
    target = np.array([p["target_mean"] for p in plan], float)
    if not np.isfinite(x).all() or not np.isfinite(target).all():
        raise ValueError("CUPED covariates must be complete and finite; no outcome-based imputation")
    if not np.allclose(x.mean(axis=0), target, rtol=0, atol=1e-8):
        raise ValueError("frozen CUPED target means must equal the pre-contestant mean of this case set")
    scales = x.std(axis=0)
    if np.any(scales < 1e-10):
        return {"status": "not run: constant covariate; amend only before scoring"}
    x = (x-target)/scales
    y = np.array([v.mean(axis=0) for v in raw_summaries(arrays)])
    fold = np.array([int.from_bytes(hashlib.sha256(("cuped-20261017:"+case).encode()).digest()[:8], "big") % 4 for case in ids])

    def adjust(indices):
        xx, yy, ff = x[indices], y[indices], fold[indices]
        adjusted = yy.copy()
        for f in range(4):
            train, test = ff != f, ff == f
            if not test.any():
                continue
            a = np.column_stack((np.ones(train.sum()), xx[train]))
            if train.sum() <= len(names)+1 or np.linalg.matrix_rank(a) < len(names)+1:
                raise ValueError("rank-deficient CUPED training fold")
            coefficients = np.linalg.lstsq(a, yy[train], rcond=None)[0][1:]
            adjusted[test] -= xx[test]@coefficients
        return yy, adjusted

    raw, adjusted = adjust(np.arange(len(ids)))
    bs_raw, bs_adjusted, failed = [], [], 0
    for _ in range(bootstraps):
        try:
            r, a = adjust(rng.integers(len(ids), size=len(ids)))
        except ValueError:
            failed += 1
            continue
        bs_raw.append(r.mean(axis=0)); bs_adjusted.append(a.mean(axis=0))
    r, a = np.array(bs_raw), np.array(bs_adjusted)
    contrasts = {"minutes_difference_C_minus_B": np.array([-1, 1, 0, 0]),
                 "unsafe_difference_C_minus_B": np.array([0, 0, -1, 1])}
    result = {"status": "secondary only", "covariates": plan, "folds_by_case": dict(zip(ids, fold.tolist())),
              "method": "Four pre-fixed case folds; slopes trained without held-out cases; "
                  "case-bootstrap refits preserve fold membership for duplicate selections. "
                  "Inference conditions on the frozen case-set covariate mean, not an unknown population mean.",
              "bootstrap_failed": failed, "bootstrap_requested": bootstraps,
              "adjusted_mean_B_C_minutes": adjusted.mean(axis=0)[:2].tolist(), "effects": {}}
    for name, contrast in contrasts.items():
        before, after = r@contrast, a@contrast
        result["effects"][name] = {"unadjusted": float(raw.mean(axis=0)@contrast),
            "adjusted": float(adjusted.mean(axis=0)@contrast),
            "adjusted_ci95": np.quantile(after, [.025, .975]).tolist(),
            "variance_reduction": float(1-after.var(ddof=1)/before.var(ddof=1)) if before.var() > 0 else None}
    rb, ab = r[:, 0], a[:, 0]
    valid = (rb > 0) & (ab > 0)
    raw_saving, adjusted_saving = 1-r[valid, 1]/rb[valid], 1-a[valid, 1]/ab[valid]
    result["effects"]["saving"] = {"estimate": float(1-adjusted[:, 1].mean()/adjusted[:, 0].mean()) if adjusted[:, 0].mean() > 0 else None,
        "ci95_conditional_on_positive_baselines": np.quantile(adjusted_saving, [.025, .975]).tolist() if valid.any() else None,
        "nonpositive_baseline_bootstrap_samples": int((~valid).sum()),
        "variance_reduction": float(1-adjusted_saving.var(ddof=1)/raw_saving.var(ddof=1)) if valid.sum() > 1 and raw_saving.var() > 0 else None}
    return result


def validate_secondary_design(design, calibration_file=None):
    if design.get("secondary_plan") != SECONDARY_PLAN:
        raise ValueError("freeze the exact secondary_plan before scoring (see fixture/design.json)")
    covariates = design.get("covariate_plan", [])
    names = [p["name"] for p in covariates]
    if len(names) != len(set(names)) or len(names) > 3:
        raise ValueError("freeze at most three distinct covariates")
    for p in covariates:
        if p.get("source") not in {"factory_difficulty", "scripted_strategy", "case_ingredients"} or p.get("fixed_before_contestants") is not True:
            raise ValueError("CUPED rejects post-treatment or unfrozen covariates")
    if covariates:
        x = np.array([[design["covariates"][c["case"]][name] for name in names] for c in design["cases"]], float)
        targets = np.array([p["target_mean"] for p in covariates])
        if not np.isfinite(x).all() or not np.isfinite(targets).all() or not np.allclose(x.mean(axis=0), targets, rtol=0, atol=1e-8):
            raise ValueError("frozen covariates must be complete, finite and match pre-contestant case-set means")
    calibration = None
    if design.get("synthetic") is not True:
        if calibration_file is None:
            raise ValueError("real rounds require a pre-scoring synthetic Bayesian calibration report and its frozen sha256")
        path = Path(calibration_file)
        if hashlib.sha256(path.read_bytes()).hexdigest() != design.get("bayesian_calibration_sha256"):
            raise ValueError("frozen Bayesian calibration hash mismatch")
        frozen = json.loads(path.read_text())
        if not frozen.get("synthetic") or frozen["secondary"]["quick_validation_only"]:
            raise ValueError("Bayesian calibration must come from a full synthetic report")
        if frozen["secondary"]["plan"] != SECONDARY_PLAN:
            raise ValueError("Bayesian calibration used a different pre-registered secondary plan")
        calibration = frozen["secondary"]["bayesian"]["calibration"]
        if (calibration.get("studies_per_scenario") != 49 or calibration.get("seed") != 20261019
                or calibration.get("generator") != SECONDARY_PLAN["calibration_generator"]
                or set(calibration.get("scenarios", {})) != {"no_difference", "time_boundary", "safety_boundary", "both_boundaries"}):
            raise ValueError("frozen calibration is incomplete or used a different generator/seed")
    return calibration


def run_secondary(arrays, design, *, quick=False, calibration_file=None):
    calibration = validate_secondary_design(design, calibration_file)
    rng = np.random.default_rng(20261017)
    values = raw_summaries(arrays)
    sensitivity = {}
    for name, prior in PRIORS.items():
        sensitivity[name] = bayes(values, prior, rng, 300 if quick else 2000, 200 if quick else 1000)
        if not quick:
            print(f"Bayesian posterior: {name} complete", flush=True)
    models = model_intervals(arrays, values, rng, 19 if quick else 199, 3 if quick else 5)
    adjustment = cuped(arrays, design, rng, 199 if quick else 999)
    if design.get("synthetic") is True:
        calibration = bayes_calibration(values, np.random.default_rng(20261019), 5 if quick else 49, 200 if quick else 600, 150 if quick else 400)
    return {"secondary_only": True, "quick_validation_only": quick, "plan": SECONDARY_PLAN,
            "bayesian": {"primary_prior": "sceptical", "sensitivity": sensitivity,
                "calibration": calibration, "interpretation": "A posterior around 70% is weak evidence, not a finding. "
                    "Posterior probabilities never change rule C; priors and Gaussian working-likelihood assumptions matter."},
            "mixed_effects": models, "covariate_adjustment": adjustment,
            "no_subgroups_or_irt": True}


def markdown_secondary(secondary):
    lines = ["", "Secondary analyses do not change rule C. A posterior around **70% is weak evidence, not a finding**. "
        "The Bayesian calculation keeps the case/try hierarchy and cross-outcome covariance. It uses a "
        "Gaussian approximation to paired try summaries, while the separate mixed-model checks use "
        "log(1 + minutes) and a logistic model for unsafe checkpoints.", ""]
    lines += ["| Frozen prior | P(saving >30%) | P(safety ≤+5pt) | P(both) | Chains adequate |",
              "|---|---:|---:|---:|---|"]
    for name, row in secondary["bayesian"]["sensitivity"].items():
        p = row["probabilities"]
        lines.append(f"| {name.replace('_', '/')} | {100*p['saving_over_30pct']:.1f}% | "
            f"{100*p['safety_at_most_plus5pt']:.1f}% | {100*p['both']:.1f}% | "
            f"{row['diagnostics']['adequate']} |")
    lines += ["", "Sceptical prior: saving centred at 0, SD 35 percentage points; safety difference centred at 0, "
        "SD 10 points. Neutral/flat widths are 150 and 25 points. Optimistic centres are 50% saving and −3 safety "
        "points, with sceptical widths. Population saving is below 100% and safety difference within ±100 points. "
        "Common baseline/covariance priors, posterior intervals and Monte Carlo errors are in JSON.", ""]
    sceptical = secondary["bayesian"]["sensitivity"]["sceptical"]
    if abs(sceptical["probabilities"]["both"]-.95) <= 2*sceptical["posterior_probability_mcse"][2]:
        lines += ["The sceptical joint probability is within Monte Carlo uncertainty of 95%; do not treat the displayed rounding as a threshold finding.", ""]
    for name, model in (("Log-minute model", secondary["mixed_effects"]["log_minutes"]),
                         ("Unsafe logistic model", secondary["mixed_effects"]["unsafe_glmm"])):
        effect = (f"C−B log(1 + minutes) coefficient {model['C_minus_B']:.3f}" if name == "Log-minute model" else
                  f"marginal C−B safety difference {100*model['marginal_C_minus_B']:+.1f} points "
                  f"(conditional log-odds coefficient {model['C_minus_B']:.3f})")
        lines.append(f"- {name}: {effect}; converged={model['converged']}; "
            f"singular/boundary={model['boundary_or_singular']}. Case-bootstrap intervals and unsuccessful fits are recorded.")
    adjustment = secondary["covariate_adjustment"]
    lines += ["", "Covariate adjustment uses only the frozen factory/tester/strategy/ingredient covariates, "
        "never establishment or contestant outputs. Fixture variance reductions (negative means worse):", ""]
    for name, value in adjustment.get("effects", {}).items():
        reduction = value["variance_reduction"]
        lines.append(f"- {name}: " + (f"{100*reduction:.1f}%." if reduction is not None else "undefined."))
    if "effects" not in adjustment:
        lines.append(adjustment["status"])
    lines += ["", "Sceptical-prior synthetic P>0.95 calibration (saving / safety / joint threshold crossings; binomial intervals in JSON). "
        "At no difference, safety non-inferiority alone is true, so its crossings are not false claims:", ""]
    for name, row in secondary["bayesian"]["calibration"]["scenarios"].items():
        counts = row["posterior_over_095"]
        n = secondary["bayesian"]["calibration"]["studies_per_scenario"]
        study_word = "study" if row["poor_chain_diagnostics"] == 1 else "studies"
        lines.append(f"- {name}: saving {counts['saving']['count']}/{n}; safety {counts['safety']['count']}/{n}; "
                     f"joint {counts['both']['count']}/{n}; poor chain diagnostics in {row['poor_chain_diagnostics']} {study_word}.")
    zero_crossings = [row["posterior_over_095"]["both"] for row in secondary["bayesian"]["calibration"]["scenarios"].values()
                      if row["posterior_over_095"]["both"]["count"] == 0]
    if zero_crossings:
        lines += ["", f"Even zero joint crossings leaves a 95% Monte Carlo upper error bound of "
            f"{100*zero_crossings[0]['monte_carlo95'][1]:.1f}% here; this does not establish a controlled 5% error rate."]
    lines += ["", "These secondary checks are model-conditional. The JSON records numerical failures and posterior "
        "threshold ambiguity. Bootstrap variance remains the sizing reference if mixed models disagree. "
        "No unregistered subgroups or item response theory.", ""]
    return lines


def self_test(arrays, design):
    rng = np.random.default_rng(98)
    values = raw_summaries(arrays)
    lmm = fit_lmm(values)
    glmm = fit_glmm(arrays, 3)
    assert np.isfinite(lmm["C_minus_B"]) and np.isfinite(glmm["marginal_C_minus_B"])
    assert "boundary_or_singular" in lmm and "optimizer_message" in glmm
    p = bayes(values, PRIORS["sceptical"], rng, 200, 150)
    probabilities = p["probabilities"]
    assert 0 <= probabilities["both"] <= min(probabilities["saving_over_30pct"], probabilities["safety_at_most_plus5pt"])
    assert len(p["diagnostics"]["ess"]) == 2
    adjusted = cuped(arrays, design, rng, 99)
    assert set(adjusted["effects"]) == {"saving", "minutes_difference_C_minus_B", "unsafe_difference_C_minus_B"}
    bad = dict(design, covariate_plan=[dict(design["covariate_plan"][0], source="establishment")])
    try:
        cuped(arrays, bad, rng, 99)
    except ValueError:
        pass
    else:
        raise AssertionError("post-treatment covariate accepted")
    bad = dict(design, secondary_plan={})
    try:
        run_secondary(arrays, bad, quick=True)
    except ValueError:
        pass
    else:
        raise AssertionError("unregistered secondary analysis accepted")
    print("secondary_round self-test: PASS (hierarchical joint posterior, model diagnostics, CUPED provenance, frozen plan)")
