"""Step 8. Data files for an interactive piece, v2. Written to interactive/.
Runs after step 11, whose register categories it reads.

v2 replaces the v1 files after a full recheck (item M7). v1 listed 408 named
sections with coordinates, including small, prison and unanimous sections. v2
publishes no section row, no polling-place name and no coordinate.

PRIVACY RULE (repeated at the top of every file written here):
  1. No section or polling place is named, located or listed. The smallest
     published unit is the municipality (a city, for votes abroad).
  2. A municipality or city is shown by name only if it has at least 50 apt
     voters and neither candidate has 0 votes or all the valid votes in it.
     Units that fail are pooled into one row per state ("other, pooled").
  3. No municipal-level file counts zero or near-unanimous sections, because a
     small municipality's count can point at a single community. Zero sections
     are published only nationally, by region and by state (results/zero_by_*),
     and as national category totals, by two labelled methods (official registers
     within 1 km, from step 11, and the text rule of step 3). A category cell with
     fewer than 10 sections is suppressed.
  4. Nothing about individual voters is used or derivable.

  municipal_2026_2t.csv           per municipality: sections, electorate, turnout, votes, shares
  zero_sections_by_category.csv   national counts by place category, by two labelled methods
  summary_by_year.json            observed vs expected, 2018, 2022, 2026, exact bounds
  SOURCES.md, README.md           sources, terms of use and the rule above
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DERIVED, FLOAT_FORMAT, HERE, INTERACTIVE as OUT, MUN, RAW, RES  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)
MIN_APT, MIN_CELL = 50, 10
RULE = [
    "PRIVACY RULE. No section or polling place is named, located or listed. The smallest unit is the "
    "municipality (a city, for votes abroad).",
    f"A municipality or city is named only if it has at least {MIN_APT} apt voters and neither candidate "
    "has 0 votes or all the valid votes in it. Others are pooled per state as 'other, pooled'.",
    "No municipal-level file counts zero or near-unanimous sections. Zero sections are published only "
    "nationally, by region and by state, and as national place-category totals by two methods (official "
    f"registers within 1 km, and the text rule), with cells under {MIN_CELL} sections suppressed.",
    "Source: TSE open data, 2026 round 2, President. See SOURCES.md. Built by 08_interactive.py (v2).",
]
NAME = {"pt": "lula", "opp": "flavio"}

cands = pd.read_csv(RES / "candidates.csv")


def r6(x):
    return None if pd.isna(x) else float(round(float(x), 6))


def write_csv(df, path):
    """CSV with the privacy rule as leading '#' lines (read with comment='#')."""
    with open(path, "w", encoding="utf-8") as fh:
        for line in RULE:
            fh.write(f"# {line}\n")
        df.to_csv(fh, index=False, float_format=FLOAT_FORMAT)


s = pd.read_parquet(DERIVED / "sections_model_2026.parquet")
s = s[s.n >= 1].copy()

# 1. Municipal table. IBGE codes come from the official TSE correspondence table.
with zipfile.ZipFile(RAW / "municipio_tse_ibge.zip") as z:
    member = [m for m in z.namelist() if m.lower().endswith(".csv")][0]
    tse_ibge = pd.read_csv(io.TextIOWrapper(z.open(member), encoding="latin1"), sep=";", dtype=str)
tse_ibge = tse_ibge.assign(CD_MUNICIPIO=tse_ibge.CD_MUNICIPIO_TSE.astype(int),
                           ibge_code=pd.to_numeric(tse_ibge.CD_MUNICIPIO_IBGE, errors="coerce"))
tse_ibge = tse_ibge[["CD_MUNICIPIO", "ibge_code"]].drop_duplicates("CD_MUNICIPIO")

# No zero, near-zero or expected-zero counts per municipality (rule 3).
agg = {"NM_MUNICIPIO": "first", "region": "first", "votes_pt": "sum", "votes_opp": "sum",
       "n": "sum", "QT_APTOS": "sum", "QT_COMPARECIMENTO": "sum", "NR_SECAO": "size"}
mu = s.groupby(MUN).agg(agg).reset_index().rename(columns={"NR_SECAO": "sections_with_valid_votes"})
mu = mu.merge(tse_ibge, on="CD_MUNICIPIO", how="left")
mu["passes_rule"] = (mu.QT_APTOS >= MIN_APT) & (mu.votes_pt > 0) & (mu.votes_opp > 0)
named, pooled = mu[mu.passes_rule], mu[~mu.passes_rule]
if len(pooled):
    num = ["votes_pt", "votes_opp", "n", "QT_APTOS", "QT_COMPARECIMENTO", "sections_with_valid_votes"]
    pl = pooled.groupby("SG_UF")[num].sum().reset_index()
    pl["NM_MUNICIPIO"] = "other, pooled"
    pl["region"] = pooled.groupby("SG_UF").region.first().values
    pl["units_pooled"] = pooled.groupby("SG_UF").size().values
    named = pd.concat([named.assign(units_pooled=1), pl], ignore_index=True)
out = pd.DataFrame({
    "state": named.SG_UF, "municipality": named.NM_MUNICIPIO,
    "municipality_code_tse": named.CD_MUNICIPIO.astype("Int64"),
    "ibge_code": named.ibge_code.astype("Int64"), "units_pooled": named.units_pooled.astype(int),
    "region": named.region, "sections_with_valid_votes": named.sections_with_valid_votes,
    "eligible_voters": named.QT_APTOS, "votes_cast": named.QT_COMPARECIMENTO, "valid_votes": named.n,
    "votes_lula": named.votes_pt, "votes_flavio": named.votes_opp,
    "share_lula": (named.votes_pt / named.n).round(6), "share_flavio": (named.votes_opp / named.n).round(6)})
out = out.sort_values(["state", "municipality"])
write_csv(out, OUT / "municipal_2026_2t.csv")
br = out[out.state != "ZZ"]
ibge_missing = br[br.ibge_code.isna() & (br.units_pooled == 1)]
ibge_missing.to_csv(RES / "ibge_unmatched_municipalities.csv", index=False, float_format=FLOAT_FORMAT)

# 2. Zero sections by place category, national totals only, small cells suppressed.
# Two methods, each labelled. "registers, 1 km" is the step-11 category of the polling
# place from official registers. A zero section whose place has no usable coordinate
# takes step 11's text fallback, as in the published zero-section counts. "text rule" is
# the step-3 category from the place's name, address and district (prison = official type).
reg = pd.read_parquet(DERIVED / "register_categories_2026.parquet", columns=["SG_UF", "CD_MUNICIPIO", "NR_ZONA",
                                                                          "NR_SECAO", "register_label"])
s = s.merge(reg, on=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"], how="left", validate="one_to_one")
s["register_label"] = s.register_label.fillna("unresolved")
rows = []
for method, col in (("registers, 1 km", "register_label"), ("text rule", "place_category")):
    for cat, gc in s.groupby(col):
        rec = {"scope": "Brazil and abroad", "method": method, "place_category": cat, "sections": len(gc)}
        for sd in ("pt", "opp"):
            rec[f"zero_sections_{NAME[sd]}"] = int((gc[f"votes_{sd}"] == 0).sum())
        if len(gc) < MIN_CELL:
            rec = {k: (v if k in ("scope", "method", "place_category") else None) for k, v in rec.items()}
            rec["suppressed"] = True
        else:
            rec["suppressed"] = False
        rows.append(rec)
write_csv(pd.DataFrame(rows), OUT / "zero_sections_by_category.csv")

# 3. Summary by year, with exact bounds.
oe = pd.read_csv(RES / "observed_vs_expected.csv")
summ = {"meta": {"rule": RULE,
                 "events": {"zero": "candidate had 0 votes",
                            "share_lt_1pct": "candidate had under 1% of valid votes",
                            "votes_le_2": "candidate had 2 votes or fewer"},
                 "min_valid_votes": "sections included have at least this many valid votes",
                 "upper_99_9_exact": "exact 99.9% quantile of the Poisson-binomial sum, sections independent",
                 "upper_99_9_normal": "v1 normal approximation, kept for comparison",
                 "model_status": "pre-registered, fixed in v2, or added after results",
                 "side": {"pt": "PT candidate", "opp": "the other runoff candidate"},
                 "caution": "A matching total does not mean a model finds the zero sections. "
                            "See FINDINGS-v2.md, M1."},
        "years": []}
for year in (2018, 2022, 2026):
    c = cands[(cands.year == year) & (cands["round"] == 2)].iloc[0]
    g = oe[(oe.year == year) & (oe.model != "BB-place (v1 code)")]
    summ["years"].append({
        "year": year, "candidates": {"pt": c.pt_name, "opp": c.opp_name},
        "rows": [{k: (r6(v) if isinstance(v, float) else (bool(v) if isinstance(v, (bool, np.bool_))
                     else (int(v) if isinstance(v, (int, np.integer)) else v)))
                  for k, v in rec.items() if k not in ("year", "candidate")}
                 for rec in g.to_dict("records")]})
(OUT / "summary_by_year.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1))

# 4. README.md and SOURCES.md
smp = pd.read_csv(RES / "m5b_text_rule_samples.csv")
rec = smp[(smp.threshold == "1 km") & (smp.quantity == "recall in frame municipalities")].iloc[0]
(OUT / "README.md").write_text("\n".join([
    "# Interactive data files, v2", "",
    "These files replace the v1 interactive files. v1 listed 408 named sections with coordinates. "
    "v2 lists none.", "", "## Privacy rule", ""] + [f"{i}. {r}" for i, r in enumerate(RULE[:3], 1)] + [
    "", "Every CSV here starts with the rule as `#` comment lines. Read with "
    "`pandas.read_csv(path, comment=\"#\")`.", "",
    "## Files", "",
    "- `municipal_2026_2t.csv`: one row per municipality or city abroad that passes the rule, plus one "
    "pooled row per state for units that do not. Sections, electorate, turnout, votes and shares only. "
    "It has no count of zero or near-unanimous sections, because a small municipality's count can point "
    "at a single community. Zero sections by state and by region are in `results/zero_by_state_2026.csv` "
    "and `results/zero_by_region_2026.csv`.",
    "- `zero_sections_by_category.csv`: national counts by place category, by two methods. "
    "`registers, 1 km` is the headline method: the polling place's category from official IBGE, FUNAI "
    "and INCRA registers (step 11). `text rule` is the category inferred from the place's name, address "
    "and district (step 3). Against the registers the text rule finds about "
    f"{rec.estimate:.0%} of indigenous places (recall {rec.estimate:.1%}, 95% interval {rec.lo95:.1%} to "
    f"{rec.hi95:.1%}, `results/m5b_text_rule_samples.csv`), so its counts are lower bounds. Neither "
    "method is ground truth.",
    "- `summary_by_year.json`: observed and expected zeros and near zeros, 2018, 2022, 2026.",
    "- `SOURCES.md`: every source file.", ""]))

src = pd.read_csv(HERE / "sources.lock.tsv", sep="\t")
lines = [
    "# Sources", "",
    "Generated by `08_interactive.py` (v2) from `sources.lock.tsv`, the reference download of 2026-10-29.",
    "",
    "## Terms of use", "",
    "- **TSE files.** The TSE open-data portal lists the packages `resultados-2026`, "
    "`resultados-2026-boletim-de-urna`, `resultados-2022`, `resultados-2018`, `eleitorado-2026` and "
    "`codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge` with licence `cc-by`. "
    "Read from the CKAN API (`/api/3/action/package_show`) on 2026-10-29. Attribution: Tribunal Superior "
    "Eleitoral.",
    "",
    "## Codes",
    "",
    "- IBGE codes in `municipal_2026_2t.csv` come from the TSE table `municipio_tse_ibge.zip`. "
    f"Brazilian municipalities without an IBGE code there: {len(ibge_missing)}.",
    "",
    "## Outside registers",
    "",
    "- Files of kind `register` (IBGE, FUNAI, INCRA) and `ibge_api` (the IBGE municipal mesh) are used only "
    "by step 11. Their download pages state no licence. Brazilian federal open-data policy (Decreto 8.777/2016) applies "
    "(inference). They are cited, not redistributed.",
    "- INCRA regenerates its file every night and FUNAI builds its files on request. The SHA-256 below is "
    "that of the archived copy used for the published tables.",
    "",
    "## Files", "",
    "| Kind | File | URL | Bytes | Last-modified (HTTP) | Downloaded (UTC) | SHA-256 |",
    "|---|---|---|---|---|---|---|",
]
for r in src.itertuples(index=False):
    lines.append(f"| {r.kind} | {r.file} | {r.url} | {int(r.bytes):,} | {r.http_last_modified} | "
                 f"{r.reference_download_utc} | `{r.sha256}` |")
(OUT / "SOURCES.md").write_text("\n".join(lines) + "\n")

print("municipal rows", len(out), "| pooled units", int(len(pooled)), "| states with pooled rows",
      int((out.municipality == "other, pooled").sum()), "| IBGE missing in Brazil", len(ibge_missing))
print(pd.DataFrame(rows).to_string(index=False))
