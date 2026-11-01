"""Step 4. Questions 1 to 5: observed zero sections, expected zeros under the
models, baselines 2022 and 2018, round-1 persistence, and scale.

Aggregate tables go to results/. Lists of individual sections go to the private
data folder, because they identify small communities.

The model for a section. A section has n valid votes for the two runoff
candidates. Candidate X's count is modelled as Binomial(n, p) (the "B" models) or
Beta-binomial(n, a, b) (the "BB" and "EB" models), where p, or the Beta mean
a / (a + b), comes from other votes: the rest of the municipality ("mun"), the
other sections at the same polling place ("place"), or the same section's round 1
("r1"). q_i is the model probability that X gets 0 votes in section i. The
expected number of zero sections is the sum of q_i. Sections are treated as
independent, which is an assumption, not a fact (see FINDINGS-v2.md, Limits).

v2 changes, each listed and dated in EXPERIMENT.md under "v2 deviations":
  - BB-place uses the municipality dispersion where it falls back to the
    municipality mean, and fits the place dispersion only on sections that have
    place-mates. The v1 implementation is kept as "BB-place (v1 code)".
  - Exact Poisson-binomial tails replace the normal approximation.
    The normal bound is still written, for comparison.
  - Two models added after results, both beta-binomial posterior predictives
    with the municipality prior (mean = municipality leave-one-out share,
    concentration = the state's BB-mun phi). They never give a probability of 1.
      EB-place: updated with the votes of the other sections at the same place.
      EB-r1:    updated with the same section's round-1 votes for the two
                runoff candidates. It does not use any round-2 outcome.
  - Per-section expectation is decomposed (M1), calibration by bins of q,
    proper scores across all sections (log score and Brier), U2 per side (M2),
    and a bootstrap over polling places for the observed/expected ratio.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DERIVED, KEY, MUN, PLACE, SEED, SIDES, YEARS, cand_name,  # noqa: E402
                    write_csv)

EVENTS = ("zero", "share_lt_1pct", "votes_le_2")
MINS = (1, 10, 50)
Z999 = stats.norm.ppf(0.999)
CLIP = 1e-4
QFLOOR = 1e-15  # floor for log scores

# name, tag, status. Status says how each model relates to EXPERIMENT.md.
MODELS = [
    ("B-mun", "bmun", "pre-registered"),
    ("B-place", "bplace", "pre-registered"),
    ("BB-mun", "bbmun", "pre-registered"),
    ("BB-place", "bbplace", "pre-registered, fallback dispersion fixed in v2"),
    ("BB-place (v1 code)", "bbplacev1", "v1 implementation, kept for comparison"),
    ("EB-place", "ebplace", "added after results (v2)"),
    ("EB-r1", "ebr1", "added after results (v2)"),
]
PREREG = ["B-mun", "B-place", "BB-mun", "BB-place"]


def loo_share(s, group, col):
    """Share of `col` in the rest of the group, leaving the section out."""
    g = s.groupby(group)[[col, "n"]].transform("sum")
    num, den = g[col] - s[col], g["n"] - s["n"]
    return np.where(den > 0, num / den.where(den > 0, 1), np.nan), num.to_numpy(), den.to_numpy()


def with_shares(s, r1):
    s = s.copy()
    st, _, _ = loo_share(s, ["SG_UF"], "votes_pt")
    mun, _, _ = loo_share(s, MUN, "votes_pt")
    s["p_pt_mun"] = np.where(np.isnan(mun), st, mun)
    place, xr, nr = loo_share(s, PLACE, "votes_pt")
    s["p_pt_place"] = np.where(np.isnan(place), s.p_pt_mun, place)
    s["place_fallback"] = np.isnan(place)
    s["place_rest_pt"], s["place_rest_n"] = xr, nr
    s["place_sections"] = s.groupby(PLACE).NR_SECAO.transform("size")
    s = s.merge(r1, on=KEY, how="left")
    s["r1_missing"] = s.r1_n2.isna() | (s.r1_n2.fillna(0) == 0)
    return s


def kmax_share(n, thr=0.01):
    """Largest k with k/n < thr."""
    return np.ceil(thr * n).astype(int) - 1


def bb_loglik(log_phi, k, n, mu):
    phi = np.exp(log_phi)
    a, b = mu * phi, (1 - mu) * phi
    return (special.gammaln(n + 1) - special.gammaln(k + 1) - special.gammaln(n - k + 1)
            + special.betaln(k + a, n - k + b) - special.betaln(a, b)).sum()


def fit_phi(k, n, mu):
    res = optimize.minimize_scalar(lambda lp: -bb_loglik(lp, k, n, mu),
                                   bounds=(np.log(0.05), np.log(1e6)), method="bounded")
    return float(np.exp(res.x))


def probs_binom(n, p):
    return (np.power(1 - p, n), stats.binom.cdf(kmax_share(n), n, p), stats.binom.cdf(2, n, p))


def probs_bb(n, a, b):
    """P(zero), P(share < 1%), P(votes <= 2) for a candidate with Beta(a, b) share."""
    q0 = np.exp(special.betaln(a, b + n) - special.betaln(a, b))
    return q0, stats.betabinom.cdf(kmax_share(n), n, a, b), stats.betabinom.cdf(2, n, a, b)


def poisson_binomial(q, obs, e, sd):
    """Exact distribution of a sum of independent Bernoulli(q_i), truncated at K.

    Returns (99.9% quantile, P(X >= obs)). Mass above K is kept in bin K, and K is
    set above both obs and E + 10 sd, so both answers are exact.
    """
    q = q[q > 1e-14]
    K = int(max(obs + 1, np.ceil(e + 10 * sd + 20)))
    pmf = np.zeros(K + 1)
    pmf[0] = 1.0
    m = 64
    pad = (-len(q)) % m
    qq = np.concatenate([q, np.zeros(pad)]).reshape(-1, m)
    poly = np.zeros((qq.shape[0], m + 1))
    poly[:, 0] = 1.0
    for j in range(m):  # one DP step across all chunks at once
        qj = qq[:, j:j + 1]
        poly[:, 1:] = poly[:, 1:] * (1 - qj) + poly[:, :-1] * qj
        poly[:, :1] *= (1 - qj)
    for c in poly:
        new = np.convolve(pmf, c)
        tail = new[K:].sum()
        pmf = new[:K + 1]
        pmf[K] = tail
    cdf = np.cumsum(pmf)
    q999 = int(np.searchsorted(cdf, 0.999 - 1e-12))
    p_ge = float(min(1.0, pmf[obs:].sum()))  # summed directly, so tiny tails keep precision
    return q999, p_ge


def observed(s, side):
    x, n = s[f"votes_{side}"], s.n
    return {"zero": (x == 0) & (n >= 1), "share_lt_1pct": (x < 0.01 * n) & (n >= 1),
            "votes_le_2": (x <= 2) & (n >= 1)}


def model_year(year):
    s = pd.read_parquet(DERIVED / f"sections_{year}_r2.parquet")
    r1 = pd.read_parquet(DERIVED / f"sections_{year}_r1.parquet",
                         columns=KEY + ["votes_pt", "votes_opp", "QT_VOTOS_NOMINAIS"])
    r1 = r1.rename(columns={"votes_pt": "r1_pt", "votes_opp": "r1_opp",
                            "QT_VOTOS_NOMINAIS": "r1_nominal"})
    r1["r1_n2"] = r1.r1_pt + r1.r1_opp
    s = with_shares(s, r1)
    v = s[s.n >= 1].copy()
    phis = []
    mu_mun_all = np.clip(v.p_pt_mun.to_numpy(), CLIP, 1 - CLIP)
    v["phi_mun"], v["phi_place"] = np.nan, np.nan
    for uf, idx in v.groupby("SG_UF").groups.items():
        g = v.loc[idx]
        mu = np.clip(g.p_pt_mun.to_numpy(), CLIP, 1 - CLIP)
        phi = fit_phi(g.votes_pt.to_numpy(), g.n.to_numpy(), mu)
        v.loc[idx, "phi_mun"] = phi
        phis.append({"year": year, "mean": "mun", "SG_UF": uf, "phi": phi, "sections": len(g)})
        # v2: the place dispersion is fitted on sections that have place-mates only.
        gp = g[~g.place_fallback]
        if len(gp):
            phi_p = fit_phi(gp.votes_pt.to_numpy(), gp.n.to_numpy(),
                            np.clip(gp.p_pt_place.to_numpy(), CLIP, 1 - CLIP))
        else:
            phi_p = phi
        v.loc[idx, "phi_place"] = phi_p
        # v1 fitted the place dispersion on all sections, fallback included.
        phi_v1 = fit_phi(g.votes_pt.to_numpy(), g.n.to_numpy(),
                         np.clip(g.p_pt_place.to_numpy(), CLIP, 1 - CLIP))
        v.loc[idx, "phi_place_v1"] = phi_v1
        phis.append({"year": year, "mean": "place (sections with place-mates)", "SG_UF": uf,
                     "phi": phi_p, "sections": len(gp)})
        phis.append({"year": year, "mean": "place, v1 fit (all sections)", "SG_UF": uf,
                     "phi": phi_v1, "sections": len(g)})

    n = v.n.to_numpy()
    p_mun = v.p_pt_mun.to_numpy()
    p_place = v.p_pt_place.to_numpy()
    fb = v.place_fallback.to_numpy()
    phi_mun = v.phi_mun.to_numpy()
    phi_place = np.where(fb, phi_mun, v.phi_place.to_numpy())
    mu_mun = mu_mun_all
    mu_place = np.clip(p_place, CLIP, 1 - CLIP)
    # Beta parameters of the PT candidate's share under each beta model.
    a0, b0 = mu_mun * phi_mun, (1 - mu_mun) * phi_mun
    xr = np.where(fb, 0, v.place_rest_pt.to_numpy())
    nr = np.where(fb, 0, v.place_rest_n.to_numpy())
    r1x = np.where(v.r1_missing, 0, v.r1_pt.fillna(0).to_numpy())
    r1n = np.where(v.r1_missing, 0, v.r1_n2.fillna(0).to_numpy())
    beta_pt = {
        "bbmun": (a0, b0),
        "bbplace": (mu_place * phi_place, (1 - mu_place) * phi_place),
        "bbplacev1": (mu_place * v.phi_place_v1.to_numpy(), (1 - mu_place) * v.phi_place_v1.to_numpy()),
        "ebplace": (a0 + xr, b0 + nr - xr),
        "ebr1": (a0 + r1x, b0 + r1n - r1x),
    }

    rows, scores, calib, decomp = [], [], [], []
    for side in SIDES:
        obs = observed(v, side)
        y0 = obs["zero"].to_numpy()
        x_rest_side = xr if side == "pt" else nr - xr
        placemates_zero = (~fb) & (x_rest_side == 0)
        v[f"placemates_zero_{side}"] = placemates_zero
        for model, tag, status in MODELS:
            if tag in ("bmun", "bplace"):
                p = p_mun if tag == "bmun" else p_place
                q = probs_binom(n, p if side == "pt" else 1 - p)
            else:
                a, b = beta_pt[tag]
                q = probs_bb(n, a, b) if side == "pt" else probs_bb(n, b, a)
            q = dict(zip(EVENTS, q))
            v[f"q0_{tag}_{side}"] = q["zero"]
            v[f"qle2_{tag}_{side}"] = q["votes_le_2"]
            for ev in EVENTS:
                for minn in MINS:
                    m = n >= minn
                    qm = q[ev][m]
                    e = qm.sum()
                    sd = np.sqrt((qm * (1 - qm)).sum())
                    o = int(obs[ev].to_numpy()[m].sum())
                    q999, p_ge = poisson_binomial(qm, o, e, sd)
                    rows.append({"year": year, "side": side, "candidate": cand_name(year, side),
                                 "event": ev, "min_valid_votes": minn, "model": model,
                                 "model_status": status, "observed": o, "expected": e, "sd": sd,
                                 "upper_99_9_normal": e + Z999 * sd,
                                 "u1_fires_normal": o > e + Z999 * sd,
                                 "upper_99_9_exact": q999, "p_exact_ge_observed": p_ge,
                                 "u1_fires_exact": o > q999,
                                 "obs_over_exp": o / e if e > 0 else np.nan})
            # Section-level checks, zero event, all sections with n >= 1.
            q0 = q["zero"]
            qc = np.clip(q0, QFLOOR, 1 - QFLOOR)
            scores.append({"year": year, "side": side, "model": model, "model_status": status,
                           "sections": len(q0), "observed_zeros": int(y0.sum()),
                           "expected_zeros": q0.sum(),
                           "log_score": float(np.sum(np.where(y0, np.log(qc), np.log1p(-qc)))),
                           "brier_sum": float(np.sum((q0 - y0) ** 2)),
                           "sections_q_eq_1": int((q0 >= 1 - 1e-12).sum()),
                           "nonzero_sections_q_eq_1": int(((q0 >= 1 - 1e-12) & ~y0).sum()),
                           "zero_sections_q_below_1e-6": int(((q0 < 1e-6) & y0).sum())})
            bins = [0, 1e-9, 1e-6, 1e-4, 1e-3, 1e-2, 0.05, 0.2, 0.5, 1.0000001]
            lab = pd.cut(q0, bins, right=False, labels=[f"[{bins[i]:g}, {min(bins[i+1], 1):g})"
                                                       for i in range(len(bins) - 1)])
            dec = pd.qcut(pd.Series(q0).rank(method="first"), 10, labels=[f"decile {i}" for i in range(1, 11)])
            for scheme, grp in (("q bin", lab), ("rank decile of q", dec)):
                t = pd.DataFrame({"g": np.asarray(grp), "q": q0, "y": y0}).groupby("g", observed=True)
                for gname, gg in t:
                    calib.append({"year": year, "side": side, "model": model, "scheme": scheme,
                                  "bin": gname, "sections": len(gg), "expected": gg.q.sum(),
                                  "observed": int(gg.y.sum()), "q_min": gg.q.min(), "q_max": gg.q.max()})
            groups = {
                "all sections": np.ones_like(y0, dtype=bool),
                "observed zero sections": y0,
                "sections that were not zero": ~y0,
                "sections alone at their place (fallback)": fb,
                "zero sections alone at their place": y0 & fb,
                "sections whose place-mates gave the candidate 0 votes": placemates_zero,
                "of those, sections that were zero themselves": placemates_zero & y0,
                "of those, sections that were not zero": placemates_zero & ~y0,
                "zero sections with place-mates, place-mates not all zero": y0 & ~fb & ~placemates_zero,
            }
            for gname, mask in groups.items():
                decomp.append({"year": year, "side": side, "model": model, "group": gname,
                               "sections": int(mask.sum()), "observed_zeros": int(y0[mask].sum()),
                               "expected_zeros": float(q0[mask].sum()),
                               "share_of_model_total": float(q0[mask].sum() / q0.sum()) if q0.sum() else np.nan,
                               "median_q": float(np.median(q0[mask])) if mask.any() else np.nan})

    keep = [c for c in v.columns if c.startswith(("q0_", "qle2_", "phi_", "placemates_zero_"))]
    s = s.merge(v[KEY + keep], on=KEY, how="left")
    return (s, pd.DataFrame(rows), pd.DataFrame(phis), pd.DataFrame(scores),
            pd.DataFrame(calib), pd.DataFrame(decomp))


def u2_check(oe):
    """U2 as pre-registered: pooled baseline of four ratios (2018, 2022, both sides).

    Pre-registered models only (72 checks = 3 events x 3 sizes x 4 models x 2 sides).
    The per-side columns are added after results (v2): the side's own 2018 and 2022.
    """
    out = []
    oe = oe[oe.model.isin(PREREG)]
    for (event, minn, model), g in oe.groupby(["event", "min_valid_votes", "model"]):
        base = g[g.year != 2026].obs_over_exp
        lo, hi = base.min(), base.max()
        for side in SIDES:
            cur = g[(g.year == 2026) & (g.side == side)].iloc[0]
            own = g[(g.year != 2026) & (g.side == side)].obs_over_exp
            r = cur.obs_over_exp
            out.append({"event": event, "min_valid_votes": minn, "model": model, "side": side,
                        "observed_2026": cur.observed, "expected_2026": cur.expected,
                        "ratio_2026": r, "baseline_min_pooled": lo, "baseline_max_pooled": hi,
                        "u2_fires_pooled": bool(r > 1.5 * hi or r < lo / 1.5),
                        "own_side_ratio_2022": g[(g.year == 2022) & (g.side == side)].obs_over_exp.iloc[0],
                        "own_side_ratio_2018": g[(g.year == 2018) & (g.side == side)].obs_over_exp.iloc[0],
                        "ratio_2026_over_own_side_max": r / own.max(),
                        "u2_fires_own_side_added_after_results": bool(r > 1.5 * own.max()
                                                                      or r < own.min() / 1.5),
                        "expected_2026_below_1": bool(cur.expected < 1)})
    return pd.DataFrame(out)


def ratio_bootstrap(s, year, reps=1000):
    """Observed/expected ratio with a 95% interval from resampling polling places.

    Zero event, sections with at least 1 valid vote. Poisson(1) weights per place,
    so sections at one place move together. This widens the interval when the zeros
    of one place are correlated, which the section-level bounds ignore.
    """
    v = s[s.n >= 1]
    pid = v.groupby(PLACE, sort=False).ngroup().to_numpy()
    P = pid.max() + 1
    cols, names = [], []
    for side in SIDES:
        y = (v[f"votes_{side}"] == 0).to_numpy().astype(float)
        cols.append(np.bincount(pid, y, P)); names.append((side, "observed"))
        for model, tag, _ in MODELS:
            cols.append(np.bincount(pid, v[f"q0_{tag}_{side}"].to_numpy(), P)); names.append((side, model))
    M = np.vstack(cols).T.astype(np.float64)
    rng = np.random.default_rng(SEED + year)
    sums = []
    for _ in range(reps // 100):
        W = rng.poisson(1.0, size=(100, P)).astype(np.float64)
        sums.append(W @ M)
    S = np.vstack(sums)
    out = []
    for side in SIDES:
        io = names.index((side, "observed"))
        for model, tag, _ in MODELS:
            ie = names.index((side, model))
            r = S[:, io] / S[:, ie]
            out.append({"year": year, "side": side, "model": model,
                        "ratio": M[:, io].sum() / M[:, ie].sum(),
                        "ratio_lo95": float(np.quantile(r, 0.025)),
                        "ratio_hi95": float(np.quantile(r, 0.975)), "places": P, "reps": reps})
    return out


def describe_zeros(year, s):
    """List zero sections for both sides with round-1 share of the same candidate."""
    z = s[(s.n >= 1) & ((s.votes_pt == 0) | (s.votes_opp == 0))].copy()
    z["zero_for"] = np.where(z.votes_opp == 0, "opp", "pt")
    z["zero_for_name"] = [cand_name(year, x) for x in z.zero_for]
    z["r1_share_same_candidate"] = np.where(
        z.zero_for == "opp", z.r1_opp, z.r1_pt) / z.r1_nominal.where(z.r1_nominal > 0)
    z["year"] = year
    qcols = []
    for _, tag, _ in MODELS:
        z[f"q0_{tag}_zero_candidate"] = np.where(z.zero_for == "opp", z[f"q0_{tag}_opp"],
                                                 z[f"q0_{tag}_pt"])
        qcols.append(f"q0_{tag}_zero_candidate")
    z["placemates_zero_for_zero_candidate"] = np.where(z.zero_for == "opp", z.placemates_zero_opp,
                                                       z.placemates_zero_pt)
    cols = ["year", "zero_for", "zero_for_name", "region", "SG_UF", "NM_MUNICIPIO",
            "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO",
            "DS_LOCAL_VOTACAO_ENDERECO", "NM_BAIRRO", "DS_TIPO_LOCAL", "QT_APTOS",
            "QT_COMPARECIMENTO", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS", "n", "votes_pt",
            "votes_opp", "place_sections", "place_fallback", "placemates_zero_for_zero_candidate",
            "p_pt_mun", "p_pt_place", *qcols,
            "r1_nominal", "r1_pt", "r1_opp", "r1_share_same_candidate",
            "place_category", "is_prison", "is_prison_by_name", "is_indigenous", "ind_name",
            "ind_address", "ind_district", "ind_district_only", "district_is_zona_rural_indigena",
            "is_quilombola", "is_river", "is_rural", "is_indig_rural_river", "is_school",
            "is_indigenous_v1", "is_river_v1", "is_rural_v1", "is_indig_rural_river_v1",
            "DS_ORIGEM_VOTO", "DS_MODELO_URNA"]
    return z[[c for c in cols if c in z]].sort_values(["zero_for", "SG_UF", "NM_MUNICIPIO"])


FLAGS = ("is_indigenous", "is_quilombola", "is_river", "is_rural", "is_indig_rural_river",
         "is_prison", "is_school", "is_indigenous_v1", "is_indig_rural_river_v1")


def summarize_zeros(year, s, z):
    rows = []
    v = s[s.n >= 1]
    base = {"year": year, "group": "all sections with n>=1", "side": "-", "sections": len(v),
            "median_electorate": v.QT_APTOS.median(), "median_valid": v.n.median()}
    for f in FLAGS:
        base[f] = v[f].mean()
        base[f + "_count"] = int(v[f].sum())
    rows.append(base)
    for side in SIDES:
        g = z[z.zero_for == side]
        r = {"year": year, "group": "zero sections", "side": side,
             "candidate_with_zero": cand_name(year, side), "sections": len(g),
             "median_electorate": g.QT_APTOS.median(), "median_valid": g.n.median(),
             "other_candidate_votes": int(g["votes_pt" if side == "opp" else "votes_opp"].sum()),
             "r1_share_ge_10pct": int((g.r1_share_same_candidate >= 0.10).sum()),
             "r1_share_lt_5pct": int((g.r1_share_same_candidate < 0.05).sum()),
             "r1_share_zero": int((g.r1_share_same_candidate == 0).sum())}
        for f in FLAGS:
            r[f] = g[f].mean() if len(g) else np.nan
            r[f + "_count"] = int(g[f].sum())
        rows.append(r)
    return rows


def scale(year, s, z):
    v = s[s.n >= 1]
    tot_pt, tot_opp = int(s.votes_pt.sum()), int(s.votes_opp.sum())
    margin = tot_pt - tot_opp
    out = {"year": year, "sections_total": len(s), "sections_with_valid_votes": len(v),
           "valid_votes_total": tot_pt + tot_opp, "votes_pt": tot_pt, "votes_opp": tot_opp,
           "pt_name": cand_name(year, "pt"), "opp_name": cand_name(year, "opp"),
           "margin_pt_minus_opp": margin}
    for side in SIDES:
        g = z[z.zero_for == side]
        other = "votes_pt" if side == "opp" else "votes_opp"
        out[f"zero_{side}_sections"] = len(g)
        out[f"zero_{side}_share_of_sections"] = len(g) / len(v)
        out[f"zero_{side}_valid_votes"] = int(g.n.sum())
        out[f"zero_{side}_share_of_valid_votes"] = g.n.sum() / (tot_pt + tot_opp)
        out[f"zero_{side}_other_candidate_votes"] = int(g[other].sum())
    a = out["zero_opp_other_candidate_votes"]  # PT-side votes where the opponent had zero
    b = out["zero_pt_other_candidate_votes"]   # opponent votes where the PT side had zero
    out["margin_if_all_zero_sections_annulled"] = margin - a + b
    out["margin_if_votes_in_opp_zero_sections_moved_to_opp"] = margin - 2 * a
    # Both sides: every opponent vote in every zero section goes to the zero candidate.
    out["margin_if_opponent_votes_moved_to_zero_candidate_both_sides"] = margin - 2 * a + 2 * b
    out["pt_votes_in_opp_zero_sections_as_share_of_margin"] = a / abs(margin)
    out["votes_needed_to_move_to_flip"] = abs(margin) // 2 + 1
    return out


def history_2022(z26):
    """Approximate match of 2026 zero sections to the same key in 2022 round 2."""
    s22 = pd.read_parquet(DERIVED / "sections_2022_r2.parquet")
    s22 = s22[KEY + ["n", "votes_pt", "votes_opp", "NM_LOCAL_VOTACAO"]].rename(
        columns={"n": "n_2022", "votes_pt": "pt_2022", "votes_opp": "opp_2022",
                 "NM_LOCAL_VOTACAO": "place_2022"})
    h = z26.merge(s22, on=KEY, how="left")
    h["same_place_name"] = h.place_2022.fillna("").str.upper() == h.NM_LOCAL_VOTACAO.str.upper()
    h["share_2022_same_side"] = np.where(h.zero_for == "opp", h.opp_2022, h.pt_2022) / h.n_2022
    return h


if __name__ == "__main__":
    acc = {k: [] for k in ("oe", "phi", "scores", "calib", "decomp", "boot")}
    zrows, srows, zlists = [], [], {}
    for year in YEARS:
        s, oe, phi, sc, cal, dec = model_year(year)
        s.to_parquet(DERIVED / f"sections_model_{year}.parquet")  # per-section model probabilities
        z = describe_zeros(year, s)
        zlists[year] = z
        write_csv(z, f"zero_sections_{year}.csv", private=True)
        zrows += summarize_zeros(year, s, z)
        srows.append(scale(year, s, z))
        for k, df in (("oe", oe), ("phi", phi), ("scores", sc), ("calib", cal), ("decomp", dec)):
            acc[k].append(df)
        acc["boot"].append(pd.DataFrame(ratio_bootstrap(s, year)))
        reg = (z.groupby(["zero_for", "region"]).agg(
            sections=("n", "size"), valid_votes=("n", "sum"),
            votes_pt=("votes_pt", "sum"), votes_opp=("votes_opp", "sum"))
            .reset_index().assign(year=year))
        write_csv(reg, f"zero_by_region_{year}.csv")
        write_csv(z.groupby(["zero_for", "SG_UF"]).size().rename("sections").reset_index()
                  .assign(year=year), f"zero_by_state_{year}.csv")
        # Zero sections by official place type, against all sections (added in v2).
        v = s[s.n >= 1]
        allt = v.DS_TIPO_LOCAL.replace("", "(blank)").value_counts().rename("all_sections")
        zt = z.assign(t=z.DS_TIPO_LOCAL.replace("", "(blank)")).groupby(["t", "zero_for"]).size() \
            .unstack(fill_value=0).reindex(columns=["opp", "pt"], fill_value=0)
        zt.columns = ["zero_opp", "zero_pt"]
        write_csv(pd.concat([allt, zt], axis=1).fillna(0).astype(int).rename_axis("official_place_type")
                  .reset_index().assign(year=year), f"zero_by_official_place_type_{year}.csv")
        cnt = []
        for minn in (1, 2, 5, 10, 20, 50, 100):
            vv = s[s.n >= minn]
            cnt.append({"year": year, "min_valid_votes": minn,
                        "zero_opp": int((vv.votes_opp == 0).sum()),
                        "zero_pt": int((vv.votes_pt == 0).sum()),
                        "pt_votes_in_zero_opp": int(vv.loc[vv.votes_opp == 0, "votes_pt"].sum()),
                        "opp_votes_in_zero_pt": int(vv.loc[vv.votes_pt == 0, "votes_opp"].sum())})
        cnt.append({"year": year, "min_valid_votes": 0, "zero_opp": int((s.n == 0).sum()),
                    "zero_pt": int((s.n == 0).sum()), "pt_votes_in_zero_opp": 0,
                    "opp_votes_in_zero_pt": 0})
        write_csv(pd.DataFrame(cnt), f"zero_counts_by_min_size_{year}.csv")
        print(year, "done", flush=True)

    oe = pd.concat(acc["oe"])
    write_csv(oe, "observed_vs_expected.csv")
    write_csv(pd.concat(acc["phi"]), "bb_phi_by_state.csv")
    u2 = u2_check(oe)
    write_csv(u2, "u2_history_check.csv")
    write_csv(pd.concat(acc["scores"]), "model_scores.csv")
    write_csv(pd.concat(acc["calib"]), "calibration.csv")
    write_csv(pd.concat(acc["decomp"]), "m1_expectation_decomposition.csv")
    write_csv(pd.concat(acc["boot"]), "ratio_bootstrap_places.csv")
    write_csv(pd.DataFrame(zrows), "zero_sections_summary.csv")
    write_csv(pd.DataFrame(srows), "scale.csv")
    write_csv(history_2022(zlists[2026]), "zero_sections_2026_history_2022.csv", private=True)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    m = oe[(oe.event == "zero") & (oe.min_valid_votes == 1)]
    print(m[["year", "side", "model", "observed", "expected", "upper_99_9_exact",
             "p_exact_ge_observed", "obs_over_exp"]].round(4).to_string(index=False))
    print("U2 pooled fired:", int(u2.u2_fires_pooled.sum()), "of", len(u2))
