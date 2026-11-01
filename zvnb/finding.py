"""The map's data files, contract vr-zero-vote/1 (the site's zero-vote-contract.md).

Three files: zero_by_state.json (zero-vote sections by year, side, region and state),
places_2026.json (one row per municipality, only what the official results publish
per municipality, never a zero count) and br_states.json (the state outlines).

This is a line-for-line port of the site's two build tools, so the files come out
byte-identical to the ones the site builds from the published package: the same
projection, the same rounding (Python's round is the same half-to-even rule the site
tool reimplements), the same spelling match, and numbers written the way JSON.stringify
writes them.
"""
import csv
import json
import math
import re
import unicodedata
from pathlib import Path

CONTRACT = "vr-zero-vote/1"
UF_ORDER = ["RO", "AC", "AM", "RR", "PA", "AP", "TO", "MA", "PI", "CE", "RN", "PB", "PE", "AL", "SE",
            "BA", "MG", "ES", "RJ", "SP", "PR", "SC", "RS", "MS", "MT", "GO", "DF"]
REGIONS = ["North", "Northeast", "Center-West", "Southeast", "South", "Abroad"]
UF_CODE = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
           "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
           "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
           "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}
# The sides by ballot number, lowest first (UX-005), named as the piece names the candidates.
SIDES = {
    2018: [{"side": "A", "number": 13, "party": "PT", "name": "Fernando Haddad"},
           {"side": "B", "number": 17, "party": "PSL", "name": "Jair Bolsonaro"}],
    2022: [{"side": "A", "number": 13, "party": "PT", "name": "Lula"},
           {"side": "B", "number": 22, "party": "PL", "name": "Jair Bolsonaro"}],
    2026: [{"side": "A", "number": 13, "party": "PT", "name": "Lula"},
           {"side": "B", "number": 22, "party": "PL", "name": "Flávio Bolsonaro"}],
}
FRAME, LAT0 = 1000, -14.5
LABEL_OUT = {"RN": [70, -10], "PB": [70, 4], "AL": [62, 14], "SE": [58, 28], "ES": [62, 6],
             "RJ": [56, 26], "DF": [95, 10], "AC": [-40, 92], "PE": [137, 0], "SC": [77, 0]}
ANCHOR_SHIFT = {"PE": [-20, 4]}
STATE_MESH = {"source": "IBGE API v3 malhas, paises/BR, qualidade=minima, intrarregiao=UF",
              "retrieved": "2026-10-26"}


# ---------- JSON exactly as JSON.stringify writes it ----------

def js_number(v):
    if isinstance(v, bool):
        raise TypeError("bool is not a number here")
    if isinstance(v, int):
        return str(v)
    if math.isnan(v) or math.isinf(v):
        return "null"
    if v == int(v) and abs(v) < 1e21:
        return str(int(v))
    r = repr(v)
    if "e" not in r:
        return r
    mant, exp = r.split("e")
    exp = int(exp)
    if 1e-6 <= abs(v) < 1e21 and exp < 0:  # JSON.stringify writes 1e-6 and up in decimal
        sign = "-" if mant.startswith("-") else ""
        digits = mant.lstrip("-").replace(".", "")
        return f"{sign}0.{'0' * (-exp - 1)}{digits}"
    return f"{mant}e{'+' if exp > 0 else '-'}{abs(exp)}"


def js_dumps(o):
    if o is None:
        return "null"
    if isinstance(o, bool):
        return "true" if o else "false"
    if isinstance(o, (int, float)):
        return js_number(o)
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(js_dumps(x) for x in o) + "]"
    if isinstance(o, dict):
        return "{" + ",".join(json.dumps(str(k), ensure_ascii=False) + ":" + js_dumps(v) for k, v in o.items()) + "}"
    raise TypeError(type(o))


def js_round(x):
    """Math.round: halves go up."""
    return math.floor(x + 0.5)


# ---------- geometry (port of the site's build_br_geo) ----------

def polygons(g):
    return g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]


def area_centroid(outline):
    a = cx = cy = 0.0
    n = len(outline)
    for i, (x0, y0) in enumerate(outline):
        x1, y1 = outline[(i + 1) % n]
        f = x0 * y1 - x1 * y0
        a += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(a) < 1e-9:
        xs = [p[0] for p in outline]
        ys = [p[1] for p in outline]
        return 0, (sum(xs) / len(xs), sum(ys) / len(ys))
    return abs(a) / 2, (cx / (3 * a), cy / (3 * a))


def geometry(state_mesh_bytes, mun_mesh_bytes, names_bytes, state_mesh_sha256):
    """Returns (br_states dict, {ibge code: (name, (x, y) or None)})."""
    uf = json.loads(state_mesh_bytes)
    k = math.cos(LAT0 * math.pi / 180)
    pts = [(x * k, -y) for f in uf["features"] for poly in polygons(f["geometry"]) for outline in poly
           for x, y in outline]
    minx = min(p[0] for p in pts); maxx = max(p[0] for p in pts)
    miny = min(p[1] for p in pts); maxy = max(p[1] for p in pts)
    scale = FRAME / max(maxx - minx, maxy - miny)
    W, H = round((maxx - minx) * scale), round((maxy - miny) * scale)

    def P(x, y):
        return (round((x * k - minx) * scale), round((-y - miny) * scale))

    states = {}
    for f in uf["features"]:
        code = UF_CODE.get(f["properties"]["codarea"])
        if not code:
            raise ValueError(f"unknown UF code {f['properties']['codarea']}")
        parts, best = [], (0, None)
        for poly in polygons(f["geometry"]):
            for i, outline in enumerate(poly):
                pr = [P(x, y) for x, y in outline]
                cl = [pr[0]] + [q for j, q in enumerate(pr[1:]) if q[0] != pr[j][0] or q[1] != pr[j][1]]
                if len(cl) < 4:
                    continue
                op = cl[:-1]
                parts.append("M" + " ".join(f"{x},{y}" for x, y in op) + "Z")
                if i == 0:
                    area, c = area_centroid(op)
                    if area > best[0]:
                        best = (area, c)
        cx0, cy0 = best[1] if best[1] else (0, 0)
        sh = ANCHOR_SHIFT.get(code, [0, 0])
        coords = [tuple(map(int, t.split(","))) for p in parts for t in p[1:-1].split(" ")]
        states[code] = {"d": "".join(parts), "anchor": [round(cx0 + sh[0]), round(cy0 + sh[1])],
                        "bbox": [min(c[0] for c in coords), min(c[1] for c in coords),
                                 max(c[0] for c in coords), max(c[1] for c in coords)],
                        "out": LABEL_OUT.get(code)}

    mun = json.loads(mun_mesh_bytes)
    points = {}
    for f in mun["features"]:
        best = (0, None)
        for poly in polygons(f["geometry"]):
            if not poly:
                continue
            area, c = area_centroid([(x * k, -y) for x, y in poly[0]])
            if area > best[0]:
                best = (area, c)
        if best[1]:
            points[f["properties"]["codarea"]] = (round((best[1][0] - minx) * scale),
                                                  round((best[1][1] - miny) * scale))
    names, state_names = {}, {}
    for m in json.loads(names_bytes):
        names[str(m["id"])] = m["nome"]
        u = (((m.get("microrregiao") or {}).get("mesorregiao") or {}).get("UF")
             or (((m.get("regiao-imediata") or {}).get("regiao-intermediaria") or {}).get("UF")))
        if u:
            state_names[u["sigla"]] = u["nome"]
    br_states = {"contract": CONTRACT, "source": STATE_MESH["source"], "retrieved": STATE_MESH["retrieved"],
                 "raw_sha256": state_mesh_sha256,
                 "projection": f"equirectangular, parallel scale cos({LAT0} deg), integer frame",
                 "viewBox": [W, H], "names": state_names, "states": states}
    places = {code: (names[code], points.get(code)) for code in sorted(names)}
    return br_states, places


# ---------- names ----------

PARTICLES = {"de", "da", "do", "das", "dos", "e", "d"}


def bare(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("M"))
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(w for w in s.split() if w and w not in PARTICLES)


def distance(a, b):
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev = d[0]
        d[0] = i
        for j in range(1, len(b) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (0 if a[i - 1] == b[j - 1] else 1))
            prev = cur
    return d[len(b)]


def title_case(s):
    small = {"de", "da", "do", "das", "dos", "e"}
    return " ".join(w if i > 0 and w in small else w[:1].upper() + w[1:]
                    for i, w in enumerate(s.lower().split(" ")))


def collate_key(s):
    """Portuguese collation as the site's localeCompare applies it: letters without accents
    and case first, then accents, then case."""
    nfd = unicodedata.normalize("NFD", s)
    base = "".join(ch for ch in nfd if not unicodedata.category(ch).startswith("M"))
    accents = tuple(unicodedata.normalize("NFD", ch)[1:] for ch in s)
    return (base.lower(), accents, tuple(not ch.islower() for ch in base))


# ---------- the three files ----------

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    return list(csv.DictReader(lines))


def zero_by_state(results_dir, years=(2018, 2022, 2026)):
    out = []
    for year in years:
        states = {u: {"uf": u, "A": 0, "B": 0} for u in UF_ORDER}
        abroad = {"A": 0, "B": 0}
        side = {"pt": "A", "opp": "B"}
        for r in read_csv(Path(results_dir) / f"zero_by_state_{year}.csv"):
            s = side[r["zero_for"]]
            if r["SG_UF"] == "ZZ":
                abroad[s] += int(r["sections"])
            else:
                states[r["SG_UF"]][s] += int(r["sections"])
        regions = {g: {"region": g, "A": 0, "B": 0} for g in REGIONS}
        for r in read_csv(Path(results_dir) / f"zero_by_region_{year}.csv"):
            regions[r["region"]][side[r["zero_for"]]] += int(r["sections"])
        st = list(states.values())
        totals = {"A": sum(x["A"] for x in st) + abroad["A"], "B": sum(x["B"] for x in st) + abroad["B"]}
        out.append({"year": year, "round": 2, "sides": SIDES[year], "totals": totals, "abroad": abroad,
                    "regions": list(regions.values()), "states": st})
    return {"contract": CONTRACT, "source": "TSE open data, votes by section, round 2. See SOURCES.md.",
            "package_commit": None, "years": out}


POOLED_NAME = "other, pooled"


def is_pooled(r):
    """True for a row of 08_interactive.py that pools units: its name, or more than one unit."""
    units = (r.get("units_pooled") or "1").strip()
    return r["municipality"].strip().lower() == POOLED_NAME or int(units) > 1


def places_2026(municipal_csv, places):
    by_state = {}
    for code, (name, _) in places.items():
        by_state.setdefault(UF_CODE.get(code[:2], ""), []).append((code, bare(name)))
    matched = []

    def spelling_match(uf, name):
        key = bare(name)
        scored = sorted(((c, distance(key, ck)) for c, ck in by_state.get(uf, [])), key=lambda t: t[1])
        if not scored or scored[0][1] > 3 or (len(scored) > 1 and scored[1][1] == scored[0][1]):
            return None
        matched.append(f"{uf} {name} as {places[scored[0][0]][0]}")
        return scored[0][0]

    rows = []
    for r in read_csv(municipal_csv):
        # A pooled row stands for several units, so it is no municipality and has no place on the map.
        # The contract keeps it out wherever it is, abroad or inside a state.
        if is_pooled(r):
            continue
        ib = r.get("ibge_code", "")
        code = ib if re.fullmatch(r"\d{7}", ib or "") else spelling_match(r["state"], title_case(r["municipality"]))
        place = places.get(code) if code else None
        a, b = float(r["share_lula"]), float(r["share_flavio"])
        xy = place[1] if place else None
        rows.append([int(code) if code else None, r["state"], place[0] if place else title_case(r["municipality"]),
                     int(r["sections_with_valid_votes"]), int(r["eligible_voters"]), int(r["valid_votes"]),
                     js_round(a * 1e6) / 1e6, js_round(b * 1e6) / 1e6,
                     xy[0] if xy else None, xy[1] if xy else None])
    # One row per municipality of the 27 units with a section with valid votes. Cities abroad (TSE's
    # unit ZZ) are left out: the contract's check 4 allows only the 27, and the map draws no point abroad.
    rows = [r for r in rows if r[3] > 0 and r[1] in UF_ORDER]
    rows.sort(key=lambda r: (r[1], collate_key(r[2])))
    return {"contract": CONTRACT, "year": 2026, "round": 2,
            "columns": ["ibge", "uf", "name", "sections", "eligible", "valid", "shareA", "shareB", "x", "y"],
            "rows": rows}, matched


# The site's own check (packages/components/src/finding/zero-vote.ts): this pattern, the contract's own
# column "sections" excepted, and a frame widened east by 150 units for the ocean islands.
FORBIDDEN = re.compile(r"section|zone|place|polling|community|zeros?$|^zero", re.I)
PLACE_COLUMNS = ["ibge", "uf", "name", "sections", "eligible", "valid", "shareA", "shareB", "x", "y"]
EAST_MARGIN = 150


def check(files):
    """The site's five build checks. Returns a list of problems (empty means the files pass)."""
    bad = []
    for name, o in files.items():
        if o.get("contract") != CONTRACT:
            bad.append(f"{name}: contract is not {CONTRACT}")
    for y in files["zero_by_state.json"]["years"]:
        if [s["uf"] for s in y["states"]] != UF_ORDER:
            bad.append(f"{y['year']}: states are not the 27 in order")
        if [g["region"] for g in y["regions"]] != REGIONS:
            bad.append(f"{y['year']}: regions are not the six")
        for s in "AB":
            by_state = sum(x[s] for x in y["states"]) + y["abroad"][s]
            by_region = sum(g[s] for g in y["regions"])
            if not (y["totals"][s] == by_state == by_region):
                bad.append(f"{y['year']} {s}: totals {y['totals'][s]}, states+abroad {by_state}, regions {by_region}")
    p = files["places_2026.json"]
    for c in p["columns"]:
        if c != "sections" and FORBIDDEN.search(c):
            bad.append(f"places_2026.json: forbidden column {c}")
    if p["columns"] != PLACE_COLUMNS:
        bad.append("places_2026.json: columns differ from the contract")
    W, H = files["br_states.json"]["viewBox"]
    W += EAST_MARGIN
    for r in p["rows"]:
        if abs(r[6] + r[7] - 1) > 1e-6:
            bad.append(f"places_2026.json: shares of {r[2]} sum to {r[6] + r[7]}")
        if r[1] not in UF_ORDER:
            bad.append(f"places_2026.json: unknown uf {r[1]}")
        if str(r[2]).strip().lower() == POOLED_NAME:
            bad.append(f"places_2026.json: a pooled row in {r[1]}")
        if r[8] is not None and not (0 <= r[8] <= W and 0 <= r[9] <= H):
            bad.append(f"places_2026.json: point of {r[2]} outside the frame")
    if sorted(files["br_states.json"]["states"]) != sorted(UF_ORDER):
        bad.append("br_states.json: not one path per state")
    return bad


def write(files, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, o in files.items():
        (out_dir / name).write_text(js_dumps(o) + "\n", encoding="utf-8")
