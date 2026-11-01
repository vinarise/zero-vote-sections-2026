"""Step 9. Check the inferred place classifier against analyst labels (added in v2).

Who labelled, and from what. The labels were written by the analyst who wrote the
v2 rules (an AI agent), reading only the TSE text fields (place name, address,
district) and the official place type, with the rule output visible. They were not
blind and were not checked against any outside register. So they measure whether
the text means what the rules assume (for example, a road named "Estrada de
Aldeia" is not a village). They do not measure whether a place is in fact an
indigenous or quilombola community.

  1. Merges the labels of all 110 zero sections of 2026 with both classifiers and
     the official place type, and writes the agreement.
  2. Draws a fixed random sample of 200 sections that the v2 rule flags as
     indigenous (2026, n >= 1). If labels for it exist, reports precision per
     section and per polling place, with intervals that allow for sections of one
     place sharing a label.
  3. Lists every distinct place where the v1 and v2 rules disagree in 2026.

Categories used in the labels:
  indigenous village or community   text names an aldeia, comunidade indígena,
                                    terra or território indígena, or a school or
                                    health post inside one
  indigenous school or institution  text names an indigenous school or institution
    in a town                       at a street address in a town or city
  quilombola                        text says QUILOMBO or QUILOMBOLA
  prison                            official place type "Preso provisório"
  street or road name               the marker is part of a street or road name
  rural or river, no marker         none of the above

The labels identify individual sections, so they are private. They are read from
ZV_LABELS_DIR (default: <data>/private/labels):
  zero_sections_2026_labels.csv      one row per zero section
  precision_sample_2026_labels.csv   one row per sampled section
Without them, parts 1 and 2 are skipped and only the sample to label is written.
Aggregates go to results/. Row-level outputs go to the private data folder.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DERIVED, HANDCHECK, KEY, PLACE, PRIVATE, SEED, write_csv  # noqa: E402


def wilson(k, n, z=1.959964):
    """Wilson score interval for a binomial proportion k / n."""
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def place_bootstrap(y, place, reps=10000):
    """95% interval for a section-level share, resampling polling places."""
    g = pd.DataFrame({"y": y, "p": place}).groupby("p").y.agg(["sum", "size"])
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(g), size=(reps, len(g)))
    share = g["sum"].to_numpy()[idx].sum(1) / g["size"].to_numpy()[idx].sum(1)
    return np.quantile(share, [0.025, 0.975])


HANDCHECK.mkdir(parents=True, exist_ok=True)

# 1. Labels of the 110 zero sections.
labels = HANDCHECK / "zero_sections_2026_labels.csv"
if labels.exists():
    z = pd.read_csv(PRIVATE / "zero_sections_2026.csv")
    lab = pd.read_csv(labels).drop(columns=["NM_LOCAL_VOTACAO", "zero_for"], errors="ignore")
    m = z.merge(lab, on=KEY, how="left", validate="one_to_one")
    assert m.label_category.notna().all(), "a zero section has no label"
    m["label_indigenous"] = m.label_category.eq("indigenous")
    cols = KEY + ["zero_for", "NM_MUNICIPIO", "NM_LOCAL_VOTACAO", "DS_LOCAL_VOTACAO_ENDERECO", "NM_BAIRRO",
                  "DS_TIPO_LOCAL", "QT_APTOS", "n", "label_category", "detail", "label_basis",
                  "label_confidence", "label_reason", "is_indigenous_v1", "is_indig_rural_river_v1",
                  "is_indigenous", "place_category", "ind_district_only"]
    write_csv(m[cols], "m5_labels_zero_sections_2026.csv", private=True)

    agree = []
    for clf, col in (("v1", "is_indigenous_v1"), ("v2", "is_indigenous")):
        for side in ("opp", "pt"):
            g = m[m.zero_for == side]
            agree.append({"classifier": clf, "side": side, "zero_sections": len(g),
                          "labelled_indigenous": int(g.label_indigenous.sum()), "flagged": int(g[col].sum()),
                          "agree_indigenous": int((g[col] & g.label_indigenous).sum()),
                          "flagged_not_labelled": int((g[col] & ~g.label_indigenous).sum()),
                          "labelled_not_flagged": int((~g[col] & g.label_indigenous).sum())})
    write_csv(pd.DataFrame(agree), "m5_classifier_agreement_zero_sections.csv")
    cat = m.groupby(["zero_for", "label_category", "detail"]).agg(
        sections=("n", "size"),
        district_label_only=("label_basis", lambda b: int(b.eq("district label only").sum())),
        medium_confidence=("label_confidence", lambda c: int(c.eq("medium").sum()))).reset_index()
    write_csv(cat, "m5_label_category_counts.csv")
    print(pd.DataFrame(agree).to_string(index=False))
    print(cat.to_string(index=False))
else:
    print(f"no labels at {labels}: part 1 skipped")

# 2. Precision sample of the v2 indigenous flag. The draw is fixed by the seed.
s = pd.read_parquet(DERIVED / "sections_2026_r2.parquet")
s = s[s.n >= 1]
flagged = s[s.is_indigenous]
samp = flagged.sample(200, random_state=SEED)[KEY + ["NR_LOCAL_VOTACAO", "NM_MUNICIPIO", "NM_LOCAL_VOTACAO",
                                                      "DS_LOCAL_VOTACAO_ENDERECO", "NM_BAIRRO",
                                                      "ind_name", "ind_address", "ind_district"]]
write_csv(samp, "precision_sample_2026_to_label.csv", private=True)
lab_path = HANDCHECK / "precision_sample_2026_labels.csv"
if lab_path.exists():
    j = samp.merge(pd.read_csv(lab_path)[KEY + ["label", "detail", "reason"]], on=KEY, how="left",
                   validate="one_to_one")
    assert j.label.notna().all(), "unlabelled sample row"
    place = j[PLACE].astype(str).agg("|".join, axis=1)
    rows = []
    for measure, y in (
            ("marker is not a street or road name", j.label.eq("indigenous")),
            ("indigenous village or community", j.detail.eq("indigenous village or community"))):
        k, n = int(y.sum()), len(y)
        lo, hi = place_bootstrap(y.to_numpy(), place.to_numpy())
        pl = pd.DataFrame({"y": y, "p": place}).groupby("p").y.max()  # one label per place
        plo, phi = wilson(int(pl.sum()), len(pl))
        rows.append({"measure": measure, "flagged_sections_2026": len(flagged), "sample_sections": n,
                     "sections_yes": k, "share_sections": k / n,
                     "share_sections_lo95_place_bootstrap": lo, "share_sections_hi95_place_bootstrap": hi,
                     "sample_places": len(pl), "places_yes": int(pl.sum()), "share_places": pl.mean(),
                     "share_places_lo95_wilson": plo, "share_places_hi95_wilson": phi})
    write_csv(pd.DataFrame(rows), "m5_precision_sample.csv")
    write_csv(j.detail.value_counts().rename_axis("label").reset_index(name="sections"),
              "m5_precision_label_counts.csv")
    write_csv(j[j.label.ne("indigenous")].reason.value_counts().rename_axis("reason")
              .reset_index(name="sections"), "m5_precision_false_positive_reasons.csv")
    write_csv(j, "m5_precision_sample_rows.csv", private=True)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
else:
    print(f"no labels at {lab_path}: precision not computed")

# 3. Places where v1 and v2 disagree, 2026. Row-level, so private. Totals are public.
d = s[s.is_indigenous != s.is_indigenous_v1].copy()
d["change"] = np.where(d.is_indigenous, "v2 adds", "v2 drops")
ch = (d.groupby(["change", "SG_UF", "NM_MUNICIPIO", "NM_LOCAL_VOTACAO", "DS_LOCAL_VOTACAO_ENDERECO",
                 "NM_BAIRRO"], dropna=False)
      .agg(sections=("n", "size"), zero_opp=("votes_opp", lambda x: int((x == 0).sum())),
           zero_pt=("votes_pt", lambda x: int((x == 0).sum()))).reset_index())
write_csv(ch, "m5_classifier_changes_2026.csv", private=True)
tot = ch.groupby("change").agg(places=("sections", "size"), sections=("sections", "sum"),
                               zero_opp=("zero_opp", "sum"), zero_pt=("zero_pt", "sum")).reset_index()
write_csv(tot, "m5_classifier_changes_2026_totals.csv")
print(tot.to_string(index=False))
