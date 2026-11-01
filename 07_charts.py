"""Step 7. Chart: observed vs expected zero sections, by year and side (round 2, n >= 1)."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RES  # noqa: E402

oe = pd.read_csv(RES / "observed_vs_expected.csv")
oe = oe[(oe.event == "zero") & (oe.min_valid_votes == 1)]

SERIES = [("observed", "Observed", "#2a78d6"),
          ("BB-place", "Expected, BB-place (polling-place mean)", "#eb6834"),
          ("BB-mun", "Expected, BB-mun (municipality mean)", "#1baf7a"),
          ("EB-r1", "Expected, EB-r1 (same section, round 1; added after results)", "#8a5cc2")]
INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3de"
YEARS = [2018, 2022, 2026]
PANELS = [("opp", "Zero votes for the non-PT candidate\n(Bolsonaro 2018, 2022; Flávio Bolsonaro 2026)"),
          ("pt", "Zero votes for the PT candidate\n(Haddad 2018; Lula 2022, 2026)")]

plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), sharey=True)
w = 0.2
for ax, (side, title) in zip(axes, PANELS):
    g = oe[oe.side == side]
    x = np.arange(len(YEARS))
    for j, (key, label, color) in enumerate(SERIES):
        if key == "observed":
            vals = [g[(g.year == y) & (g.model == "BB-mun")].observed.iloc[0] for y in YEARS]
        else:
            vals = [g[(g.year == y) & (g.model == key)].expected.iloc[0] for y in YEARS]
        pos = x + (j - 1.5) * w
        ax.bar(pos, vals, width=w - 0.03, color=color, label=label, zorder=3)
        for p, v in zip(pos, vals):
            ax.text(p, max(v, 0.1) * 1.12, f"{v:.0f}" if key == "observed" else (f"{v:.2f}" if v < 1 else f"{v:.1f}"),
                    ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_yscale("log")
    ax.set_ylim(0.1, 1000)
    ax.set_xticks(x, [str(y) for y in YEARS])
    ax.set_title(title, fontsize=10, loc="left", color=INK)
    ax.grid(axis="y", color=GRID, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
axes[0].set_ylabel("Sections with zero votes (log scale)")
handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.06), ncol=2, frameon=False, fontsize=8.5)
fig.suptitle("Presidential runoff sections with zero votes for one candidate: observed vs expected",
             x=0.01, ha="left", fontsize=11, color=INK)
fig.text(0.01, 0.005, "Source: TSE open data, votes by section, round 2. Sections with at least "
         "one valid vote. Expected = sum over sections of the model probability of zero.\n"
         "A matching total does not mean the model finds the zero sections (FINDINGS-v2.md, M1).",
         fontsize=7.5, color=MUTED)
fig.tight_layout(rect=(0, 0.17, 1, 0.95))
fig.savefig(RES / "chart_observed_vs_expected_zeros.png", dpi=160, facecolor="white",
            metadata={"Software": None})
print("saved")
