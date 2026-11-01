"""Writes zero_vote_sections.ipynb, the unexecuted notebook, from the cells below.

  python build_notebook.py

The notebook is the record: run_all.sh executes it top to bottom with nbconvert and
writes zero_vote_sections.executed.ipynb. Editing a cell here and rebuilding changes
the harness identity, which every ledger row carries.
"""
import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

CELLS = []


def md(s):
    CELLS.append(new_markdown_cell(s.strip("\n")))


def code(s):
    CELLS.append(new_code_cell(s.strip("\n")))


md(r"""
# Zero-vote sections in Brazil's presidential runoffs, 2018, 2022 and 2026

This notebook is the research record of the zero-vote Lab. It runs the published analysis
code stage by stage, unchanged, computes the model arms itself with that code's functions and
asserts them equal to the stage tables, and turns every number into a row of the append-only
ledger `results.csv`. `FINDINGS.md` is generated from that ledger by
`make_findings.py`. No number is typed by hand.

The order follows the house skeleton: environment probe, pre-flight checks of every input,
the config with a strict schema, data loading, known-answer tests, one `run_arm()` that
writes its ledger row at once, the baseline, the arms, tables with intervals, the decision
against the rules registered in `EXPERIMENT.md`, and a closing re-check of the config.

The questions, models and rules were written in `EXPERIMENT.md` on 29 October 2026. The text
was not frozen before the first model run. Its earliest commitment is a signed commit of the
same day, after the first results. The section "Status of this registration" says so, and lists
every deviation with its date.

Privacy. The run reads files that list single sections and polling places. Those stay in the
private data folder. Nothing in this notebook's output names a section, a polling place or a
community, and no count of zero sections is shown below the level of a state.
""")

md("## 1. Imports and environment probe")
code(r"""
import hashlib, importlib.metadata as md, importlib.util, json, os, platform, re, shutil, sys, tempfile, time
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()
PKG = Path.cwd().resolve()
DATA = Path(os.environ.get("ZV_DATA_DIR", PKG / "data")).resolve()
sys.path.insert(0, str(PKG))
from zvnb import config as C, finding as F, inputs as I, ledger as L, stages as ST, stats as S

WANT_PY = (PKG / ".python-version").read_text().strip()
assert platform.python_version() == WANT_PY, f"Python {platform.python_version()}, the record needs {WANT_PY}"
assert sys.prefix != sys.base_prefix, "run inside the package's virtual environment"


def pins(path):
    out = {}
    for line in (PKG / path).read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if m:
            out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


PINS = {**pins("requirements.lock"), **pins("requirements-notebook.lock")}
INSTALLED = {d.metadata["Name"].lower().replace("_", "-"): d.version for d in md.distributions()}
wrong = {n: (v, INSTALLED.get(n)) for n, v in PINS.items() if INSTALLED.get(n) != v}
extra = sorted(set(INSTALLED) - set(PINS) - {"pip"})
assert not wrong, f"installed versions differ from the locks: {wrong}"
assert not extra, f"packages installed that no lock pins: {extra}"


def first(path, key):
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith(key):
                return line.split(":", 1)[1].strip() if ":" in line else line.split("=", 1)[1].strip().strip('"')
    except OSError:
        return "unknown"
    return "unknown"


ENV = {
    "python": platform.python_version(),
    "implementation": platform.python_implementation(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "cpu": first("/proc/cpuinfo", "model name"),
    "logical_cpus": os.cpu_count(),
    "memory_total": first("/proc/meminfo", "MemTotal"),
    "os": first("/etc/os-release", "PRETTY_NAME"),
    "packages": dict(sorted(INSTALLED.items())),
}
ENVIRONMENT_SHA256 = hashlib.sha256(json.dumps(
    {k: ENV[k] for k in ("python", "implementation", "machine", "packages")}, sort_keys=True).encode()).hexdigest()
for k in ("python", "platform", "cpu", "logical_cpus", "memory_total", "os"):
    print(f"{k:13} {ENV[k]}")
print(f"packages      {len(PINS)} pinned, every one at its locked version, and pip {INSTALLED.get('pip')}")
print(f"environment   {ENVIRONMENT_SHA256}")
# The data folder's path is never printed: it belongs to the machine, not to the record.
print(f"data folder   {'set by ZV_DATA_DIR' if 'ZV_DATA_DIR' in os.environ else './data'}")
""")

md("""
## 2. Pre-flight: every input present, with its locked size and SHA-256

`sources.lock.tsv` pins the 79 public files of the reference download of 29 October 2026
(TSE results, the IBGE municipal mesh, and the outside registers of IBGE, FUNAI and INCRA).
`inputs.extra.tsv` pins four more: the two private analyst-label files, and the two IBGE files
the map data are drawn from. A missing file or a different hash stops the run here, with one
exception. When a source has republished a public file, the flags of `01_download.py`
(`ZV_ALLOW_CHANGED_SOURCES=1` for the TSE, `ZV_ACCEPT_NEW_REGISTERS=1` for the registers) let the
run go on with the new version. The file is then listed as changed, and every ledger row carries
an inputs identity that differs from the reference.
""")
code(r"""
INPUT_ROWS, INPUTS_SHA256 = I.preflight(PKG, DATA, os.environ)
HARNESS_FILES, HARNESS_SHA256 = I.harness(PKG)
by_kind = pd.Series([r["kind"] for r in INPUT_ROWS]).value_counts().sort_index()
print(by_kind.to_string())
LABELS = all(r["present"] for r in INPUT_ROWS if r["kind"] == "label")
MAP_INPUTS = all(r["present"] for r in INPUT_ROWS if r["kind"] == "map")
absent = [f"{r['kind']}/{r['file']}" for r in INPUT_ROWS if not r["present"]]
print(f"{len(INPUT_ROWS) - len(absent)} inputs present, every size and SHA-256 as locked")
print(f"absent (optional): {absent or 'none'}")
CHANGED = [f"{r['kind']}/{r['file']}" for r in INPUT_ROWS if r["changed"]]
print(f"changed since the lock, accepted by flag: {CHANGED or 'none'}")
print(f"inputs manifest {INPUTS_SHA256}")
print(f"harness         {HARNESS_SHA256} over {len(HARNESS_FILES)} code and lock files")
""")

md("""
### environment.md

Written from the probe and the input table, so it cannot drift from what ran. It names the
hardware and the operating system, never the machine or a path.
""")
code(r"""
def write_environment():
    lines = ["# Environment of the reference run", "",
             "Generated by `zero_vote_sections.ipynb`, section 2, from the environment probe and the pre-flight table.",
             "", "## Machine", "",
             f"- CPU: {ENV['cpu']}, {ENV['logical_cpus']} logical CPUs. No GPU is used.",
             f"- Memory: {ENV['memory_total']}.",
             f"- Operating system: {ENV['os']}, {ENV['platform']}.",
             f"- Python: {ENV['implementation']} {ENV['python']}.", "",
             "## Identities", "",
             f"- Environment SHA-256 (Python version, implementation, architecture and every installed package): `{ENVIRONMENT_SHA256}`",
             f"- Inputs SHA-256 (the sorted list of every input's SHA-256): `{INPUTS_SHA256}`",
             f"- Harness SHA-256 (the sorted list of every code and lock file's SHA-256): `{HARNESS_SHA256}`",
             "- Harness commit: the commit of the public repository that holds this file. A file cannot name the "
             "commit that contains it, so the Lab block of the published piece records it. The harness SHA-256 "
             "above identifies the code.", "",
             "## Libraries", "",
             "Every installed package, each pinned with its PyPI SHA-256 in `requirements.lock` (the analysis) "
             "or `requirements-notebook.lock` (the notebook runner).", "",
             "| Package | Version |", "|---|---|"]
    lines += [f"| {n} | {v} |" for n, v in ENV["packages"].items()]
    lines += ["", "## Code and lock files", "", "| File | SHA-256 |", "|---|---|"]
    lines += [f"| `{p}` | `{h}` |" for p, h in HARNESS_FILES]
    lines += ["", "## Inputs", "",
              "Kinds: `tse` TSE open data, `ibge_api` the IBGE municipal mesh, `register` the outside registers "
              "(IBGE, FUNAI, INCRA), `label` the private analyst labels (not published), `map` the IBGE files "
              "the map data are drawn from.", "",
              "| Kind | File | Bytes | SHA-256 | URL |", "|---|---|---:|---|---|"]
    for r in sorted(INPUT_ROWS, key=lambda r: (r["kind"], r["file"])):
        lines.append(f"| {r['kind']} | `{r['file']}` | {r['bytes']:,} | `{r['sha256']}` | {r['url'] or 'private'} |"
                     + ("" if r["present"] else " absent from this run")
                     + (f" changed: this run read {r['observed_bytes']:,} bytes, `{r['observed_sha256']}`"
                        if r["changed"] else ""))
    (PKG / "environment.md").write_text("\n".join(lines) + "\n")
    print(f"environment.md: {len(lines)} lines")


write_environment()
""")

md("""
## 3. Config, with a strict schema

Every setting that changes a number. The frozen constants of `EXPERIMENT.md` (the U1 to U3
thresholds) and of the code (`common.py`, `04_models.py`) are listed here and asserted equal
to the code, so the config cannot describe a run the code did not do. An unknown key is an error.
""")
code(r"""
CONFIG = {
    "years": [2018, 2022, 2026],
    "sides": ["pt", "opp"],
    "ballot": {"2026": {"pt": 13, "opp": 22}, "2022": {"pt": 13, "opp": 22}, "2018": {"pt": 13, "opp": 17}},
    "seed": 20261029,
    "min_valid_votes": [1, 10, 50],
    "events": ["zero", "share_lt_1pct", "votes_le_2"],
    "models": ["B-mun", "B-place", "BB-mun", "BB-place", "BB-place (v1 code)", "EB-place", "EB-r1"],
    "models_preregistered": ["B-mun", "B-place", "BB-mun", "BB-place"],
    "wilson_z": S.Z95,
    "u1_quantile": 0.999,
    "u2_factor": 1.5,
    "u3_r1_share": 0.10,
    "u3_ratio": 2.0,
    "u3_min_sections": 5,
    "python_version": WANT_PY,
    "stages": ["02_load.py", "03_build.py", "04_models.py", "05_consistency.py", "11_external_check.py",
               "06_diagnostics.py", "08_interactive.py", "09_classifier_check.py", "10_verify.py"],
    "stages_not_run": {
        "01_download.py": "every input is already on disk with its locked hash (section 2). run_all.sh runs it only when an input is missing.",
        "07_charts.py": "it draws a PNG chart only, which no number depends on. The site draws the charts from the ledger.",
    },
    "reference_checksums": "checksums/results.sha256",
    "ledger": "results.csv",
    "finding_dir": "finding",
}
C.validate(CONFIG)
try:
    C.validate({**CONFIG, "typo_key": 1})
    raise AssertionError("an unknown key was accepted")
except KeyError:
    pass

# The config must describe the code, not a run the code did not do.
spec = importlib.util.spec_from_file_location("common", PKG / "common.py")
common = importlib.util.module_from_spec(spec); spec.loader.exec_module(common)
spec = importlib.util.spec_from_file_location("m04", PKG / "04_models.py")
m04 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m04)
assert tuple(CONFIG["years"]) == tuple(sorted(common.YEARS))
assert tuple(CONFIG["sides"]) == common.SIDES and CONFIG["seed"] == common.SEED
assert {int(y): v for y, v in CONFIG["ballot"].items()} == common.BALLOT
assert CONFIG["models"] == [m[0] for m in m04.MODELS] and CONFIG["models_preregistered"] == m04.PREREG
assert tuple(CONFIG["events"]) == m04.EVENTS and tuple(CONFIG["min_valid_votes"]) == m04.MINS
CONFIG_SHA256 = C.digest(CONFIG)
print(f"config {CONFIG_SHA256}")
""")

md("""
## 4. Data loading

A clean start, as in the v2 package: every intermediate and output table is removed and rebuilt.
The raw files and the private labels are kept. Stage 2 reads the TSE zips into Parquet and stage 3
builds one table per section and round, with the place flags. Both read only files whose hashes
section 2 asserted.
""")
code(r"""
for d in (DATA / "derived", PKG / "results", PKG / "interactive", PKG / CONFIG["finding_dir"], DATA / "logs"):
    shutil.rmtree(d, ignore_errors=True)
for f in (DATA / "private").glob("*.csv"):
    f.unlink()
shutil.rmtree(DATA / "private" / "external_check", ignore_errors=True)
(PKG / "results").mkdir()

ST.run_stage("02_load.py", PKG, DATA);
ST.run_stage("03_build.py", PKG, DATA);

COLS = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "region", "n", "votes_pt", "votes_opp"]
SEC = {y: pd.read_parquet(DATA / "derived" / f"sections_{y}_r2.parquet", columns=COLS) for y in CONFIG["years"]}
for y, s in SEC.items():
    assert s[["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]].duplicated().sum() == 0
    assert (s.n == s.votes_pt + s.votes_opp).all()
    print(f"{y}: {len(s):,} sections, {int((s.n >= 1).sum()):,} with a valid vote")
""")

md("""
## 5. Known-answer tests

Small synthetic tables where every answer is known by hand. They test the notebook's own
counting and intervals, the model functions of `04_models.py` that the expectations come from,
the ledger, and the map files' contract checks. They must all pass before any arm runs.
""")
code(r"""
KAT = []


def kat(name, got, want, tol=0.0):
    ok = (abs(got - want) <= tol) if isinstance(want, float) else (got == want)
    KAT.append((name, ok))
    assert ok, f"known-answer test failed: {name}: got {got!r}, want {want!r}"


def zero_count(s, side, min_n=1):
    # Sections with at least min_n valid votes where `side` had none, and the other side's votes there.
    other = "votes_opp" if side == "pt" else "votes_pt"
    z = s[(s.n >= max(min_n, 1)) & (s[f"votes_{side}"] == 0)]
    return len(z), int(z[other].sum()), int((s.n >= max(min_n, 1)).sum())


# 1. Counting. Seven sections: one with no valid vote (a zero for neither side), two zeros for opp, one for pt.
toy = pd.DataFrame({"votes_pt": [0, 5, 12, 0, 3, 40, 7], "votes_opp": [0, 0, 0, 9, 3, 2, 60]})
toy["n"] = toy.votes_pt + toy.votes_opp
kat("zero sections, opp, n>=1", zero_count(toy, "opp")[:2], (2, 17))
kat("zero sections, pt, n>=1", zero_count(toy, "pt")[:2], (1, 9))
kat("sections with a valid vote", zero_count(toy, "pt")[2], 6)
kat("zero sections, opp, n>=10", zero_count(toy, "opp", 10)[:2], (1, 12))
kat("v2 observed() agrees, opp", int(m04.observed(toy, "opp")["zero"].sum()), 2)
kat("v2 observed() agrees, pt", int(m04.observed(toy, "pt")["zero"].sum()), 1)
kat("v2 observed() share under 1%", int(m04.observed(toy, "opp")["share_lt_1pct"].sum()), 2)

# 2. Wilson 95% intervals, against values computed by hand from the closed form.
lo, hi = S.wilson(5, 10); kat("Wilson 5/10 low", round(lo, 4), 0.2366); kat("Wilson 5/10 high", round(hi, 4), 0.7634)
lo, hi = S.wilson(0, 10); kat("Wilson 0/10 low", lo, 0.0); kat("Wilson 0/10 high", round(hi, 4), 0.2775)
lo, hi = S.wilson(10, 10); kat("Wilson 10/10 high", hi, 1.0); kat("Wilson 10/10 low", round(lo, 4), 0.7225)

# 3. The model functions the expectations come from.
q0, _, q2 = m04.probs_binom(np.array([3]), np.array([0.5]))
kat("binomial P(0 of 3 at p=0.5)", float(q0[0]), 0.125, 1e-15)
kat("binomial P(at most 2 of 3 at p=0.5)", float(q2[0]), 0.875, 1e-15)
q0, _, _ = m04.probs_bb(np.array([3]), np.array([1.0]), np.array([1.0]))
kat("beta-binomial P(0 of 3), Beta(1,1)", float(q0[0]), 0.25, 1e-12)
q999, pge = m04.poisson_binomial(np.array([0.5, 0.5]), 2, 1.0, np.sqrt(0.5))
kat("Poisson-binomial P(X>=2), two fair coins", pge, 0.25, 1e-15)
kat("Poisson-binomial 99.9% quantile, two fair coins", q999, 2)
t = pd.DataFrame({"g": [1, 1, 1, 2], "votes_pt": [1, 3, 0, 5], "n": [2, 4, 4, 5]})
share, _, den = m04.loo_share(t, ["g"], "votes_pt")
kat("leave-one-out share, first section", float(share[0]), 3 / 8, 1e-15)
kat("leave-one-out share, alone in its group", bool(np.isnan(share[3])), True)

# 4. The ledger refuses an unknown column and a repeated arm, and chains supersedes across runs.
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "l.csv")
    base = dict(measure="kat", run_class="known-answer", prereg_status="not applicable", status="ok")
    a = L.Ledger(p, {"run_id": "a"}); a.append({**base, "k": 1})
    for bad in ({**base, "nonsense": 1}, base):
        try:
            a.append(bad); kat("ledger refuses " + str(sorted(set(bad) - set(base)) or "a repeat"), False, True)
        except (KeyError, ValueError):
            kat("ledger refuses " + str(sorted(set(bad) - set(base)) or "a repeat"), True, True)
    b = L.Ledger(p, {"run_id": "b"}); b.append({**base, "k": 2})
    kat("a later run supersedes the earlier row", b.rows[-1]["supersedes"], "R00001")
    kat("current() keeps only the latest", [r["k"] for r in b.current()], ["2"])

# 5. The map files: numbers as JSON.stringify writes them, the collation, and the contract checks.
kat("js number 1e-6", F.js_number(1e-6), "0.000001")
kat("js number 1e-7", F.js_number(1e-7), "1e-7")
kat("js number 1.0", F.js_number(1.0), "1")
kat("js number 0.222628", F.js_number(0.222628), "0.222628")
kat("Portuguese order", sorted(["Aguaí", "Água Boa", "Abadia"], key=F.collate_key), ["Abadia", "Água Boa", "Aguaí"])
probe = {"zero_by_state.json": {"contract": F.CONTRACT, "years": []},
         "places_2026.json": {"contract": F.CONTRACT, "columns": ["ibge", "zeros"], "rows": [[1, "ZZ", "x", 1, 1, 1, 0.5, 0.5, None, None]]},
         "br_states.json": {"contract": F.CONTRACT, "viewBox": [10, 10], "states": {}}}
probs = F.check(probe)
kat("contract check refuses a zero column", any("forbidden column zeros" in x for x in probs), True)
kat("contract check refuses a unit abroad", any("unknown uf ZZ" in x for x in probs), True)

# 6. Pooled rows: a row of 08_interactive.py that pools units is never a municipality on the map,
#    abroad or inside a state, and the contract check refuses one that slips through.
with tempfile.TemporaryDirectory() as td:
    csv_path = os.path.join(td, "m.csv")
    Path(csv_path).write_text(
        "# a comment line, as in the published file\n"
        "state,municipality,municipality_code_tse,ibge_code,units_pooled,region,sections_with_valid_votes,"
        "eligible_voters,votes_cast,valid_votes,votes_lula,votes_flavio,share_lula,share_flavio\n"
        "RO,ALTA FLORESTA D'OESTE,1,1100015,1,North,10,1000,800,780,400,380,0.512821,0.487179\n"
        "RO,\"other, pooled\",,,3,North,5,300,200,190,190,0,1,0\n"
        "RO,\"other, pooled\",,,1,North,1,60,50,48,48,0,1,0\n"
        "RO,ANYWHERE,2,1100023,2,North,4,200,150,140,70,70,0.5,0.5\n")
    pl_kat, _ = F.places_2026(csv_path, {"1100015": ("Alta Floresta D'Oeste", (10.0, 20.0)),
                                         "1100023": ("Ariquemes", (11.0, 21.0))})
    kat("in-state pooled rows are dropped, by name or by units pooled", [r[2] for r in pl_kat["rows"]],
        ["Alta Floresta D'Oeste"])
probe["places_2026.json"]["columns"] = list(F.PLACE_COLUMNS)
probe["places_2026.json"]["rows"] = [[None, "SP", "other, pooled", 5, 300, 190, 1.0, 0.0, None, None]]
kat("contract check refuses a pooled row in a state", any("a pooled row in SP" in x for x in F.check(probe)), True)

# 7. A version 1 ledger gains the expectation column at the first append, and no earlier line changes.
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "v1.csv")
    v1 = {c: "" for c in L.COLUMNS_V1}
    v1.update(row_id="R00001", run_id="a", run_at="2026-11-01T00:00:00.000000Z", arm="measure=kat", measure="kat",
              run_class="known-answer", prereg_status="not applicable", status="ok", k="1")
    old_line = ",".join(v1[c] for c in L.COLUMNS_V1)
    Path(p).write_text(",".join(L.COLUMNS_V1) + "\n" + old_line + "\n")
    led = L.Ledger(p, {"run_id": "b"})
    led.append(dict(measure="kat", run_class="known-answer", prereg_status="not applicable", status="ok", k=2,
                    expectation_held="not applicable"))
    lines = Path(p).read_text().splitlines()
    kat("ledger v1 to v2: the header gains the column", lines[0], ",".join(L.COLUMNS))
    kat("ledger v1 to v2: the earlier line gains one empty cell, nothing else", lines[1], old_line + ",")
    kat("ledger v1 to v2: the new row supersedes the earlier one", led.rows[-1]["supersedes"], "R00001")

# 8. The stage output the notebook prints names no folder of this machine.
kat("stage output: folders masked, longest first", ST.mask("no labels at /a/b/data/x.csv, wrote /a/b/results", "/a/b", "/a/b/data"),
    "no labels at $ZV_DATA_DIR/x.csv, wrote ./results")

KAT_PASSED = sum(ok for _, ok in KAT)
print(f"known-answer tests: {KAT_PASSED} of {len(KAT)} passed")
""")

md("""
## 6. `run_arm()`, the only way a number enters the ledger

An arm is a call: `run_arm(measure, **factors)`. The measure's function computes the arm's
metrics from the tables the stages wrote in this run, and `run_arm` appends the row at once,
with the run's identity (inputs, harness, environment and config hashes) and the hash of the
table it read. A proportion always gets its n and a Wilson 95% interval. A measure that fails
writes a `failed` row and stops the notebook.
""")
code(r"""
RUN_ID = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(T0)) + "-" + CONFIG_SHA256[:8]
LEDGER = L.Ledger(PKG / CONFIG["ledger"], {
    "run_id": RUN_ID, "inputs_sha256": INPUTS_SHA256, "harness_sha256": HARNESS_SHA256,
    "environment_sha256": ENVIRONMENT_SHA256, "config_sha256": CONFIG_SHA256, "seed": CONFIG["seed"]})
MEASURES, TABLES = {}, {}


PRIVATE = "private: "


def table(rel):
    # A table this run wrote, read once, with its SHA-256 kept for the rows that use it. A private table
    # ("private: derived/...", in the data folder, never published) is only hashed: the row names it and
    # carries its hash, so the number is tied to the exact bytes it was counted from.
    if rel not in TABLES:
        if rel.startswith(PRIVATE):
            TABLES[rel] = (None, I.sha256(DATA / rel[len(PRIVATE):]))
        else:
            path = PKG / rel
            TABLES[rel] = (pd.read_csv(path, comment="#") if path.suffix == ".csv" else None, I.sha256(path))
    return TABLES[rel][0]


def measure(name, *, stage, table=None, run_class="main", prereg="pre-registered", interval=True):
    # interval=False: k and n are a tally of rules or tests, not a sample, so no share or interval is written.
    def deco(fn):
        MEASURES[name] = dict(fn=fn, stage=stage, table=table, run_class=run_class, prereg=prereg, interval=interval)
        return fn
    return deco


def run_arm(measure, note="", **factors):
    m = MEASURES[measure]
    src = m["table"].format(**factors) if m["table"] else ""
    base = dict(measure=measure, source_stage=m["stage"], source_table=src, note=note, **factors)
    try:
        out = dict(m["fn"](**factors))
    except Exception as e:
        LEDGER.append({**base, "run_class": m["run_class"], "prereg_status": m["prereg"], "status": "failed",
                       "note": f"{type(e).__name__}: {e}"[:300]})
        raise
    row = {**base, "run_class": out.pop("run_class", m["run_class"]),
           "prereg_status": out.pop("prereg_status", m["prereg"]), "status": "ok"}
    if "note" in out:
        row["note"] = ". ".join(x for x in (note, out.pop("note")) if x)
    if m["interval"] and out.get("k") is not None and out.get("n") and "share" not in out:
        out["share"] = out["k"] / out["n"]
        out["share_ci_low"], out["share_ci_high"] = S.wilson(out["k"], out["n"], CONFIG["wilson_z"])
        out["ci_method"] = ". ".join(x for x in ("share: Wilson score 95%", out.get("ci_method")) if x)
    row.update(out)
    if src:
        table(src)
        row["source_table_sha256"] = TABLES[src][1]
    return LEDGER.append(row)


@measure("kat", stage="notebook section 5", run_class="known-answer", prereg="not applicable", interval=False)
def _kat():
    return {"k": KAT_PASSED, "n": len(KAT), "n_label": "known-answer tests"}


run_arm("kat")
print(f"run {RUN_ID}, ledger {CONFIG['ledger']} now {len(LEDGER.rows)} rows")
""")

md("""
## 7. Baseline: the electorate of every runoff, counted from the section tables

Counted here from the section tables of stage 3, independently of the stage scripts. Every later
count is a part of these totals. The section tables list single sections, so they stay private:
each row names its table and carries the table's SHA-256. Section 8.1 asserts the same totals equal
to the published `results/scale.csv`.
""")
code(r"""
@measure("universe", stage="03_build.py", run_class="baseline", table=PRIVATE + "derived/sections_{year}_r2.parquet")
def _universe(year):
    s = SEC[year]
    return {"k": int((s.n >= 1).sum()), "n": len(s), "n_label": "sections in the section-detail file",
            "value": int(s.n.sum()), "value_unit": "valid votes for the two candidates"}


@measure("votes", stage="03_build.py", run_class="baseline", table=PRIVATE + "derived/sections_{year}_r2.parquet")
def _votes(year, side):
    s = SEC[year]
    return {"value": int(s[f"votes_{side}"].sum()), "value_unit": "votes", "n": len(s), "n_label": "sections"}


@measure("margin", stage="03_build.py", run_class="baseline", table=PRIVATE + "derived/sections_{year}_r2.parquet")
def _margin(year):
    s = SEC[year]
    return {"value": int(s.votes_pt.sum() - s.votes_opp.sum()), "value_unit": "votes, PT side minus PL side"}


for y in CONFIG["years"]:
    run_arm("universe", year=y)
    for side in CONFIG["sides"]:
        run_arm("votes", year=y, side=side)
    run_arm("margin", year=y)
""")

md("""
## 8. Questions 1 to 5: counts, models, U1 to U3 and scale (stage 4)
""")
code(r"""
ST.run_stage("04_models.py", PKG, DATA);
""")

md("""
### 8.1 Zero-vote sections by year, side and minimum size

Counted here from the section tables, then asserted equal to the stage-4 tables. A zero is a
section with at least one valid vote in which the side had none.
""")
code(r"""
@measure("zero_count", stage="03_build.py and 04_models.py", table="results/zero_counts_by_min_size_{year}.csv")
def _zero_count(year, side, min_valid_votes):
    k, other_votes, n = zero_count(SEC[year], side, min_valid_votes)
    t = table(f"results/zero_counts_by_min_size_{year}.csv").set_index("min_valid_votes").loc[min_valid_votes]
    other = "pt_votes_in_zero_opp" if side == "opp" else "opp_votes_in_zero_pt"
    assert (k, other_votes) == (int(t[f"zero_{side}"]), int(t[other])), (k, other_votes, t.to_dict())
    if min_valid_votes == 1:
        sc = table("results/scale.csv").set_index("year").loc[year]
        assert k == sc[f"zero_{side}_sections"] and other_votes == sc[f"zero_{side}_other_candidate_votes"]
        assert n == sc.sections_with_valid_votes
    return {"k": k, "n": n, "n_label": f"sections with at least {min_valid_votes} valid votes",
            "votes_other": other_votes}


for y in CONFIG["years"]:
    for side in CONFIG["sides"]:
        for mn in CONFIG["min_valid_votes"]:
            run_arm("zero_count", year=y, side=side, min_valid_votes=mn)

sc = table("results/scale.csv").set_index("year")
for y in CONFIG["years"]:
    assert SEC[y].votes_pt.sum() == sc.loc[y, "votes_pt"] and SEC[y].votes_opp.sum() == sc.loc[y, "votes_opp"]
    assert len(SEC[y]) == sc.loc[y, "sections_total"]
print("baseline totals and zero counts equal the stage-4 tables")
""")

md("### 8.2 Where the zeros are: by region")
code(r"""
@measure("zero_by_region", stage="03_build.py and 04_models.py", table="results/zero_by_region_{year}.csv")
def _zero_by_region(year, side, category):
    s = SEC[year]
    v = s[s.region == category]
    k = int(((v.n >= 1) & (v[f"votes_{side}"] == 0)).sum())
    t = table(f"results/zero_by_region_{year}.csv")
    want = t[(t.zero_for == side) & (t.region == category)].sections.sum()
    assert k == want, (year, side, category, k, want)
    return {"k": k, "n": int((v.n >= 1).sum()), "n_label": "sections with a valid vote in the region"}


REGIONS = ["North", "Northeast", "Center-West", "Southeast", "South", "Abroad"]
for y in CONFIG["years"]:
    assert set(SEC[y].region) <= set(REGIONS)
    for side in CONFIG["sides"]:
        for g in REGIONS:
            run_arm("zero_by_region", year=y, side=side, category=g)
""")

md("""
### 8.3 Scale: the votes in the zero sections against the national margin (U5)

U5 is plain arithmetic, registered as such, not a test.
""")
code(r"""
@measure("share_of_margin", stage="03_build.py and 04_models.py", table="results/scale.csv")
def _share_of_margin(year):
    s = SEC[year]
    margin = int(s.votes_pt.sum() - s.votes_opp.sum())
    a = zero_count(s, "opp")[1]
    want = table("results/scale.csv").set_index("year").loc[year, "pt_votes_in_opp_zero_sections_as_share_of_margin"]
    assert abs(a / abs(margin) - want) <= 1e-9 * want
    return {"value": a / abs(margin), "value_unit": "PT-side votes in PL-side zero sections, as a share of the margin",
            "votes_other": a}


for y in CONFIG["years"]:
    run_arm("share_of_margin", year=y)
""")

md("""
### 8.4 Observed against expected, every model, event and size, computed here

One arm per year, side, model, event and minimum size: 378 arms. Each arm is computed in this
notebook with the functions of `04_models.py`: the leave-one-out shares, the per-state dispersion
fits, each section's probability of the event under the model, the expected count and its standard
deviation, the registered normal 99.9% bound, and the exact Poisson-binomial 99.9% bound and tail.
For the zero event at one or more valid votes it also computes the model's log score and Brier sum
over all sections. Every result is then asserted equal to the row stage 4 wrote, as the ledger
writes numbers, to ten significant digits. Stage 4 stays as the oracle. The place-cluster bootstrap
interval of the ratio is read from stage 4's table: its resamples are stage 4's own computation.
""")
code(r"""
OE = table("results/observed_vs_expected.csv")
BOOT = table("results/ratio_bootstrap_places.csv").set_index(["year", "side", "model"]).sort_index()
SCORES = table("results/model_scores.csv").set_index(["year", "side", "model"]).sort_index()
MODEL_TAG = {name: tag for name, tag, _ in m04.MODELS}
CACHE = {}


def same(got, want):
    # Equal as the ledger and the stage tables write a number: ten significant digits.
    return L._fmt(float(got)) == L._fmt(float(want))


def model_inputs(year):
    # The per-section inputs every model of the year shares, built as 04_models.model_year builds them.
    if CACHE.get("year") == year:
        return CACHE["inputs"]
    CACHE.clear()
    s = pd.read_parquet(DATA / "derived" / f"sections_{year}_r2.parquet")
    r1 = pd.read_parquet(DATA / "derived" / f"sections_{year}_r1.parquet",
                         columns=common.KEY + ["votes_pt", "votes_opp", "QT_VOTOS_NOMINAIS"])
    r1 = r1.rename(columns={"votes_pt": "r1_pt", "votes_opp": "r1_opp", "QT_VOTOS_NOMINAIS": "r1_nominal"})
    r1["r1_n2"] = r1.r1_pt + r1.r1_opp
    v = m04.with_shares(s, r1)
    v = v[v.n >= 1].copy()
    clip = lambda x: np.clip(x, m04.CLIP, 1 - m04.CLIP)
    v["phi_mun"], v["phi_place"], v["phi_place_v1"] = np.nan, np.nan, np.nan
    for uf, idx in v.groupby("SG_UF").groups.items():
        g = v.loc[idx]
        phi = m04.fit_phi(g.votes_pt.to_numpy(), g.n.to_numpy(), clip(g.p_pt_mun.to_numpy()))
        gp = g[~g.place_fallback]
        v.loc[idx, "phi_mun"] = phi
        v.loc[idx, "phi_place"] = (m04.fit_phi(gp.votes_pt.to_numpy(), gp.n.to_numpy(), clip(gp.p_pt_place.to_numpy()))
                                   if len(gp) else phi)
        v.loc[idx, "phi_place_v1"] = m04.fit_phi(g.votes_pt.to_numpy(), g.n.to_numpy(), clip(g.p_pt_place.to_numpy()))
    fb = v.place_fallback.to_numpy()
    phi_mun = v.phi_mun.to_numpy()
    phi_place = np.where(fb, phi_mun, v.phi_place.to_numpy())
    mu_mun, mu_place = clip(v.p_pt_mun.to_numpy()), clip(v.p_pt_place.to_numpy())
    a0, b0 = mu_mun * phi_mun, (1 - mu_mun) * phi_mun
    xr = np.where(fb, 0, v.place_rest_pt.to_numpy())
    nr = np.where(fb, 0, v.place_rest_n.to_numpy())
    r1x = np.where(v.r1_missing, 0, v.r1_pt.fillna(0).to_numpy())
    r1n = np.where(v.r1_missing, 0, v.r1_n2.fillna(0).to_numpy())
    beta_pt = {"bbmun": (a0, b0),
               "bbplace": (mu_place * phi_place, (1 - mu_place) * phi_place),
               "bbplacev1": (mu_place * v.phi_place_v1.to_numpy(), (1 - mu_place) * v.phi_place_v1.to_numpy()),
               "ebplace": (a0 + xr, b0 + nr - xr),
               "ebr1": (a0 + r1x, b0 + r1n - r1x)}
    inputs = {"n": v.n.to_numpy(), "p_mun": v.p_pt_mun.to_numpy(), "p_place": v.p_pt_place.to_numpy(),
              "beta_pt": beta_pt, "observed": {side: {e: o.to_numpy() for e, o in m04.observed(v, side).items()}
                                               for side in CONFIG["sides"]}}
    CACHE.update(year=year, inputs=inputs)
    return inputs


def model_q(year, side, model):
    # Each section's probability of the three events for the side, under the model.
    key = ("q", side, model)
    if key not in CACHE:
        mi, tag = model_inputs(year), MODEL_TAG[model]
        if tag in ("bmun", "bplace"):
            p = mi["p_mun"] if tag == "bmun" else mi["p_place"]
            q = m04.probs_binom(mi["n"], p if side == "pt" else 1 - p)
        else:
            a, b = mi["beta_pt"][tag]
            q = m04.probs_bb(mi["n"], a, b) if side == "pt" else m04.probs_bb(mi["n"], b, a)
        CACHE[key] = dict(zip(m04.EVENTS, q))
    return CACHE[key]


def prereg_of(model):
    if model in CONFIG["models_preregistered"]:
        return "pre-registered"
    return "added after results"


@measure("observed_vs_expected", stage="notebook section 8.4, with the functions of 04_models.py",
         table="results/observed_vs_expected.csv")
def _oe(year, side, model, event, min_valid_votes):
    mi = model_inputs(year)
    q = model_q(year, side, model)[event]
    m = mi["n"] >= min_valid_votes
    qm = q[m]
    e = qm.sum()
    sd = np.sqrt((qm * (1 - qm)).sum())
    o = int(mi["observed"][side][event][m].sum())
    q999, p_ge = m04.poisson_binomial(qm, o, e, sd)
    upper_normal = e + m04.Z999 * sd
    ratio = o / e if e > 0 else np.nan
    r = OE[(OE.year == year) & (OE.side == side) & (OE.model == model) & (OE.event == event)
           & (OE.min_valid_votes == min_valid_votes)]
    assert len(r) == 1
    r = r.iloc[0]
    assert o == int(r.observed) and q999 == int(r.upper_99_9_exact), (o, r.observed, q999, r.upper_99_9_exact)
    assert bool(o > q999) == bool(r.u1_fires_exact) and bool(o > upper_normal) == bool(r.u1_fires_normal)
    for name, got, want in (("expected", e, r.expected), ("sd", sd, r.sd), ("tail", p_ge, r.p_exact_ge_observed),
                            ("normal bound", upper_normal, r.upper_99_9_normal), ("ratio", ratio, r.obs_over_exp)):
        assert same(got, want), (year, side, model, event, min_valid_votes, name, got, want)
    out = {"k": o, "n": int(m.sum()), "n_label": f"sections with at least {min_valid_votes} valid votes",
           "expected": float(e), "expected_sd": float(sd), "upper_99_9_exact": q999,
           "p_exact_ge_observed": float(p_ge), "u1_fires_exact": bool(o > q999), "ratio": float(ratio),
           "value": float(upper_normal), "value_unit": "U1 bound, normal approximation (as registered)",
           "prereg_status": prereg_of(model), "note": "computed in the notebook, equal to the stage 4 row"}
    if model == "BB-place (v1 code)":
        out["note"] += ". The v1 implementation of BB-place, kept to show the effect of the v2 fix"
    if event == "zero" and min_valid_votes == 1:
        y0 = mi["observed"][side]["zero"]
        qc = np.clip(q, m04.QFLOOR, 1 - m04.QFLOOR)
        log_score = float(np.sum(np.where(y0, np.log(qc), np.log1p(-qc))))
        brier = float(np.sum((q - y0) ** 2))
        b, sc = BOOT.loc[(year, side, model)], SCORES.loc[(year, side, model)]
        assert same(log_score, sc.log_score) and same(brier, sc.brier_sum), (log_score, sc.log_score, brier, sc.brier_sum)
        assert same(b.ratio, ratio)
        out.update(ratio_ci_low=float(b.ratio_lo95), ratio_ci_high=float(b.ratio_hi95),
                   ci_method="ratio: place-cluster bootstrap of stage 4, 1000 Poisson(1) weights per polling place",
                   log_score=log_score, brier=brier)
    return out


for y in CONFIG["years"]:
    for side in CONFIG["sides"]:
        for model in CONFIG["models"]:
            for ev in CONFIG["events"]:
                for mn in CONFIG["min_valid_votes"]:
                    run_arm("observed_vs_expected", year=y, side=side, model=model, event=ev, min_valid_votes=mn)
CACHE.clear()
print(f"{len(LEDGER.arms_this_run)} arms so far. All 378 model arms computed here equal stage 4's rows.")
""")

md("""
### 8.5 An independent check of one model

The simplest registered model, B-mun, recomputed here from the section tables alone: each
section's chance of a zero is (1 - p)^n, where p is the side's share in the rest of the
municipality (the rest of the state where the municipality has no other valid vote).
""")
code(r"""
@measure("bmun_recomputed", stage="notebook section 8.5", table="results/observed_vs_expected.csv", run_class="check")
def _bmun(year, side):
    s = SEC[year]
    v = s.copy()
    def loo(group):
        g = v.groupby(group)[["votes_pt", "n"]].transform("sum")
        num, den = g.votes_pt - v.votes_pt, g.n - v.n
        return np.where(den > 0, num / den.where(den > 0, 1), np.nan)
    p_pt = loo(["SG_UF", "CD_MUNICIPIO"])
    p_pt = np.where(np.isnan(p_pt), loo(["SG_UF"]), p_pt)
    keep = (v.n >= 1).to_numpy()
    p = p_pt[keep] if side == "pt" else 1 - p_pt[keep]
    e = float(np.power(1 - p, v.n.to_numpy()[keep]).sum())
    want = OE[(OE.year == year) & (OE.side == side) & (OE.model == "B-mun") & (OE.event == "zero")
              & (OE.min_valid_votes == 1)].expected.iloc[0]
    assert abs(e - want) <= 1e-8 * want, (e, want)
    return {"expected": e, "value": e - want, "value_unit": "recomputed minus stage 4"}


for y in CONFIG["years"]:
    for side in CONFIG["sides"]:
        run_arm("bmun_recomputed", year=y, side=side)
""")

md("""
### 8.6 Summaries the article reads: U1 per year and side, the best model, and where the expectation falls

The six models are the seven above without "BB-place (v1 code)". "Best" means the highest
Bernoulli log score over all sections, as deviation 9 defines it.
""")
code(r"""
SIX = [m for m in CONFIG["models"] if m != "BB-place (v1 code)"]


@measure("u1_models_exceeded", stage="04_models.py", table="results/observed_vs_expected.csv")
def _u1(year, side):
    r = OE[(OE.year == year) & (OE.side == side) & (OE.event == "zero") & (OE.min_valid_votes == 1) & OE.model.isin(SIX)]
    assert len(r) == 6
    return {"k": int(r.u1_fires_exact.sum()), "n": 6, "n_label": "models (the six), zero event, n>=1",
            "value": int(r.u1_fires_normal.sum()), "value_unit": "models whose normal U1 bound fires",
            "prereg_status": "pre-registered", "note": "k uses the exact tail of deviation 7"}


@measure("is_best_model", stage="04_models.py", table="results/model_scores.csv", prereg="added after results")
def _best(year, side, model):
    sc = SCORES.loc[(year, side)].loc[SIX]
    return {"k": int(sc.log_score[model] == sc.log_score.max()), "n": 1,
            "n_label": "1 when this model has the highest log score of the six", "log_score": float(sc.log_score[model]),
            "value": float(sc.log_score.max()), "value_unit": "highest log score of the six"}


DEC = table("results/m1_expectation_decomposition.csv")


@measure("expected_on_zero_sections", stage="04_models.py", table="results/m1_expectation_decomposition.csv",
         prereg="added after results")
def _decomp(year, side, model):
    d = DEC[(DEC.year == year) & (DEC.side == side) & (DEC.model == model)].set_index("group")
    return {"expected": float(d.loc["all sections", "expected_zeros"]),
            "value": float(d.loc["observed zero sections", "expected_zeros"]),
            "value_unit": "expected zeros that fall on the sections that were zero",
            "k": int(d.loc["observed zero sections", "observed_zeros"]), "n": int(d.loc["all sections", "sections"]),
            "n_label": "sections with a valid vote"}


for y in CONFIG["years"]:
    for side in CONFIG["sides"]:
        run_arm("u1_models_exceeded", year=y, side=side)
        for model in SIX:
            run_arm("is_best_model", year=y, side=side, model=model)
        for model in CONFIG["models"]:
            run_arm("expected_on_zero_sections", year=y, side=side, model=model)
""")

md("""
### 8.7 U2, the history rule

The 72 registered checks are 3 events by 3 sizes by 4 registered models by 2 sides. The pooled
rule compares 2026 with the range of the four baseline ratios. The per-side rule, added after
results (deviation 10), compares each side with its own 2018 and 2022.
""")
code(r"""
U2 = table("results/u2_history_check.csv")
assert len(U2) == 72


@measure("u2_fires", stage="04_models.py", table="results/u2_history_check.csv")
def _u2(scope, side):
    g = U2 if side == "both" else U2[U2.side == side]
    col = "u2_fires_pooled" if scope == "pooled" else "u2_fires_own_side_added_after_results"
    f = g[g[col].astype(bool)]
    return {"k": len(f), "n": len(g), "n_label": "registered U2 checks",
            "value": int(f.expected_2026_below_1.astype(bool).sum()),
            "value_unit": "of the checks that fire, those where the model expected under one zero in 2026",
            "prereg_status": "pre-registered" if scope == "pooled" else "added after results"}


for scope in ("pooled", "own side"):
    for side in ("both", "pt", "opp"):
        run_arm("u2_fires", scope=scope, side=side)
""")

md("""
### 8.8 Round 1 in the round-2 zero sections (the U3 input)

For each round-2 zero section, the same candidate's share of the valid votes in round 1 of the
same year, in the same section. The 10% threshold is registered (U3). The zero and under-5% counts
are descriptive.
""")
code(r"""
ZS = table("results/zero_sections_summary.csv")


@measure("round1_in_zero_sections", stage="04_models.py", table="results/zero_sections_summary.csv")
def _r1(year, side, category):
    r = ZS[(ZS.year == year) & (ZS.group == "zero sections") & (ZS.side == side)].iloc[0]
    return {"k": int(r[category]), "n": int(r.sections), "n_label": "round-2 zero sections of the side",
            "prereg_status": "pre-registered" if category == "r1_share_ge_10pct" else "added after results"}


for y in CONFIG["years"]:
    for side in CONFIG["sides"]:
        for cat in ("r1_share_zero", "r1_share_lt_5pct", "r1_share_ge_10pct"):
            run_arm("round1_in_zero_sections", year=y, side=side, category=cat)
""")

md("""
## 9. Question 6: consistency checks between the published files (stage 5, U4)
""")
code(r"""
ST.run_stage("05_consistency.py", PKG, DATA);
CS = table("results/consistency_summary.csv")


def cs(pattern):
    r = CS[CS.check.str.contains(pattern, regex=False)]
    assert len(r) == 1, pattern
    return r.iloc[0]


@measure("consistency", stage="05_consistency.py", table="results/consistency_summary.csv")
def _consistency(category, year=None):
    if category == "bulletin vs section, vote counts":
        n = int(cs("(section, votable) pairs compared").result)
        k = int(re.search(r"pairs that differ: (\d+)", cs("(section, votable) pairs compared").detail).group(1))
        return {"k": k, "n": n, "n_label": "(section, candidate) vote counts compared", "year": 2026}
    if category == "sum of sections vs published totals":
        r = cs(f"{year} R2 (municipality, zone, candidate) cells")
        n, k = map(int, re.match(r"(\d+) cells, (\d+) differ", r.result).groups())
        return {"k": k, "n": n, "n_label": "(municipality, zone, candidate) cells"}
    if category == "turnout above electorate":
        r = cs(f"{year} R2 sections with turnout > electorate")
        return {"k": int(r.result), "n": int(r.detail.split()[-1]), "n_label": "sections"}
    if category == "turnout not equal to valid, blank and null":
        k = int(cs(f"{year} R2 sections where turnout != valid + blank + null").result)
        return {"k": k, "n": len(SEC[year]), "n_label": "round-2 sections"}
    if category == "bulletin zip hash files":
        k, n = map(int, cs("bulletin zip SHA-512").result.split("/"))
        return {"k": k, "n": n, "n_label": "state bulletin files whose SHA-512 matches", "year": 2026}
    if category == "national report lines":
        k, n = map(int, re.match(r"(\d+)/(\d+)", cs("national report vs sum of sections").result).groups())
        return {"k": k, "n": n, "n_label": "national report lines that match", "year": 2026}
    raise KeyError(category)


for cat in ("bulletin vs section, vote counts", "bulletin zip hash files", "national report lines"):
    run_arm("consistency", category=cat)
for y in CONFIG["years"]:
    for cat in ("sum of sections vs published totals", "turnout above electorate", "turnout not equal to valid, blank and null"):
        run_arm("consistency", category=cat, year=y)

NR = table("results/consistency_checks_not_run.csv")


@measure("check_not_run", stage="05_consistency.py", table="results/consistency_checks_not_run.csv",
         prereg="not applicable")
def _not_run(category):
    reason = NR[NR.check.str.startswith("Signatures of the per-machine files")].reason.iloc[0]
    lo, hi = map(float, re.search(r"([\d.]+) to ([\d.]+) GB per state", reason).groups())
    return {"value": lo if category == "smallest state bundle" else hi, "value_unit": "GB",
            "note": "a size stated in 05_consistency.py from the TSE listing, not measured by this run"}


for cat in ("smallest state bundle", "largest state bundle"):
    run_arm("check_not_run", category=cat)
""")

md("""
## 10. The outside registers (stage 11, added after results)

The place categories are compared with IBGE, FUNAI and INCRA registers by each polling place's
coordinate. The method was fixed in `EXTERNAL-CHECK-PLAN.md` before this check ran, after the
first results. Stage 11 runs before 6 and 8 because they read its categories.
""")
code(r"""
ST.run_stage("11_external_check.py", PKG, DATA);
AFTER = "added after results"
ZC = table("results/m5b_zero_sections_categories.csv")


def basis_group(b):
    return "registers" if b.startswith("registers") else ("text only" if b.startswith("text only") else b)


@measure("zero_category", stage="11_external_check.py", table="results/m5b_zero_sections_categories.csv", prereg=AFTER)
def _zero_category(side, category, scope):
    g = ZC[(ZC.zero_for == side) & (ZC.label == category) & (ZC.label_basis.map(basis_group) == scope)]
    n = int(ZC[ZC.zero_for == side].sections.sum())
    assert n == zero_count(SEC[2026], side)[0]
    return {"k": int(g.sections.sum()), "n": n, "n_label": "2026 zero sections of the side", "year": 2026}


for side in CONFIG["sides"]:
    for (cat, scope) in sorted({(r.label, basis_group(r.label_basis)) for r in ZC[ZC.zero_for == side].itertuples()}):
        run_arm("zero_category", side=side, category=cat, scope=scope)


@measure("zero_basis", stage="11_external_check.py", table="results/m5b_zero_sections_categories.csv", prereg=AFTER)
def _zero_basis(side, scope):
    g = ZC[(ZC.zero_for == side) & (ZC.label_basis.map(basis_group) == scope)]
    return {"k": int(g.sections.sum()), "n": int(ZC[ZC.zero_for == side].sections.sum()),
            "n_label": "2026 zero sections of the side", "year": 2026}


for side in CONFIG["sides"]:
    for scope in ("registers", "text only", "official place type"):
        run_arm("zero_basis", side=side, scope=scope)

COV = table("results/m5b_coordinate_coverage.csv")


@measure("zero_without_coordinate", stage="11_external_check.py", table="results/m5b_coordinate_coverage.csv", prereg=AFTER)
def _cov(side):
    g = COV[(COV.year == 2026) & (COV.group == f"zero-section places, zero for {side}")]
    return {"k": int(g[g.coordinate != "usable"].sections.sum()), "n": int(g.sections.sum()),
            "n_label": "2026 zero sections of the side", "year": 2026}


for side in CONFIG["sides"]:
    run_arm("zero_without_coordinate", side=side)

@measure("register_text_agreement", stage="11_external_check.py",
         table="results/m5b_zero_sections_agreement_summary.csv", prereg=AFTER)
def _agree(scope):
    AG = table("results/m5b_zero_sections_agreement_summary.csv")
    r = AG[(AG.label_set == "register-based (counted)") & (AG.zero_for == scope)].iloc[0]
    out = {"k": int(r.agree_coarse), "n": int(r.sections), "n_label": "register-based zero sections, 2026", "year": 2026}
    if pd.notna(r.kappa_indigenous):
        out.update(value=float(r.kappa_indigenous), value_unit="Cohen's kappa, indigenous yes or no")
    return out


if LABELS:  # this table compares the registers with the private analyst labels
    for scope in ("opp", "pt", "both sides, indigenous yes or no"):
        run_arm("register_text_agreement", scope=scope)
else:
    print("the analyst labels are absent, so the register and label agreement is not computed")

PANEL = table("results/m5b_panel_2022_2026.csv")


@measure("panel_zero_rate", stage="11_external_check.py", table="results/m5b_panel_2022_2026.csv", prereg=AFTER)
def _panel(year, side, category):
    r = PANEL[(PANEL.definition == category) & (PANEL.year == year)].iloc[0]
    k = int(r[f"zero_{side}"])
    out = {"k": k, "n": int(r.sections), "n_label": f"sections at the {int(r.places_in_both_years)} places followed in both years",
           "value": int(r.places_in_both_years), "value_unit": "polling places in both years"}
    if side == "opp":
        out.update(ratio=float(r.zero_rate_opp), ratio_ci_low=float(r.zero_rate_opp_lo95),
                   ratio_ci_high=float(r.zero_rate_opp_hi95),
                   ci_method="ratio: here the zero rate, interval from a place-cluster bootstrap of stage 11, 2000 Poisson weights")
        assert abs(r.zero_rate_opp - k / r.sections) <= 1e-9 * max(r.zero_rate_opp, 1e-12)
    return out


for cat in PANEL.definition.unique():
    for y in (2022, 2026):
        for side in CONFIG["sides"]:
            run_arm("panel_zero_rate", year=y, side=side, category=cat)

TR = table("results/m5b_text_rule_census.csv")


@measure("text_rule_vs_registers", stage="11_external_check.py", table="results/m5b_text_rule_census.csv", prereg=AFTER)
def _text_rule(category, scope):
    r = TR[(TR.scope == "all places") & (TR.threshold == scope)].iloc[0]
    if category == "precision":
        k, n = int(r.flag_and_register), int(r.flag_and_register + r.flag_only)
        assert abs(k / n - r.precision) < 1e-9
        lab = "places the text rule flags as indigenous"
    else:
        k, n = int(r.flag_and_register), int(r.flag_and_register + r.register_only)
        assert abs(k / n - r.recall) < 1e-9
        lab = "places the registers mark as indigenous"
    return {"k": k, "n": n, "n_label": lab, "year": 2026, "value": float(r.kappa), "value_unit": "Cohen's kappa"}


for cat in ("precision", "recall"):
    for th in ("1 km", "village category, 1 km"):
        run_arm("text_rule_vs_registers", category=cat, scope=th)

""")

md("""
## 11. Exploratory diagnostics (stage 6, added after the U2 result)

Deviation 4 of `EXPERIMENT.md`: written after seeing U2 fire, so every row here is labelled
exploratory.
""")
code(r"""
ST.run_stage("06_diagnostics.py", PKG, DATA);
EXPL = "exploratory, added after results"
LS = table("results/diag_local_share_in_zero_sections.csv")


@measure("local_share_around_zeros", stage="06_diagnostics.py", table="results/diag_local_share_in_zero_sections.csv",
         run_class="exploratory", prereg=EXPL)
def _ls(year, side):
    r = LS[(LS.year == year) & (LS.side == side)].iloc[0]
    return {"value": float(r.median_mun_loo_share_of_zero_candidate),
            "value_unit": "median share of the zero side in the rest of the municipality",
            "k": int(r.zero_sections), "n": int((SEC[year].n >= 1).sum()), "n_label": "sections with a valid vote"}


for y in CONFIG["years"]:
    for side in CONFIG["sides"]:
        run_arm("local_share_around_zeros", year=y, side=side)

D5 = table("results/diag_round1_share_2026_zero_sections.csv").set_index("zero_for")
for side in CONFIG["sides"]:
    r = ZS[(ZS.year == 2026) & (ZS.group == "zero sections") & (ZS.side == side)].iloc[0]
    assert (D5.loc[side, "r1_zero"], D5.loc[side, "r1_lt_5pct"], D5.loc[side, "r1_ge_10pct"]) == \
        (r.r1_share_zero, r.r1_share_lt_5pct, r.r1_share_ge_10pct)
print("stage 6's round-1 table agrees with stage 4's")

CF = table("results/m4_counterfactual_reweighting.csv")


@measure("register_village_zero_rate", stage="06_diagnostics.py", table="results/m4_counterfactual_reweighting.csv",
         run_class="exploratory", prereg=EXPL)
def _rv(year, side):
    r = CF[(CF.side == side) & (CF.classifier == "registers")].iloc[0]
    n_all = int((SEC[year].n >= 1).sum())
    n = r[f"flagged_share_{year}"] * n_all
    k = r[f"zero_rate_flagged_{year}"] * round(n)
    assert abs(n - round(n)) < 1e-6 and abs(k - round(k)) < 1e-6, (n, k)
    return {"k": int(round(k)), "n": int(round(n)), "n_label": "sections at register villages, followed or not",
            "note": "n and k recovered from the table's shares and asserted whole"}


for y in (2022, 2026):
    for side in CONFIG["sides"]:
        run_arm("register_village_zero_rate", year=y, side=side)
""")

md("""
## 12. Privacy-safe aggregates, the analyst-label checks and the reproduction check (stages 8, 9 and 10)
""")
code(r"""
ST.run_stage("08_interactive.py", PKG, DATA);
ST.run_stage("09_classifier_check.py", PKG, DATA);
CAT = table("interactive/zero_sections_by_category.csv")


@measure("category_table", stage="08_interactive.py", table="interactive/zero_sections_by_category.csv", prereg=AFTER)
def _cat(side, category, scope):
    r = CAT[(CAT.method == scope) & (CAT.place_category == category)].iloc[0]
    k = int(r["zero_sections_lula" if side == "pt" else "zero_sections_flavio"])
    return {"k": k, "n": int(r.sections), "n_label": "2026 sections with a valid vote in the category", "year": 2026,
            "note": "suppressed in the published file" if bool(r.suppressed) else ""}


for r in CAT.itertuples():
    for side in CONFIG["sides"]:
        run_arm("category_table", side=side, category=r.place_category, scope=r.method)
for side in CONFIG["sides"]:
    reg = CAT[CAT.method == "registers, 1 km"]
    assert reg["zero_sections_lula" if side == "pt" else "zero_sections_flavio"].sum() == zero_count(SEC[2026], side)[0]
    assert reg.sections.sum() == (SEC[2026].n >= 1).sum()

verify = ST.run_stage("10_verify.py", PKG, DATA, check=False)
m = re.search(r"match: (\d+), differs: (\d+), missing: (\d+), skipped: (\d+), not in reference: (\d+)", verify)
match, differs, missing, skipped, new = map(int, m.groups())


@measure("reproduction", stage="10_verify.py", table="checksums/results.sha256", run_class="check", prereg="not applicable")
def _repro(category):
    if category == "published tables identical to the reference run":
        return {"k": match, "n": match + differs + missing + skipped, "n_label": "tables in the reference checksums",
                "value": new, "value_unit": "tables not in the reference"}
    return {"k": 0 if "privacy rule: holds" in verify else 1, "n": 1, "n_label": "privacy rule (1 means it fails)"}


run_arm("reproduction", category="published tables identical to the reference run")
run_arm("reproduction", category="privacy rule")
assert "privacy rule: holds" in verify
assert skipped == 0 or not LABELS, "tables were skipped although the labels are present"
if CHANGED:
    # A republished input may change a table. That is a data revision, recorded above, not a failure.
    print(f"{len(CHANGED)} inputs differ from the lock: {differs} tables differ, {missing} missing, {new} new")
else:
    assert differs == missing == new == 0
""")

md("""
## 13. The map's data files (contract vr-zero-vote/1)

`zero_by_state.json`, `places_2026.json` and `br_states.json`, built from this run's tables and the
two IBGE files pinned in section 2, under the package's privacy rule: no section, polling place,
zone or community, and no zero count below a state.
""")
code(r"""
if MAP_INPUTS:
    mapdir = DATA / "map"
    states_raw = (mapdir / "ibge-br-uf-minima.geojson").read_bytes()
    br_states, places = F.geometry(states_raw, (DATA / "raw" / "ibge_malha_municipios_minima.geojson").read_bytes(),
                                   (mapdir / "ibge_municipios.json").read_bytes(), hashlib.sha256(states_raw).hexdigest())
    pl, spelled = F.places_2026(PKG / "interactive" / "municipal_2026_2t.csv", places)
    FILES = {"zero_by_state.json": F.zero_by_state(PKG / "results"), "places_2026.json": pl, "br_states.json": br_states}
    problems = F.check(FILES)
    assert not problems, problems
    F.write(FILES, PKG / CONFIG["finding_dir"])
    print(f"places: {len(pl['rows'])} municipalities, {sum(r[0] is None for r in pl['rows'])} without an IBGE match, "
          f"{len(spelled)} matched by spelling")


    @measure("finding_totals", stage="notebook section 13", table="finding/zero_by_state.json", run_class="check",
             prereg="not applicable")
    def _ft(year, side):
        y = next(x for x in FILES["zero_by_state.json"]["years"] if x["year"] == year)
        k = y["totals"]["A" if side == "pt" else "B"]
        assert k == zero_count(SEC[year], side)[0]
        return {"k": k, "n": int((SEC[year].n >= 1).sum()), "n_label": "sections with a valid vote"}


    for y in CONFIG["years"]:
        for side in CONFIG["sides"]:
            run_arm("finding_totals", year=y, side=side)
else:
    print("the two IBGE map inputs are absent, so the map files are not built (REPRODUCE.md, section 4)")
""")

md("""
## 14. The ledger as tables, with intervals

Every proportion with its n and a Wilson 95% interval. Ratios carry the place-cluster bootstrap
interval of deviation 11.
""")
code(r"""
cur = pd.DataFrame([r for r in LEDGER.current() if r["run_id"] == RUN_ID])
num = ["n", "k", "share", "share_ci_low", "share_ci_high", "expected", "ratio", "ratio_ci_low", "ratio_ci_high", "value"]
for c in num:
    cur[c] = pd.to_numeric(cur[c], errors="coerce")
pd.set_option("display.width", 200, "display.max_columns", 20, "display.max_rows", 80)
zc = cur[(cur.measure == "zero_count") & (cur.min_valid_votes == "1")]
print("Zero-vote sections, at least one valid vote\n",
      zc[["row_id", "year", "side", "k", "n", "share", "share_ci_low", "share_ci_high"]].to_string(index=False))
oe = cur[(cur.measure == "observed_vs_expected") & (cur.event == "zero") & (cur.min_valid_votes == "1")]
print("\nObserved against expected, zero event, n>=1\n",
      oe[["row_id", "year", "side", "model", "k", "expected", "ratio", "ratio_ci_low", "ratio_ci_high"]].round(3).to_string(index=False))
pz = cur[cur.measure == "panel_zero_rate"]
print("\nPlaces followed from 2022 to 2026\n",
      pz[["row_id", "category", "year", "side", "k", "n", "share", "share_ci_low", "share_ci_high", "ratio_ci_low", "ratio_ci_high"]].round(4).to_string(index=False))
""")

md("""
## 15. Decision: the rules registered in `EXPERIMENT.md`, read against the ledger

"What counts as unexpected" was fixed before any result. Each rule is evaluated here from ledger
rows only, and its outcome is itself a ledger row, which cites in its note the rows it read. The
registration said U1 alone is read as nothing, and only together with U2. It stated one expected
outcome: that U1 fires for the binomial models in every year and on both sides. Each decision
row says in `expectation_held` whether that held, or "not applicable" where nothing was expected.
The registration set no count of U2 checks that would make 2026 unusual as a whole, so the
decision reports how many fired and where, and draws no verdict beyond that.
""")
code(r"""
cur = pd.DataFrame([r for r in LEDGER.current() if r["run_id"] == RUN_ID])
for c in ("k", "n", "value", "share"):
    cur[c] = pd.to_numeric(cur[c], errors="coerce")
row = lambda **f: cur[(cur.arm == L.arm_key(**f))].iloc[0]


NA = "not applicable"
BINOMIAL = ["B-mun", "B-place"]


@measure("decision", stage="notebook section 15", prereg="pre-registered", interval=False)
def _decision(category, side, year=None, scope=None):
    if category == "U1":
        models = CONFIG["models_preregistered"] if scope is None else BINOMIAL
        rs = cur[(cur.measure == "observed_vs_expected") & (cur.year == str(year)) & (cur.side == side)
                 & cur.model.isin(models)]
        k = int((pd.to_numeric(rs.k) > pd.to_numeric(rs.value)).sum())
        rows = f"the {len(rs)} matching observed_vs_expected rows between {rs.row_id.iloc[0]} and {rs.row_id.iloc[-1]}"
        if scope is None:
            return {"k": k, "n": len(rs), "expectation_held": NA,
                    "n_label": "registered U1 checks (4 models, 3 events, 3 sizes), normal bound as registered",
                    "note": f"no outcome registered for all four models together, see the binomial row. "
                            f"Read only with U2. From {rows}"}
        return {"k": k, "n": len(rs), "expectation_held": bool(k == len(rs)),
                "n_label": "registered U1 checks of the binomial models (B-mun and B-place, 3 events, 3 sizes), "
                           "normal bound as registered",
                "note": f"registered: U1 fires for the binomial models in every year and on both sides. From {rows}"}
    if category == "U2":
        r = row(measure="u2_fires", scope="pooled", side=side)
        return {"k": int(r.k), "n": int(r.n), "n_label": "registered U2 checks", "expectation_held": NA,
                "note": f"no outcome registered. From {r.row_id}"}
    if category == "U3":
        r26 = row(measure="round1_in_zero_sections", year=2026, side=side, category="r1_share_ge_10pct")
        r22 = row(measure="round1_in_zero_sections", year=2022, side=side, category="r1_share_ge_10pct")
        s26, s22 = r26.k / r26.n, r22.k / r22.n
        fires = bool(s26 > CONFIG["u3_ratio"] * s22 and r26.k >= CONFIG["u3_min_sections"])
        return {"k": int(fires), "n": 1, "n_label": "rule fires (1) or not (0)", "value": s26,
                "value_unit": "2026 share of zero sections with 10% or more in round 1", "expectation_held": NA,
                "note": f"no outcome registered. 2022 share {s22:.4f}, from {r26.row_id} and {r22.row_id}"}
    if category == "U4":
        rs = cur[cur.measure == "consistency"]
        rs = rs[~rs.category.isin(["bulletin zip hash files", "national report lines"])]
        return {"k": int(rs.k.sum()), "n": len(rs), "n_label": "differences summed over the consistency rows",
                "expectation_held": NA, "note": "no outcome registered. From rows " + " ".join(rs.row_id)}
    if category == "U5":
        r = row(measure="share_of_margin", year=2026)
        return {"value": float(r.value), "value_unit": "share of the national margin, arithmetic only",
                "expectation_held": NA, "note": f"arithmetic, no outcome registered. From {r.row_id}"}
    raise KeyError(category)


for y in CONFIG["years"]:
    for side in CONFIG["sides"]:
        run_arm("decision", category="U1", side=side, year=y)
        run_arm("decision", category="U1", side=side, year=y, scope="binomial models")
for side in ("both", "pt", "opp"):
    run_arm("decision", category="U2", side=side)
for side in CONFIG["sides"]:
    run_arm("decision", category="U3", side=side)
run_arm("decision", category="U4", side="both")
run_arm("decision", category="U5", side="both")

cur = pd.DataFrame([r for r in LEDGER.current() if r["run_id"] == RUN_ID])
d = cur[cur.measure == "decision"][["row_id", "category", "scope", "year", "side", "k", "n", "value", "expectation_held"]]
print(d.to_string(index=False))
""")

md("## 16. Closing re-check: config, harness and inputs unchanged since the start")
code(r"""
C.validate(CONFIG)
assert C.digest(CONFIG) == CONFIG_SHA256, "the config changed during the run"
assert I.harness(PKG)[1] == HARNESS_SHA256, "a code or lock file changed during the run"
# Re-hashing 6 GB again costs minutes on a shared disk. The inputs were hashed once in section 2,
# and here each must still have the same size, modification time and inode.
assert I.unchanged_since(INPUT_ROWS), "an input changed during the run"
n_rows = len([r for r in LEDGER.rows if r["run_id"] == RUN_ID])
failed = [r["row_id"] for r in LEDGER.rows if r["run_id"] == RUN_ID and r["status"] != "ok"]
assert not failed, failed
print(f"run {RUN_ID}: {n_rows} ledger rows, none failed")
print("stage times (s):", json.dumps(ST.TIMINGS))
print(f"total {time.time() - T0:.0f} s")
""")

nb = new_notebook(cells=CELLS, metadata={
    "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
    "language_info": {"name": "python"}})
nbformat.write(nb, "zero_vote_sections.ipynb")
print(f"wrote zero_vote_sections.ipynb with {len(CELLS)} cells")
