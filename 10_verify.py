"""Step 10. Compare this run's outputs with the reference run.

checksums/results.sha256 holds the SHA-256 of every published table from the
reference run (Python 3.13.5, Linux x86_64, packages in requirements.lock).
This step reports, for each file: match, differs, or missing.

Floats are written with 10 significant digits, so a run with the same package
versions should match byte for byte. Another platform or other versions can still
change a last digit. If a file differs, compare it numerically with the published
copy before concluding anything.

Files that need the private analyst labels (m5_label_*, m5_classifier_agreement_*,
m5_precision_*, m5b_zero_sections_agreement*) are reported as skipped when those
labels were not available. The m5b_* tables depend on the outside registers too: with
newer registers (ZV_ACCEPT_NEW_REGISTERS=1) they can differ from the reference.

It also tests the privacy rule on every published file and fails if a file has a
section, polling-place or coordinate column, names a unit the rule forbids, or is a
municipal-level file that counts zero or near-unanimous sections.

  python 10_verify.py           check
  python 10_verify.py --write   rewrite the checksum file (reference run only)
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, INTERACTIVE, RES  # noqa: E402

SUMS = HERE / "checksums" / "results.sha256"
NEEDS_LABELS = ("m5_label_", "m5_classifier_agreement_", "m5_precision_", "m5b_zero_sections_agreement")


def published_files():
    files = [p for p in RES.glob("*.csv")] + [p for p in INTERACTIVE.glob("*") if p.suffix in (".csv", ".json", ".md")]
    return sorted(p.relative_to(HERE).as_posix() for p in files)


def digest(rel):
    return hashlib.sha256((HERE / rel).read_bytes()).hexdigest()


# A file is municipal-level if it has one of these columns. Such a file must not count
# zero, unanimous or near-unanimous sections: a small municipality's count can point at
# a single community.
MUNICIPAL_COLS = {"municipality", "municipality_code_tse", "cd_municipio", "nm_municipio"}
ZERO_COUNT_WORDS = ("zero", "unanim", "or_fewer", "near")

# Column names that would identify a section, a polling place or a location.
FORBIDDEN = {"nr_secao", "section", "nr_local_votacao", "nm_local_votacao", "polling_place",
             "ds_local_votacao_endereco", "address", "nm_bairro", "nr_latitude", "nr_longitude",
             "latitude", "longitude", "coordinates"}


def privacy_problems():
    """Every way a published file breaks the privacy rule. Empty list means it holds."""
    bad = []
    for rel in published_files():
        path = HERE / rel
        if path.suffix == ".csv":
            cols = pd.read_csv(path, comment="#", nrows=0).columns
            bad += [f"{rel}: column {c}" for c in cols if c.lower() in FORBIDDEN]
            if MUNICIPAL_COLS & {c.lower() for c in cols}:
                bad += [f"{rel}: municipal-level file with zero or unanimous count column {c}"
                        for c in cols if any(w in c.lower() for w in ZERO_COUNT_WORDS)]
        elif path.suffix == ".json":
            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k.lower() in FORBIDDEN:
                            bad.append(f"{rel}: key {k}")
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(json.loads(path.read_text()))
    mun = pd.read_csv(INTERACTIVE / "municipal_2026_2t.csv", comment="#")
    named = mun[mun.units_pooled == 1]
    small = named[(named.eligible_voters < 50) | (named.votes_lula == 0) | (named.votes_flavio == 0)]
    bad += [f"municipal_2026_2t.csv: named unit breaks the size or unanimity rule: {r.municipality}"
            for r in small.itertuples()]
    pooled1 = mun[(mun.units_pooled == 1) & (mun.municipality == "other, pooled")]
    bad += [f"municipal_2026_2t.csv: a pooled row holds one unit ({r.state})" for r in pooled1.itertuples()]
    cat = pd.read_csv(INTERACTIVE / "zero_sections_by_category.csv", comment="#")
    bad += [f"zero_sections_by_category.csv: scope below national ({s})" for s in cat.scope.unique()
            if s != "Brazil and abroad"]
    bad += [f"zero_sections_by_category.csv: unsuppressed cell under 10 ({r.place_category})"
            for r in cat[~cat.suppressed].itertuples() if r.sections < 10]
    return bad


if "--write" in sys.argv:
    assert not privacy_problems(), privacy_problems()
    SUMS.parent.mkdir(exist_ok=True)
    SUMS.write_text("".join(f"{digest(r)}  {r}\n" for r in published_files()))
    print(f"wrote {SUMS.relative_to(HERE)} with {len(published_files())} files")
    sys.exit(0)

if not SUMS.exists():
    sys.exit(f"no reference checksums at {SUMS.relative_to(HERE)}")
expected = dict(reversed(line.split("  ", 1)) for line in SUMS.read_text().splitlines() if line)
counts = {"match": 0, "differs": 0, "missing": 0, "skipped": 0}
for rel, want in sorted(expected.items()):
    path = HERE / rel
    if not path.exists():
        status = "skipped" if Path(rel).name.startswith(NEEDS_LABELS) else "missing"
    else:
        status = "match" if digest(rel) == want else "differs"
    counts[status] += 1
    if status != "match":
        print(f"{status:8} {rel}")
extra = sorted(set(published_files()) - set(expected))
for rel in extra:
    print(f"{'new':8} {rel}")
print(", ".join(f"{k}: {v}" for k, v in counts.items()) + f", not in reference: {len(extra)}")
problems = privacy_problems()
for p in problems:
    print(f"PRIVACY  {p}")
print(f"privacy rule: {'holds' if not problems else f'{len(problems)} problems'}")
sys.exit(1 if counts["differs"] or counts["missing"] or problems else 0)
