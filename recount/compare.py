"""Compares the awk recount with the ledger's current rows. Exits 1 on any difference or a missing year.

  python3 recount/compare.py recount/expected.txt results.csv
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zvnb.ledger import Ledger  # noqa: E402

text, ledger = Path(sys.argv[1]).read_text(), sys.argv[2]
rows = Ledger(ledger, {}).current()
run = rows[-1]["run_id"]
arm = {r["arm"]: r for r in rows if r["run_id"] == run}
same = diff = 0
years = {}
for block in re.split(r"(?=^year )", text, flags=re.M):
    m = re.match(r"year (\d{4}): sections with a round-2 row (\d+), votes pt (\d+), votes opp (\d+), margin (-?\d+)", block)
    if m:
        years[m.group(1)] = block
for y in ("2018", "2022", "2026"):
    if y not in years:
        print(f"year {y}: missing from the recount")
        diff += 1
        continue
    b = years[y]
    _, secs, vp, vo, mg = re.match(r"year (\d{4}): sections with a round-2 row (\d+), votes pt (\d+), votes opp (\d+), margin (-?\d+)", b).groups()
    if int(secs) == 0:
        print(f"year {y}: no section read")
        diff += 1
    checks = [(f"measure=votes|year={y}|side=pt", "value", vp), (f"measure=votes|year={y}|side=opp", "value", vo),
              (f"measure=margin|year={y}", "value", mg)]
    for mn, n, zo, vpo, zp, vop in re.findall(r"at least\s+(\d+) valid votes: sections (\d+), zero for opp (\d+) \(pt votes in them (\d+)\), zero for pt (\d+) \(opp votes in them (\d+)\)", b):
        for side, k, other in (("opp", zo, vpo), ("pt", zp, vop)):
            a = f"measure=zero_count|year={y}|side={side}|min_valid_votes={mn}"
            checks += [(a, "k", k), (a, "votes_other", other), (a, "n", n)]
    for a, field, want in checks:
        got = arm[a][field] if a in arm else "absent"
        if got == want:
            same += 1
        else:
            diff += 1
            print(f"differs: {a} {field}: ledger {got}, recount {want}")
print(f"run {run}: {same} fields equal, {diff} differ")
sys.exit(1 if diff or same != 63 else 0)
