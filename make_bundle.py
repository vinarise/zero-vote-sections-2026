"""BUNDLE.sha256 and the dataset manifest dataset.json.

  python make_bundle.py --write   seal the reference run (writes the two files)
  python make_bundle.py --check   compare this folder with BUNDLE.sha256 (the default)

BUNDLE.sha256 lists every sealed file of the package with its SHA-256, in the format of
sha256sum, sorted by path. The bundle hash is the SHA-256 of BUNDLE.sha256 itself. Every
sealed file is published, the executed notebook included: it prints no path of the
machine that ran it, and check_notebook.py asserts that.

dataset.json describes the published data files (dataset.schema.json of the site's spec):
each file's path, media type, size, SHA-256 and columns.

--check names three kinds of difference. A file that records a run (the ledger, the
executed notebook, FINDINGS.md, environment.md, dataset.json) differs after every new run,
as expected.
A table built from an input this run did not have (the private analyst labels, the two
IBGE map files) is reported as skipped, not missing. Any other file that differs or is
missing, code or table, fails the check.
"""
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from zvnb.inputs import input_table, sha256  # noqa: E402

TOP = ["EXPERIMENT.md", "EXTERNAL-CHECK-PLAN.md", "FINDINGS.md", "REPRODUCE.md", "LICENSE.md", "environment.md",
       "results.csv", "zero_vote_sections.ipynb", "zero_vote_sections.executed.ipynb", "run_all.sh",
       "requirements.lock", "requirements-notebook.lock", ".python-version", "sources.lock.tsv", "inputs.extra.tsv",
       "sources.freshness-2026-11-01.tsv", "piece_numbers.tsv", "build_notebook.py", "make_findings.py",
       "make_bundle.py", "check_notebook.py", "common.py", "dataset.json"]
# Files that a rerun on the same platform rebuilds byte for byte.
DETERMINISTIC = ("results/", "interactive/", "finding/")
# Files that record a run: every new run rewrites them.
RECORDS = {"results.csv", "zero_vote_sections.executed.ipynb", "FINDINGS.md", "environment.md", "dataset.json"}
# The tables stage 9 and stage 11 build from the private analyst labels (the list of 10_verify.py).
NEEDS_LABELS = ("m5_label_", "m5_classifier_agreement_", "m5_precision_", "m5b_zero_sections_agreement")
MEDIA = {".csv": "text/csv", ".json": "application/json", ".md": "text/markdown", ".ipynb": "application/x-ipynb+json",
         ".py": "text/x-python", ".sh": "text/plain", ".tsv": "text/plain", ".lock": "text/plain", ".sha256": "text/plain"}


def sealed_files():
    files = [p for p in TOP if (HERE / p).exists()]
    for g in ("0*.py", "1*.py", "zvnb/*.py", "checksums/results.sha256", "results/*.csv", "interactive/*",
              "finding/*.json"):
        files += [p.relative_to(HERE).as_posix() for p in HERE.glob(g) if p.is_file()]
    return sorted(set(files))


def field_type(values):
    vals = [v for v in values if v != ""]
    for t, test in (("integer", int), ("number", float)):
        try:
            for v in vals:
                test(v)
            return t
        except ValueError:
            pass
    if vals and all(v in ("True", "False", "true", "false") for v in vals):
        return "boolean"
    return "string"


def table_schema(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(ln for ln in fh if not ln.startswith("#")))
    head, body = rows[0], rows[1:]
    return {"fields": [{"name": h, "type": field_type([r[i] for r in body if i < len(r)])} for i, h in enumerate(head)]}


def dataset(files):
    data = [p for p in files if p.startswith(DETERMINISTIC) or p == "results.csv"]
    entries = []
    for p in data:
        e = {"path": p, "media_type": MEDIA.get(Path(p).suffix, "text/plain"), "bytes": (HERE / p).stat().st_size,
             "sha256": sha256(HERE / p)}
        if e["media_type"] == "text/csv":
            e["table_schema"] = table_schema(HERE / p)
        entries.append(e)
    manifest = "".join(f"{e['sha256']}  {e['path']}\n" for e in sorted(entries, key=lambda e: e["path"]))
    return {
        "id": "ds_2026_br-zero-vote-sections",
        "version": "3.1.0",
        "title": {"en": "Zero-vote sections in Brazil's presidential runoffs, 2018, 2022 and 2026"},
        "description": {"en": "Counts of sections where a runoff candidate had no votes, model expectations, consistency "
                              "checks and register categories, at national, regional and state level, with the "
                              "research ledger they come from. No section, polling place or community is named."},
        "license": "CC-BY-4.0",
        "published_at": "2026-11-01T00:00:00Z",
        "temporal_coverage": "2018-10-28/2026-10-25",
        "spatial_coverage": "Brazil and voters abroad",
        "keywords": ["elections", "Brazil", "runoff", "zero-vote sections", "open data"],
        "files": entries,
        "manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
        "provenance": {"method_en": "Built by zero_vote_sections.ipynb, executed top to bottom by run_all.sh, from the "
                                    "TSE open-data files pinned in sources.lock.tsv. Every number is a row of results.csv. "
                                    "Derived from data of the Tribunal Superior Eleitoral (CC BY 4.0)."},
    }


def absent_inputs():
    """The optional kinds of input this run did not have: 'label', 'map' or both."""
    data = Path(os.environ.get("ZV_DATA_DIR", HERE / "data"))
    rows = input_table(HERE, data)
    return {k for k in ("label", "map") if not all(r["path"].exists() for r in rows if r["kind"] == k)}


def skipped_because(p, absent):
    if "label" in absent and p.startswith("results/") and Path(p).name.startswith(NEEDS_LABELS):
        return "the private analyst labels"
    if "map" in absent and p.startswith("finding/"):
        return "the two IBGE map inputs"
    return None


def main():
    write = "--write" in sys.argv
    if write:
        (HERE / "dataset.json").write_text(json.dumps(dataset(sealed_files()), indent=1, ensure_ascii=False) + "\n")
        files = sealed_files()
        (HERE / "BUNDLE.sha256").write_text("".join(f"{sha256(HERE / p)}  {p}\n" for p in files))
        print(f"BUNDLE.sha256: {len(files)} sealed files, bundle hash {sha256(HERE / 'BUNDLE.sha256')}")
        return 0
    if not (HERE / "BUNDLE.sha256").exists():
        print("no BUNDLE.sha256 yet: this is the reference run, seal it with make_bundle.py --write")
        return 0
    absent = absent_inputs()
    lines = [ln.split("  ", 1) for ln in (HERE / "BUNDLE.sha256").read_text().splitlines() if ln]
    same, diff, gone, skipped = [], [], [], []
    for h, p in lines:
        why = skipped_because(p, absent)
        # A file whose input this run lacked is skipped only when it is missing. Present, it is compared.
        if why and not (HERE / p).exists():
            skipped.append((p, why))
        elif not (HERE / p).exists():
            gone.append(p)
        elif sha256(HERE / p) == h:
            same.append(p)
        else:
            diff.append(p)
    bad_diff = [p for p in diff if p not in RECORDS]
    print(f"bundle {sha256(HERE / 'BUNDLE.sha256')}: {len(same)} files match, {len(diff)} differ, "
          f"{len(gone)} missing, {len(skipped)} skipped")
    for p in diff:
        print(f"  differs  {p}{'  (expected after a new run: it records the run)' if p in RECORDS else ''}")
    for p in gone:
        print(f"  missing  {p}")
    for p, why in skipped:
        print(f"  skipped  {p}  (input absent: {why})")
    return 1 if bad_diff or gone else 0


if __name__ == "__main__":
    sys.exit(main())
