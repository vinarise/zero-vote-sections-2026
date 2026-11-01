"""Step 6. EXPLORATORY diagnostics, added AFTER the first results.

Nothing here was pre-registered (EXPERIMENT.md, deviations 4 and 13). v1 asked
where the BB-mun U2 signal sits and answered "composition, not a higher zero
rate". A full recheck on 2026-10-29 (item M4) showed that answer did not hold
up. v2 redoes it:
  D1. Observed vs expected zeros by inferred place category, each year and side,
      with the v2 classifier and with the v1 flag.
  D2. Indigenous-flagged sections: count, zeros, zero rate, pooled share, BB-mun
      expected, for both classifiers, each year and side.
  D3. The municipality leave-one-out share of the zero candidate around the zero
      sections, by year and side.
  R1. Composition reweighting: 2026 with the indigenous-flagged share held at its
      2022 level and the 2026 zero rate kept. Both sides, with the v2 and v1 text
      flags and with the step-11 register category (added after a later recheck).
  R2. Flag components by year: name, address, district, district only, and the
      district value "ZONA RURAL INDÍGENA".
  R3. Places matched across years by municipality and place name (and, stricter,
      by place key and name), so new places are separated from relabelled ones.
      A stable panel of places flagged in both years gives a zero rate free of
      composition change.
  R4. How round 1 maps to round 2 nationally: the top-two share of round 1, and the
      non-PT share of the top two in each round (added after a later recheck).
  D4, D5. Unchanged descriptive tables (2022 history, round-1 share).
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DERIVED, KEY, PRIVATE, RES, SIDES, YEARS, cand_name, write_csv  # noqa: E402

# Reuse the text normaliser and the v1 patterns from step 3.
spec = importlib.util.spec_from_file_location("build", Path(__file__).parent / "03_build.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


S = {}
for year in YEARS:
    s = pd.read_parquet(DERIVED / f"sections_model_{year}.parquet")
    s = s[s.n >= 1].copy()
    # v1 indigenous pattern applied to each field separately (for R2).
    for fld, col in (("name", "NM_LOCAL_VOTACAO"), ("address", "DS_LOCAL_VOTACAO_ENDERECO"),
                     ("district", "NM_BAIRRO")):
        s[f"ind_v1_{fld}"] = s[col].map(b.norm).str.contains(b.PAT_V1["indigenous"], regex=True)
    # Register category from step 11 (2026 and 2022 only, the years with registers).
    reg = DERIVED / f"register_categories_{year}.parquet"
    if reg.exists():
        s = s.merge(pd.read_parquet(reg, columns=KEY + ["reg_village"]), on=KEY, how="left")
        s["reg_village"] = s.reg_village.fillna(False).astype(bool)
    S[year] = s

d1, d2, d3 = [], [], []
for year, v in S.items():
    for side in SIDES:
        y = v[f"votes_{side}"] == 0
        groups = [(f"category: {c}", v.place_category == c) for c in sorted(v.place_category.unique())]
        groups += [("v1 flag: indigenous by text", v.is_indigenous_v1),
                   ("v1 flag: indigenous, rural or river", v.is_indig_rural_river_v1),
                   ("v1 flag: not flagged", ~v.is_indig_rural_river_v1),
                   ("v2 flag: indigenous", v.is_indigenous),
                   ("v2: not indigenous, not prison", ~v.is_indigenous & ~v.is_prison),
                   ("all sections", pd.Series(True, index=v.index))]
        for gname, mask in groups:
            g = v[mask]
            d1.append({"year": year, "side": side, "candidate": cand_name(year, side), "group": gname,
                       "sections": len(g), "observed_zeros": int(y[mask].sum()),
                       "expected_BB_mun": g[f"q0_bbmun_{side}"].sum(),
                       "expected_BB_place": g[f"q0_bbplace_{side}"].sum(),
                       "expected_EB_r1": g[f"q0_ebr1_{side}"].sum(),
                       "expected_B_mun": g[f"q0_bmun_{side}"].sum()})
        x = v[f"votes_{side}"]
        share = x / v.n
        for clf, ind in (("v2", v.is_indigenous), ("v1", v.is_indigenous_v1)):
            d2.append({"year": year, "side": side, "candidate": cand_name(year, side), "classifier": clf,
                       "indigenous_flagged_sections": int(ind.sum()),
                       "median_share_in_flagged": share[ind].median(),
                       "pooled_share_in_flagged": x[ind].sum() / v.n[ind].sum(),
                       "flagged_sections_share_lt_1pct": int((share[ind] < 0.01).sum()),
                       "flagged_sections_zero": int((x[ind] == 0).sum()),
                       "zero_rate_in_flagged": float((x[ind] == 0).mean()),
                       "expected_BB_mun_in_flagged": v.loc[ind, f"q0_bbmun_{side}"].sum(),
                       "national_share": x.sum() / v.n.sum()})
        z = v[y]
        p_mun = z.p_pt_mun if side == "pt" else 1 - z.p_pt_mun
        d3.append({"year": year, "side": side, "candidate": cand_name(year, side),
                   "zero_sections": len(z), "median_mun_loo_share_of_zero_candidate": p_mun.median(),
                   "mean_mun_loo_share_of_zero_candidate": p_mun.mean(),
                   "median_valid_votes": z.n.median(),
                   "zero_sections_alone_in_their_place": int(z.place_fallback.sum())})

# R1. Composition reweighting, BB-mun, zero event, n >= 1.
u2 = pd.read_csv(RES / "u2_history_check.csv")
r1 = []
for side in SIDES:
    row = u2[(u2.event == "zero") & (u2.min_valid_votes == 1) & (u2.model == "BB-mun") & (u2.side == side)].iloc[0]
    # "registers" uses the step-11 category "indigenous village or community" (1 km rule).
    # 2022 has fewer usable coordinates than 2026, and 2018 has no register category.
    for clf, col in (("v2", "is_indigenous"), ("v1", "is_indigenous_v1"), ("registers", "reg_village")):
        st = {}
        for year in YEARS:
            v = S[year]
            if col not in v:
                st[year] = {"N": len(v), "Nf": np.nan, "Zf": np.nan, "Ef": np.nan, "Oo": np.nan, "Eo": np.nan}
                continue
            f = v[col]
            y = v[f"votes_{side}"] == 0
            q = v[f"q0_bbmun_{side}"]
            st[year] = {"N": len(v), "Nf": int(f.sum()), "Zf": int(y[f].sum()), "Ef": q[f].sum(),
                        "Oo": int(y[~f].sum()), "Eo": q[~f].sum()}
        a, c = st[2026], st[2022]
        share22 = c["Nf"] / c["N"]
        nf_cf = share22 * a["N"]
        z_cf = nf_cf * a["Zf"] / a["Nf"]
        e_cf = nf_cf * a["Ef"] / a["Nf"]
        r1.append({"side": side, "candidate_2026": cand_name(2026, side), "classifier": clf,
                   "flagged_share_2022": share22, "flagged_share_2026": a["Nf"] / a["N"],
                   "flagged_sections_2026": a["Nf"], "flagged_sections_at_2022_share": nf_cf,
                   "zero_rate_flagged_2026": a["Zf"] / a["Nf"],
                   "zero_rate_flagged_2022": c["Zf"] / c["Nf"],
                   "zero_rate_flagged_2018": st[2018]["Zf"] / st[2018]["Nf"],
                   "observed_outside_2026": a["Oo"], "expected_outside_2026": a["Eo"],
                   "observed_outside_2022": c["Oo"], "expected_outside_2022": c["Eo"],
                   "observed_outside_2018": st[2018]["Oo"], "expected_outside_2018": st[2018]["Eo"],
                   "zeros_flagged_counterfactual": z_cf, "expected_flagged_counterfactual": e_cf,
                   "ratio_2026_actual": (a["Oo"] + a["Zf"]) / (a["Eo"] + a["Ef"]),
                   "ratio_2026_counterfactual": (a["Oo"] + z_cf) / (a["Eo"] + e_cf),
                   "ratio_2026_outside_flagged_only": a["Oo"] / a["Eo"] if a["Eo"] else np.nan,
                   "ratio_2022_outside_flagged_only": c["Oo"] / c["Eo"] if c["Eo"] else np.nan,
                   "u2_threshold_pooled": 1.5 * row.baseline_max_pooled,
                   "u2_threshold_own_side": 1.5 * max(row.own_side_ratio_2022, row.own_side_ratio_2018)})

# R2. Flag components by year, both classifiers, with zeros for each side.
r2 = []
for year, v in S.items():
    comps = {
        "v2 indigenous, any field": v.is_indigenous,
        "v2 by place name": v.ind_name, "v2 by address": v.ind_address, "v2 by district": v.ind_district,
        "v2 by district only": v.ind_district_only,
        "district text is exactly ZONA RURAL INDIGENA": v.district_is_zona_rural_indigena,
        "v1 indigenous, any field": v.is_indigenous_v1,
        "v1 pattern on place name": v.ind_v1_name, "v1 pattern on address": v.ind_v1_address,
        "v1 pattern on district": v.ind_v1_district,
        "v1 pattern on district only": v.ind_v1_district & ~v.ind_v1_name & ~v.ind_v1_address,
    }
    for cname, mask in comps.items():
        r2.append({"year": year, "component": cname, "sections": int(mask.sum()),
                   "zero_opp": int((mask & (v.votes_opp == 0)).sum()),
                   "zero_pt": int((mask & (v.votes_pt == 0)).sum())})

# R3. Places matched across years.
r3, panel = [], []
for later, earlier in ((2026, 2022), (2022, 2018)):
    L, E = S[later], S[earlier]
    for match, keys in (("municipality + place name", ["SG_UF", "CD_MUNICIPIO", "place_name_norm"]),
                        ("place key + place name", ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO",
                                                    "place_name_norm"])):
        pe = E.groupby(keys).agg(flag_earlier=("is_indigenous", "max"), sections_earlier=("n", "size"),
                                 zero_opp_earlier=("votes_opp", lambda x: int((x == 0).sum())),
                                 zero_pt_earlier=("votes_pt", lambda x: int((x == 0).sum()))).reset_index()
        m = L.merge(pe, on=keys, how="left")
        m["status"] = np.select(
            [m.sections_earlier.isna(), m.flag_earlier.fillna(False).astype(bool)],
            ["place name not found in the earlier year (new or renamed)",
             "same place in both years, flagged in both"],
            "same place in both years, flagged only in the later year (text changed)")
        f = m[m.is_indigenous]
        for st, g in f.groupby("status"):
            r3.append({"later_year": later, "earlier_year": earlier, "match": match, "status": st,
                       "sections_later": len(g), "zero_opp_later": int((g.votes_opp == 0).sum()),
                       "zero_pt_later": int((g.votes_pt == 0).sum()),
                       "expected_BB_mun_opp_later": g.q0_bbmun_opp.sum()})
        # Flagged in the earlier year, gone or unflagged in the later year.
        pl = L.groupby(keys).agg(flag_later=("is_indigenous", "max")).reset_index()
        me = E[E.is_indigenous].merge(pl, on=keys, how="left")
        for st, g in me.groupby(np.where(me.flag_later.isna(), "earlier flagged place not found later",
                                         np.where(me.flag_later.fillna(False).astype(bool),
                                                  "earlier flagged place still flagged later",
                                                  "earlier flagged place unflagged later"))):
            r3.append({"later_year": later, "earlier_year": earlier, "match": match, "status": st,
                       "sections_earlier": len(g), "zero_opp_earlier": int((g.votes_opp == 0).sum()),
                       "zero_pt_earlier": int((g.votes_pt == 0).sum())})
        # Stable panel: places flagged in both years under this match.
        both = set(map(tuple, m.loc[m.is_indigenous & m.flag_earlier.fillna(False).astype(bool), keys]
                       .drop_duplicates().to_numpy()))
        for yr, D in ((later, L), (earlier, E)):
            mask = D[keys].apply(tuple, axis=1).isin(both) & D.is_indigenous
            g = D[mask]
            panel.append({"panel": f"{earlier}-{later}", "match": match, "year": yr,
                          "places": len(both), "sections": len(g),
                          "zero_opp": int((g.votes_opp == 0).sum()), "zero_pt": int((g.votes_pt == 0).sum()),
                          "zero_rate_opp": float((g.votes_opp == 0).mean()) if len(g) else np.nan,
                          "zero_rate_pt": float((g.votes_pt == 0).mean()) if len(g) else np.nan,
                          "pooled_share_opp": g.votes_opp.sum() / g.n.sum() if len(g) else np.nan,
                          "expected_BB_mun_opp": g.q0_bbmun_opp.sum()})

# R4. How round 1 maps to round 2, nationally (added after results, in a later recheck).
# Valid votes for President are the nominal votes. The "top two" are the two runoff
# candidates, who were also first and second in round 1 in all three years.
r4 = []
for year in YEARS:
    s1 = pd.read_parquet(DERIVED / f"sections_{year}_r1.parquet", columns=["votes_pt", "votes_opp", "QT_VOTOS_NOMINAIS"])
    s2 = pd.read_parquet(DERIVED / f"sections_{year}_r2.parquet", columns=["votes_pt", "votes_opp"])
    t1, t2 = s1.votes_pt.sum() + s1.votes_opp.sum(), s2.votes_pt.sum() + s2.votes_opp.sum()
    r4.append({"year": year, "pt_candidate": cand_name(year, "pt"), "opp_candidate": cand_name(year, "opp"),
               "r1_valid_votes": int(s1.QT_VOTOS_NOMINAIS.sum()), "r1_top_two_votes": int(t1),
               "r1_top_two_share_of_valid": t1 / s1.QT_VOTOS_NOMINAIS.sum(),
               "r1_opp_share_of_top_two": s1.votes_opp.sum() / t1,
               "r2_opp_share_of_top_two": s2.votes_opp.sum() / t2,
               "change_opp_share_r1_to_r2": s2.votes_opp.sum() / t2 - s1.votes_opp.sum() / t1})

# D4. 2026 zero sections matched to 2022 by key and same place name (approximate).
h = pd.read_csv(PRIVATE / "zero_sections_2026_history_2022.csv")
d4 = []
for side in SIDES:
    g = h[h.zero_for == side]
    gg = g[g.same_place_name]
    sh = gg.share_2022_same_side
    d4.append({"side": side, "zero_sections_2026": len(g), "same_key_in_2022": int(g.n_2022.notna().sum()),
               "same_key_and_place_name": len(gg), "median_2022_share_same_side": sh.median(),
               "max_2022_share_same_side": sh.max(), "n_2022_share_zero": int((sh == 0).sum()),
               "n_2022_share_lt_5pct": int((sh < 0.05).sum())})
# D5. Round-1 share of the same candidate in 2026 zero sections.
z26 = pd.read_csv(PRIVATE / "zero_sections_2026.csv")
d5 = (z26.groupby("zero_for").r1_share_same_candidate
      .agg(["count", "median", "max", lambda x: int((x == 0).sum()), lambda x: int((x < 0.05).sum()),
            lambda x: int((x >= 0.10).sum())]))
d5.columns = ["sections", "median_r1_share", "max_r1_share", "r1_zero", "r1_lt_5pct", "r1_ge_10pct"]
write_csv(d5, "diag_round1_share_2026_zero_sections.csv", index=True)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
for name, rows in (("diag_by_place_category", d1), ("diag_indigenous_flagged_places", d2),
                   ("diag_local_share_in_zero_sections", d3),
                   ("diag_history_2022_of_2026_zero_sections", d4),
                   ("m4_counterfactual_reweighting", r1), ("m4_flag_components_by_year", r2),
                   ("round_mapping_by_year", r4),
                   ("m4_place_matching_across_years", r3), ("m4_stable_panel_zero_rates", panel)):
    df = pd.DataFrame(rows)
    write_csv(df, f"{name}.csv")
    print(name)
    print(df.round(4).to_string(index=False))
