"""Step 11. External check of the place categories against official registers (added in v2).

Added after a full recheck (items M3 and S7). The method is fixed in EXTERNAL-CHECK-PLAN.md, written
before any classification was run. In short:
  1. Load the outside registers (IBGE 2022 Census indigenous and quilombola localities and
     census sectors, FUNAI indigenous lands and villages, INCRA quilombola territories)
     and check each file against its SHA-256.
  2. Join every polling place of 2026 and 2022 to them by its TSE coordinate.
  3. Classify the 2026 zero sections with the registers, plus text where the plan allows.
     The labels are written and hashed before the lab's own labels are read.
  4. Draw place-level samples of the text rule (flagged, and unflagged in municipalities
     with an indigenous land or locality) and classify them from the registers.
  5. Precision, recall and kappa of the text rule against the registers, on the samples
     and on every place.
  6. Compare with the lab's labels for the zero sections.
  7. The 2022 to 2026 stable panel with the register definition.

Runs as step 11 of run_all.sh, after step 3 (it reads the derived section tables).
Step 1 downloads the registers into ZV_REGISTERS_DIR (default <data>/registers) and
checks them against sources.lock.tsv. This step checks them again before use.
Part 6 needs the private analyst labels and is skipped without them.
Published outputs: results/m5b_*. Row-level outputs: <data>/private/external_check/.
"""
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import shapefile
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DERIVED, HANDCHECK, HERE, KEY, PLACE, PRIVATE, RAW, REGISTERS as REG, SEED, write_csv  # noqa: E402,E501

PRIV = PRIVATE / "external_check"
PRIV.mkdir(parents=True, exist_ok=True)

# The lab's text normaliser, reused so the panel match is the lab's match.
_spec = importlib.util.spec_from_file_location("build", Path(__file__).parent / "03_build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
norm = build.norm

EARTH_KM = 6371.0088
NEAR_KM = (1.0, 5.0)
N_SAMPLE = 200

# name, publisher, path in the registers folder. URL, reference date and SHA-256 are in
# sources.lock.tsv (kind "register"), the single record of every source file.
REGISTERS = [
    ("Indigenous localities, 2022 Census (LI)", "IBGE", "ibge/BR_LIs_CD2022_20250919.csv"),
    ("Places of concentration of indigenous people, 2022 Census (LCPI)", "IBGE",
     "ibge/BR_LCPIs_CD2022_20250919.csv"),
    ("Quilombola localities, 2022 Census (LQ)", "IBGE", "ibge/BR_LQs_CD2022.csv"),
    ("Census sectors 2022 (situation and type)", "IBGE", "ibge_setores/BR_setores_CD2022.gpkg"),
    ("Census sectors 2022, data dictionary", "IBGE", "ibge_setores/Dicionario_de_dados_malha_agregados.xlsx"),
    ("Indigenous lands, polygons (tis_poligonais)", "FUNAI", "funai/tis_poligonais_shp.zip"),
    ("Indigenous villages, points (aldeias_pontos)", "FUNAI", "funai/aldeias_pontos_shp.zip"),
    ("Quilombola territories, polygons", "INCRA", "incra/areas_de_quilombolas.zip"),
]
LICENCE = ("No licence stated on the download page. Brazilian federal open data policy "
           "(Decreto 8.777/2016) applies. Cited, not redistributed. (Inference.)")

# Census sector codes, from the IBGE dictionary.
SIT_URBAN = {"1", "2", "3"}
TYPE_INDIGENOUS, TYPE_PRISON, TYPE_QUILOMBOLA = "5", "6", "9"

CAT_PRISON = "prison or detention"
CAT_VILLAGE = "indigenous village or community"
CAT_URBAN_IND = "urban indigenous school (in a town)"
CAT_QUI = "quilombola community"
CAT_RURAL = "other rural or riverside"
CAT_URBAN = "urban"
CAT_UNRES = "unresolved"
CATS = [CAT_PRISON, CAT_VILLAGE, CAT_URBAN_IND, CAT_QUI, CAT_RURAL, CAT_URBAN, CAT_UNRES]

# Text used only where the plan allows it (urban indigenous schools, and the fallback).
TXT_IND = r"\bINDIGEN|\bALDEIA [A-Z]"
TXT_SCHOOL = r"ESCOLA|\bESC\b|\bE M\b|\bE E\b|\bU E\b|\bCETI\b|COLEGIO|UNIDADE ESCOLAR|\bEMEF|\bEEI|\bEMEI"
TXT_QUI = r"QUILOMB"
TXT_RIVER = r"\bRIO\b|IGARAPE|RIBEIRINH|\bLAGO\b|\bPARANA\b|\bFURO\b|\bILHA\b"
TXT_RURAL = r"ZONA RURAL|\bSITIO\b|\bFAZENDA\b|\bPOVOADO\b|ASSENTAMENTO|\bCOMUNIDADE\b|\bVICINAL\b|\bRAMAL\b"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_registers():
    with open(HERE / "sources.lock.tsv", newline="") as fh:
        lock = {r["file"]: r for r in csv.DictReader(fh, delimiter="\t") if r["kind"] == "register"}
    rows, bad = [], []
    for name, pub, rel in REGISTERS:
        url, got, want = lock[rel]["url"], lock[rel]["reference_download_utc"], lock[rel]["sha256"]
        p = REG / rel
        h = sha256(p)
        if h != want:
            bad.append(f"{rel}: {h}")
        rows.append({"register": name, "publisher": pub, "url": url, "retrieved_utc": got,
                     "licence": LICENCE, "sha256": h, "sha256_matches_plan": h == want})
    if bad and os.environ.get("ZV_ACCEPT_NEW_REGISTERS") != "1":
        raise SystemExit("register hash differs from sources.lock.tsv (set ZV_ACCEPT_NEW_REGISTERS=1 to "
                         "accept a newer file):\n" + "\n".join(bad))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- register loading
def read_points(rel, lat, lon, keep):
    d = pd.read_csv(REG / rel, sep=";", encoding="utf-8-sig", dtype=str)
    d["lat"] = pd.to_numeric(d[lat].str.replace(",", "."), errors="coerce")
    d["lon"] = pd.to_numeric(d[lon].str.replace(",", "."), errors="coerce")
    return d.dropna(subset=["lat", "lon"])[keep + ["lat", "lon"]].reset_index(drop=True)


def read_shp_zip(rel, encoding="latin1"):
    """Polygons or points of a zipped shapefile, with their records."""
    z = zipfile.ZipFile(REG / rel)
    names = {Path(n).suffix.lower(): n for n in z.namelist()}
    r = shapefile.Reader(shp=io.BytesIO(z.read(names[".shp"])), shx=io.BytesIO(z.read(names[".shx"])),
                         dbf=io.BytesIO(z.read(names[".dbf"])), encoding=encoding, encodingErrors="replace")
    geoms, recs = [], []
    for sr in r.iterShapeRecords():
        if sr.shape.shapeType == shapefile.NULL:
            continue
        geoms.append(shapely.make_valid(shape(sr.shape.__geo_interface__)))
        recs.append(sr.record.as_dict())
    return np.array(geoms, dtype=object), pd.DataFrame(recs)


def unit_xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


class Nearest:
    """Great-circle distance in km to the nearest point of a register."""

    def __init__(self, lat, lon):
        self.tree = cKDTree(unit_xyz(np.asarray(lat), np.asarray(lon)))

    def __call__(self, lat, lon):
        chord, idx = self.tree.query(unit_xyz(lat, lon))
        return 2 * EARTH_KM * np.arcsin(np.clip(chord / 2, 0, 1)), idx


def gpkg_wkb(blob):
    """Strip the GeoPackage header and return the WKB body."""
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 0b111]
    return blob[8 + env:]


def sector_join(lat, lon):
    """Census sector situation and type for each point (None where no sector contains it)."""
    con = sqlite3.connect(f"file:{REG / 'ibge_setores/BR_setores_CD2022.gpkg'}?mode=ro", uri=True)
    out_sit = np.full(len(lat), None, dtype=object)
    out_typ = np.full(len(lat), None, dtype=object)
    out_cd = np.full(len(lat), None, dtype=object)
    pts = shapely.points(lon, lat)
    # Read by state to bound memory. Each state's points are tested against all sectors of the
    # state's bounding box, so a point just across a border is still found.
    states = [r[0] for r in con.execute("SELECT DISTINCT CD_UF FROM BR_setores_CD2022 WHERE CD_UF IS NOT NULL")]
    for uf in sorted(states):
        rows = con.execute("SELECT geom, CD_SETOR, CD_SIT, CD_TIPO FROM BR_setores_CD2022 WHERE CD_UF = ?",
                           (uf,)).fetchall()
        geoms = shapely.from_wkb([gpkg_wkb(r[0]) for r in rows])
        tree = shapely.STRtree(geoms)
        xmin, ymin, xmax, ymax = shapely.total_bounds(geoms)
        cand = np.where((lon >= xmin) & (lon <= xmax) & (lat >= ymin) & (lat <= ymax)
                        & pd.isna(out_cd))[0]
        if len(cand):
            pi, gi = tree.query(pts[cand], predicate="within")
            first = pd.Series(gi, index=pi).groupby(level=0).first()
            for p, g in first.items():
                k = cand[p]
                out_cd[k], out_sit[k], out_typ[k] = rows[g][1], rows[g][2], rows[g][3]
        del rows, geoms, tree
    con.close()
    return out_cd, out_sit, out_typ


# ---------------------------------------------------------------- polling places
def read_places(year):
    """One row per polling place of round 2, main sections, from the raw TSE file."""
    z = zipfile.ZipFile(RAW / f"eleitorado_local_votacao_{year}.zip")
    cols = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
            "DS_TIPO_SECAO_AGREGADA", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_TIPO_LOCAL",
            "DS_ENDERECO", "NM_BAIRRO", "NR_LATITUDE", "NR_LONGITUDE", "QT_ELEITOR_SECAO"]
    parts = [pd.read_csv(z.open(n), sep=";", encoding="latin1", dtype=str, usecols=cols)
             for n in z.namelist() if n.lower().endswith(".csv")]
    d = pd.concat(parts, ignore_index=True)
    d = d[(d.NR_TURNO == "2") & d.DS_TIPO_SECAO_AGREGADA.str.upper().str.startswith("PRINC")]
    for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO"):
        d[c] = d[c].astype(int)
    d = d.drop_duplicates(KEY)
    for c in ("NR_LATITUDE", "NR_LONGITUDE"):
        d[c] = pd.to_numeric(d[c].str.replace(",", ".", regex=False), errors="coerce")
    d["QT_ELEITOR_SECAO"] = pd.to_numeric(d.QT_ELEITOR_SECAO, errors="coerce").fillna(0).astype(int)
    sec = d[KEY + ["NR_LOCAL_VOTACAO", "QT_ELEITOR_SECAO"]].copy()
    p = (d.groupby(PLACE, sort=False)
         .agg(NM_MUNICIPIO=("NM_MUNICIPIO", "first"), NM_LOCAL_VOTACAO=("NM_LOCAL_VOTACAO", "first"),
              DS_TIPO_LOCAL=("DS_TIPO_LOCAL", "first"), DS_ENDERECO=("DS_ENDERECO", "first"),
              NM_BAIRRO=("NM_BAIRRO", "first"),
              lat=("NR_LATITUDE", lambda x: x.mode().iloc[0] if x.notna().any() else np.nan),
              lon=("NR_LONGITUDE", lambda x: x.mode().iloc[0] if x.notna().any() else np.nan),
              n_coords=("NR_LATITUDE", "nunique"), sections=("NR_SECAO", "size"),
              voters=("QT_ELEITOR_SECAO", "sum"))
         .reset_index())
    for c in ("NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO"):
        p[c] = p[c].fillna("")
    p["name_norm"] = p.NM_LOCAL_VOTACAO.map(norm)
    p["text_norm"] = p.name_norm + " | " + p.DS_ENDERECO.map(norm) + " | " + p.NM_BAIRRO.map(norm)
    return p, sec


def municipality_codes():
    z = zipfile.ZipFile(RAW / "municipio_tse_ibge.zip")
    n = [x for x in z.namelist() if x.endswith(".csv")][0]
    m = pd.read_csv(z.open(n), sep=";", encoding="latin1", dtype=str)
    return dict(zip(m.CD_MUNICIPIO_TSE.astype(int), m.CD_MUNICIPIO_IBGE.astype(str)))


def coordinate_quality(p, mun_geom, tse_ibge):
    """Reason a coordinate is unusable, or '' if usable (rules of the plan)."""
    lat, lon = p.lat.to_numpy(), p.lon.to_numpy()
    reason = np.full(len(p), "", dtype=object)
    missing = ~np.isfinite(lat) | ~np.isfinite(lon) | (lat == 0) | (lon == 0) | (lat == -1) | (lon == -1)
    reason[missing] = "missing or zero"
    box = ~missing & ~((lat >= -34) & (lat <= 5.5) & (lon >= -74.5) & (lon <= -28.5))
    reason[box] = "outside Brazil box"
    ok = reason == ""
    ibge = p.CD_MUNICIPIO.map(tse_ibge)
    p["CD_MUN_IBGE"] = ibge
    outside = np.zeros(len(p), bool)
    for i in np.where(ok & ibge.notna().to_numpy())[0]:
        g = mun_geom.get(ibge.iat[i])
        if g is None:
            continue
        pt = shapely.Point(lon[i], lat[i])
        if g.contains(pt):
            continue
        k = np.cos(np.radians(lat[i]))
        gs = shapely.transform(g, lambda c: c * np.array([k, 1.0]))
        d_km = gs.distance(shapely.Point(lon[i] * k, lat[i])) * np.pi / 180 * EARTH_KM
        outside[i] = d_km > 5
    reason[outside] = "more than 5 km outside own municipality"
    ok = reason == ""
    r5 = pd.DataFrame({"m": p.CD_MUNICIPIO, "la": np.round(lat, 5), "lo": np.round(lon, 5),
                       "nm": p.name_norm})
    shared = r5[ok].groupby(["m", "la", "lo"]).nm.transform("nunique") >= 3
    idx = shared[shared].index
    reason[idx] = "shared default (3+ named places, same point)"
    return reason


def signals(p, reg):
    """Register signals per place. Places with an unusable coordinate get NaN distances."""
    use = (p.coord_reason == "").to_numpy()
    lat, lon = p.lat.to_numpy(), p.lon.to_numpy()
    n = len(p)
    out = pd.DataFrame(index=p.index)
    pts = shapely.points(np.where(use, lon, 0.0), np.where(use, lat, 0.0))
    for nm, (geoms, recs, label) in (("ti", reg["ti"]), ("incra", reg["incra"])):
        tree = shapely.STRtree(geoms)
        pi, gi = tree.query(pts[use], predicate="within")
        idx_use = np.where(use)[0]
        hit = np.zeros(n, bool)
        hit[idx_use[pi]] = True
        name = np.full(n, "", dtype=object)
        s = pd.Series(gi, index=idx_use[pi]).groupby(level=0).first()
        name[s.index.to_numpy()] = recs[label].iloc[s.to_numpy()].to_numpy()
        out[f"in_{nm}"], out[f"{nm}_name"] = hit, name
    for nm in ("li", "lcpi", "lq", "aldeia"):
        dist = np.full(n, np.nan)
        idx = np.full(n, -1)
        dd, ii = reg[nm](lat[use], lon[use])
        dist[use], idx[use] = dd, ii
        out[f"km_{nm}"] = dist
        out[f"idx_{nm}"] = idx
    cd, sit, typ = sector_join(np.where(use, lat, 90.0), np.where(use, lon, 0.0))
    out["sector"], out["sector_sit"], out["sector_type"] = cd, sit, typ
    out.loc[~use, ["sector", "sector_sit", "sector_type"]] = None
    return out


def categorise(p, s, near_km=1.0, text_school=True):
    """Exclusive category of the plan, with its basis. p: places, s: their signals."""
    use = (p.coord_reason == "").to_numpy()
    in_sector = s.sector.notna().to_numpy()
    urban = s.sector_sit.isin(SIT_URBAN).to_numpy()
    t5 = s.sector_type.eq(TYPE_INDIGENOUS).to_numpy()
    t9 = s.sector_type.eq(TYPE_QUILOMBOLA).to_numpy()
    ind = s.in_ti.to_numpy() | t5 | (s.km_li.to_numpy() <= near_km)
    qui = s.in_incra.to_numpy() | t9 | (s.km_lq.to_numpy() <= near_km)
    pri = p.DS_TIPO_LOCAL.eq("Preso provisório").to_numpy() | s.sector_type.eq(TYPE_PRISON).to_numpy()
    txt_ind_school = (p.name_norm.str.contains(TXT_IND, regex=True)
                      & p.name_norm.str.contains(TXT_SCHOOL, regex=True)).to_numpy()
    resolved = use & in_sector
    cat = np.select(
        [pri, ~resolved, ind & (~urban | t5), urban & ~t5 & (ind | (txt_ind_school & text_school)),
         qui & (~urban | t9), ~urban, urban],
        [CAT_PRISON, CAT_UNRES, CAT_VILLAGE, CAT_URBAN_IND, CAT_QUI, CAT_RURAL, CAT_URBAN], CAT_UNRES)
    return pd.Series(cat, index=p.index), pd.Series(ind & resolved, index=p.index)


def basis(p, s, reg_tables):
    """A readable record of which register facts each label rests on."""
    li, lq = reg_tables
    rows = []
    for i in p.index:
        b = []
        if p.at[i, "coord_reason"]:
            b.append(f"coordinate unusable: {p.at[i, 'coord_reason']}")
        else:
            sit = s.at[i, "sector_sit"]
            b.append(f"sector {s.at[i, 'sector']} situation {sit} "
                     f"({'urban' if sit in SIT_URBAN else 'rural or water' if sit else 'none'}) "
                     f"type {s.at[i, 'sector_type']}")
            if s.at[i, "in_ti"]:
                b.append(f"inside FUNAI land {s.at[i, 'ti_name']}")
            if s.at[i, "in_incra"]:
                b.append(f"inside INCRA territory {s.at[i, 'incra_name']}")
            j = s.at[i, "idx_li"]
            b.append(f"nearest IBGE indigenous locality {s.at[i, 'km_li']:.2f} km "
                     f"({li.NM_LI.iat[j]}, sector situation {li.SITUACAO.iat[j]})")
            b.append(f"nearest FUNAI village {s.at[i, 'km_aldeia']:.2f} km")
            j = s.at[i, "idx_lq"]
            b.append(f"nearest IBGE quilombola locality {s.at[i, 'km_lq']:.2f} km ({lq.NM_CQ.iat[j]})")
        b.append(f"official place type {p.at[i, 'DS_TIPO_LOCAL']}")
        rows.append("; ".join(b))
    return pd.Series(rows, index=p.index)


def text_fallback(t):
    """Text-only label for a place without a usable coordinate (lower confidence)."""
    if re.search(TXT_IND, t):
        return CAT_VILLAGE
    if re.search(TXT_QUI, t):
        return CAT_QUI
    if re.search(TXT_RIVER, t) or re.search(TXT_RURAL, t):
        return CAT_RURAL
    return CAT_URBAN


# ---------------------------------------------------------------- statistics
def wilson(k, n, z=1.959964):
    if n == 0:
        return np.nan, np.nan
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def kappa(a, b, c, d):
    """Cohen's kappa from 2x2 cells (a = both yes, d = both no). Works on arrays."""
    n = a + b + c + d
    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    return (po - pe) / (1 - pe)


def require(path):
    if not path.exists():
        raise SystemExit(f"missing {path}: run step 3 first")


def main():
    regs = check_registers()
    write_csv(regs, "m5b_registers.csv")
    log("registers checked")

    li = read_points("ibge/BR_LIs_CD2022_20250919.csv", "LAT", "LONG", ["CD_MUNIC", "NM_LI", "SITUACAO"])
    lcpi = read_points("ibge/BR_LCPIs_CD2022_20250919.csv", "LAT", "LONG", ["CD_MUNIC", "NM_LI"])
    lq = read_points("ibge/BR_LQs_CD2022.csv", "Lat_d", "Long_d", ["CD_MUNIC", "NM_CQ"])
    ti_g, ti_r = read_shp_zip("funai/tis_poligonais_shp.zip")
    al_g, al_r = read_shp_zip("funai/aldeias_pontos_shp.zip")
    qa_g, qa_r = read_shp_zip("incra/areas_de_quilombolas.zip")
    al_xy = np.array([(g.y, g.x) for g in al_g])
    reg = {"ti": (ti_g, ti_r, "terrai_nom"), "incra": (qa_g, qa_r, "nm_comunid"),
           "li": Nearest(li.lat, li.lon), "lcpi": Nearest(lcpi.lat, lcpi.lon), "lq": Nearest(lq.lat, lq.lon),
           "aldeia": Nearest(al_xy[:, 0], al_xy[:, 1])}
    counts = pd.DataFrame([
        {"register": "IBGE indigenous localities (LI)", "features": len(li)},
        {"register": "IBGE places of concentration of indigenous people (LCPI)", "features": len(lcpi)},
        {"register": "IBGE quilombola localities (LQ)", "features": len(lq)},
        {"register": "FUNAI indigenous lands", "features": len(ti_g)},
        {"register": "FUNAI indigenous villages", "features": len(al_g)},
        {"register": "INCRA quilombola territories", "features": len(qa_g)}])
    log("registers loaded", counts.to_dict("records"))

    mesh = json.load(open(RAW / "ibge_malha_municipios_minima.geojson"))
    mun_geom = {f["properties"]["codarea"]: shapely.make_valid(shape(f["geometry"])) for f in mesh["features"]}
    tse_ibge = municipality_codes()

    # Frame municipalities: IBGE polygon meets a FUNAI land, or holds an IBGE indigenous locality.
    codes = list(mun_geom)
    mtree = shapely.STRtree([mun_geom[c] for c in codes])
    _, hit_mun = mtree.query(ti_g, predicate="intersects")
    frame = {codes[i] for i in np.unique(hit_mun)} | set(li.CD_MUNIC.astype(str))

    P, SEC, SIG = {}, {}, {}
    for year in (2026, 2022):
        p, sec = read_places(year)
        p["coord_reason"] = coordinate_quality(p, mun_geom, tse_ibge)
        P[year], SEC[year] = p, sec
        SIG[year] = signals(p, reg)
        log("signals", year, len(p), "places")

    # Step 2. Coordinate coverage.
    cov = []
    for year, p in P.items():
        for reason, g in p.groupby(p.coord_reason.replace("", "usable")):
            cov.append({"year": year, "group": "all polling places", "coordinate": reason, "places": len(g),
                        "sections": int(g.sections.sum()), "voters": int(g.voters.sum())})
        no_sector = (p.coord_reason == "") & SIG[year].sector.isna()
        cov.append({"year": year, "group": "all polling places", "coordinate": "usable but in no census sector",
                    "places": int(no_sector.sum()), "sections": int(p.sections[no_sector].sum()),
                    "voters": int(p.voters[no_sector].sum())})

    # Step 3. The 2026 zero sections, from votes (definition of the lab: n >= 1, zero for a side).
    sfile = DERIVED / "sections_2026_r2.parquet"
    require(sfile)
    v = pd.read_parquet(sfile, columns=KEY + ["votes_pt", "votes_opp", "n", "QT_APTOS"])
    for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"):
        v[c] = v[c].astype(int)
    v = v[v.n >= 1]
    z = v[(v.votes_pt == 0) | (v.votes_opp == 0)].copy()
    z["zero_for"] = np.where(z.votes_opp == 0, "opp", "pt")
    z = z.merge(SEC[2026][KEY + ["NR_LOCAL_VOTACAO"]], on=KEY, how="left", validate="one_to_one")
    assert z.NR_LOCAL_VOTACAO.notna().all(), "a zero section has no row in the polling-place file"
    p26, s26 = P[2026], SIG[2026]
    cat26, ind26 = categorise(p26, s26)
    cat26_5, ind26_5 = categorise(p26, s26, near_km=5.0)
    pk = p26[PLACE].copy()
    pk["category"], pk["category_5km"], pk["IND"], pk["IND5"] = cat26, cat26_5, ind26, ind26_5
    z = z.merge(pk, on=PLACE, how="left", validate="many_to_one")
    zi = p26.reset_index().merge(z[PLACE].drop_duplicates(), on=PLACE)["index"].to_numpy()
    b = basis(p26.loc[zi], s26.loc[zi], (li, lq))
    zp = p26.loc[zi, PLACE + ["NM_MUNICIPIO", "NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO", "DS_TIPO_LOCAL",
                              "coord_reason", "text_norm", "voters"]].copy()
    zp["register_basis"] = b
    z = z.merge(zp, on=PLACE, how="left", validate="many_to_one")
    z["label"], z["label_basis"], z["confidence"] = z.category, "registers", "high"
    unres = z.category.eq(CAT_UNRES)
    z.loc[unres, "label"] = z.loc[unres, "text_norm"].map(text_fallback)
    z.loc[unres, "label_basis"] = "text only, no usable coordinate"
    z.loc[unres, "confidence"] = "low"
    urb_txt = z.category.eq(CAT_URBAN_IND) & ~z.IND.astype(bool)
    z.loc[urb_txt, "label_basis"] = "registers (urban sector) + text (indigenous school name)"
    # A prison label comes from the TSE's official place type, not from a register.
    z.loc[z.category.eq(CAT_PRISON) & z.DS_TIPO_LOCAL.eq("Preso provisório"), "label_basis"] = "official place type"
    edge = ~unres & (z.category != z.category_5km)
    z.loc[edge, "confidence"] = "medium"
    z.loc[edge, "label_basis"] += "; label changes at 5 km"
    for side in ("opp", "pt"):
        g = p26.reset_index().merge(z.loc[z.zero_for == side, PLACE].drop_duplicates(), on=PLACE)
        for reason, gg in g.groupby(g.coord_reason.replace("", "usable")):
            cov.append({"year": 2026, "group": f"zero-section places, zero for {side}", "coordinate": reason,
                        "places": len(gg), "sections": int(len(z[(z.zero_for == side)
                                                                    & z.coord_reason.replace("", "usable").eq(reason)])),
                        "voters": int(gg.voters.sum())})
    write_csv(pd.DataFrame(cov), "m5b_coordinate_coverage.csv")
    zcols = KEY + ["NR_LOCAL_VOTACAO", "zero_for", "NM_MUNICIPIO", "NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO",
                   "DS_TIPO_LOCAL", "QT_APTOS", "n", "votes_pt", "votes_opp", "coord_reason", "label", "label_basis",
                   "confidence", "category", "category_5km", "IND", "IND5", "register_basis"]
    zpath = PRIV / "zero_sections_2026_external_labels.csv"
    z[zcols].sort_values(["zero_for"] + KEY).to_csv(zpath, index=False)
    log("zero-section labels written", len(z), "sha256", sha256(zpath))
    zc = (z.groupby(["zero_for", "label", "label_basis", "confidence"]).size().rename("sections").reset_index())
    write_csv(zc, "m5b_zero_sections_categories.csv")
    log("\n" + zc.to_string(index=False))

    # Step 4. Place-level samples. The lab's flag is read here, only to draw.
    def draw():
        f = pd.read_parquet(sfile, columns=KEY + ["n", "is_indigenous"])
        for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"):
            f[c] = f[c].astype(int)
        f = f[f.n >= 1].merge(SEC[2026][KEY + ["NR_LOCAL_VOTACAO"]], on=KEY, how="inner")
        t = f.groupby(PLACE).is_indigenous.max().reset_index()
        t = t.merge(p26[PLACE + ["CD_MUN_IBGE"]], on=PLACE, how="left")
        t["frame"] = t.CD_MUN_IBGE.isin(frame)
        rng = np.random.default_rng(SEED)
        a = t[t.is_indigenous].sort_values(PLACE)
        bb = t[~t.is_indigenous & t.frame].sort_values(PLACE)
        sa = a.iloc[np.sort(rng.choice(len(a), N_SAMPLE, replace=False))][PLACE]
        sb = bb.iloc[np.sort(rng.choice(len(bb), N_SAMPLE, replace=False))][PLACE]
        return t, sa, sb

    T, sa, sb = draw()
    p26x = p26.join(s26)
    p26x["category"], p26x["IND"], p26x["IND5"] = cat26, ind26, ind26_5
    p26x = p26x.merge(T[PLACE + ["is_indigenous", "frame"]], on=PLACE, how="inner")
    p26x["usable"] = (p26x.coord_reason == "") & p26x.sector.notna()
    srows = []
    for nm, keys in (("A: text-flagged", sa), ("B: unflagged, frame", sb)):
        g = p26x.merge(keys, on=PLACE)
        g["sample"] = nm
        srows.append(g)
    S = pd.concat(srows, ignore_index=True)
    S[["sample"] + PLACE + ["NM_MUNICIPIO", "NM_LOCAL_VOTACAO", "coord_reason", "category", "IND", "IND5", "in_ti",
       "sector_sit", "sector_type", "km_li", "km_aldeia", "km_lcpi"]].to_csv(PRIV / "text_rule_samples_2026.csv",
                                                                        index=False)

    # Step 5. Agreement of the text rule with the registers.
    rng = np.random.default_rng(SEED + 1)
    N_A = int((T.is_indigenous & T.frame).sum())
    N_B = int((~T.is_indigenous & T.frame).sum())
    res = []
    A = S[(S["sample"] == "A: text-flagged") & S.usable]
    Af = A[A.frame]
    B = S[(S["sample"] == "B: unflagged, frame") & S.usable]
    for thr, col in (("1 km", "IND"), ("5 km", "IND5")):
        kA, nA, kAf, nAf, kB, nB = int(A[col].sum()), len(A), int(Af[col].sum()), len(Af), int(B[col].sum()), len(B)
        pa = rng.beta(kAf + .5, nAf - kAf + .5, 20000)
        pb = rng.beta(kB + .5, nB - kB + .5, 20000)
        rec = N_A * pa / (N_A * pa + N_B * pb)
        kap = kappa(N_A * pa, N_A * (1 - pa), N_B * pb, N_B * (1 - pb))
        lo, hi = wilson(kA, nA)
        res.append({"threshold": thr, "quantity": "precision: share of flagged places with a register signal",
                    "k": kA, "n_places": nA, "estimate": kA / nA, "lo95": lo, "hi95": hi, "interval": "Wilson"})
        lo, hi = wilson(kB, nB)
        res.append({"threshold": thr, "quantity": "share of unflagged frame places with a register signal",
                    "k": kB, "n_places": nB, "estimate": kB / nB, "lo95": lo, "hi95": hi, "interval": "Wilson"})
        pA, pB = kAf / nAf, kB / nB
        res.append({"threshold": thr, "quantity": "recall in frame municipalities", "k": np.nan,
                    "n_places": nAf + nB, "estimate": N_A * pA / (N_A * pA + N_B * pB),
                    "lo95": np.quantile(rec, .025), "hi95": np.quantile(rec, .975),
                    "interval": "Jeffreys posterior draws, strata weighted"})
        res.append({"threshold": thr, "quantity": "Cohen's kappa in frame municipalities", "k": np.nan,
                    "n_places": nAf + nB, "estimate": kappa(N_A * pA, N_A * (1 - pA), N_B * pB, N_B * (1 - pB)),
                    "lo95": np.quantile(kap, .025), "hi95": np.quantile(kap, .975),
                    "interval": "Jeffreys posterior draws, strata weighted"})
        # Municipality cluster bootstrap of the two sample shares.
        for nm, g in (("precision (cluster bootstrap)", A), ("unflagged share (cluster bootstrap)", B)):
            m = g.groupby(["SG_UF", "CD_MUNICIPIO"])[col].agg(["sum", "size"]).to_numpy()
            bs = []
            for _ in range(2000):
                w = m[rng.integers(0, len(m), len(m))]
                bs.append(w[:, 0].sum() / w[:, 1].sum())
            res.append({"threshold": thr, "quantity": nm, "k": int(g[col].sum()), "n_places": len(g),
                        "estimate": g[col].mean(), "lo95": np.quantile(bs, .025), "hi95": np.quantile(bs, .975),
                        "interval": f"municipality cluster bootstrap, {len(m)} municipalities"})
    for nm, g in (("A: text-flagged", A), ("B: unflagged, frame", B)):
        for c, k in g.category.value_counts().items():
            lo, hi = wilson(k, len(g))
            res.append({"threshold": "1 km", "quantity": f"sample {nm}: category {c}", "k": int(k),
                        "n_places": len(g), "estimate": k / len(g), "lo95": lo, "hi95": hi, "interval": "Wilson"})
    res.append({"threshold": "-", "quantity": "sample places without a usable coordinate (left out)",
                "k": int((~S.usable).sum()), "n_places": len(S), "estimate": np.nan, "lo95": np.nan,
                "hi95": np.nan, "interval": "-"})
    res.append({"threshold": "-", "quantity": "sample A places outside frame municipalities", "k": int((~A.frame).sum()),
                "n_places": len(A), "estimate": np.nan, "lo95": np.nan, "hi95": np.nan, "interval": "-"})
    res.append({"threshold": "-", "quantity": "population sizes: flagged in frame (N_A), unflagged in frame (N_B)",
                "k": N_A, "n_places": N_B, "estimate": np.nan, "lo95": np.nan, "hi95": np.nan, "interval": "-"})
    write_csv(pd.DataFrame(res), "m5b_text_rule_samples.csv")
    log("\n" + pd.DataFrame(res).to_string(index=False))

    # Census: every place with a usable coordinate, no sampling error.
    cen = []
    U = p26x[p26x.usable]
    for scope, g in (("all places", U), ("frame municipalities", U[U.frame])):
        t = g.is_indigenous.astype(bool)
        for thr, col in (("1 km", "IND"), ("5 km", "IND5")):
            r = g[col].astype(bool)
            a, bq, c, d = int((t & r).sum()), int((t & ~r).sum()), int((~t & r).sum()), int((~t & ~r).sum())
            cen.append({"scope": scope, "threshold": thr, "flag_and_register": a, "flag_only": bq,
                        "register_only": c, "neither": d, "precision": a / (a + bq), "recall": a / (a + c),
                        "kappa": kappa(a, bq, c, d)})
        rv = g.category.eq(CAT_VILLAGE)
        a, bq, c, d = int((t & rv).sum()), int((t & ~rv).sum()), int((~t & rv).sum()), int((~t & ~rv).sum())
        cen.append({"scope": scope, "threshold": "village category, 1 km", "flag_and_register": a, "flag_only": bq,
                    "register_only": c, "neither": d, "precision": a / (a + bq), "recall": a / (a + c),
                    "kappa": kappa(a, bq, c, d)})
    write_csv(pd.DataFrame(cen), "m5b_text_rule_census.csv")
    fl = (p26x[p26x.is_indigenous].groupby("category").agg(places=("sections", "size"),
                                                           sections=("sections", "sum")).reset_index())
    write_csv(fl, "m5b_text_flagged_places_by_register_category.csv")
    log("\n" + pd.DataFrame(cen).to_string(index=False) + "\n" + fl.to_string(index=False))

    # Step 6. Comparison with the lab's analyst labels, read only now. They are private,
    # so this part is skipped when they are not available.
    lab_file = HANDCHECK / "zero_sections_2026_labels.csv"
    if not lab_file.exists():
        log(f"no analyst labels at {lab_file}: step 6 skipped")
    else:
        lab = pd.read_csv(lab_file)
        lab = lab.rename(columns={f"label_{x}": f"lab_{x}" for x in ("category", "basis", "reason", "confidence")})
        for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"):
            lab[c] = lab[c].astype(int)
        keep = [c for c in ["lab_category", "lab_basis", "lab_reason", "lab_confidence"] if c in lab]
        m = z.merge(lab[KEY + keep], on=KEY, how="left", validate="one_to_one")

        def coarse(c):
            c = str(c).lower()
            if "no indigenous" in c:
                return "rural or riverside"
            if "indig" in c:
                return "indigenous"
            if "quilomb" in c:
                return "quilombola"
            if "pris" in c or "deten" in c:
                return "prison"
            if "rural" in c or "river" in c or "ribeir" in c:
                return "rural or riverside"
            if c == "nan":
                return "missing"
            return "urban or other"

        mine = {CAT_VILLAGE: "indigenous", CAT_URBAN_IND: "indigenous", CAT_QUI: "quilombola", CAT_PRISON: "prison",
                CAT_RURAL: "rural or riverside", CAT_URBAN: "urban or other", CAT_UNRES: "missing"}
        m["lab_coarse"] = m.lab_category.map(coarse)
        m["mine_coarse"] = m.label.map(mine)
        m["agree"] = m.lab_coarse == m.mine_coarse
        agree = (m.groupby(["zero_for", "label", "lab_category", "label_basis"]).size()
                 .rename("sections").reset_index())
        write_csv(agree, "m5b_zero_sections_agreement.csv")
        # The plan: a label whose basis is text is never counted as register agreement.
        # So agreement and kappa use the register-based labels only. Text fallbacks are
        # reported on their own rows.
        m["label_set"] = np.where(m.label_basis.str.startswith("text"), "text fallback (not counted)",
                                  "register-based (counted)")
        summ = (m.groupby(["label_set", "zero_for"])
                .agg(sections=("agree", "size"), agree_coarse=("agree", "sum"),
                     lab_indigenous=("lab_coarse", lambda x: int(x.eq("indigenous").sum())),
                     ext_indigenous=("mine_coarse", lambda x: int(x.eq("indigenous").sum())),
                     ext_village=("label", lambda x: int(x.eq(CAT_VILLAGE).sum())),
                     ext_urban_indigenous_school=("label", lambda x: int(x.eq(CAT_URBAN_IND).sum())))
                .reset_index())
        r = m[m.label_set.eq("register-based (counted)")]
        li_, le_ = r.lab_coarse.eq("indigenous"), r.mine_coarse.eq("indigenous")
        a, bq, c, d = (int((li_ & le_).sum()), int((~li_ & le_).sum()), int((li_ & ~le_).sum()),
                       int((~li_ & ~le_).sum()))
        summ = pd.concat([summ, pd.DataFrame([{
            "label_set": "register-based (counted)", "zero_for": "both sides, indigenous yes or no",
            "sections": len(r), "agree_coarse": a + d, "lab_indigenous": a + c, "ext_indigenous": a + bq,
            "both_indigenous": a, "external_only": bq, "lab_only": c,
            "kappa_indigenous": kappa(a, bq, c, d)}])], ignore_index=True)
        write_csv(summ, "m5b_zero_sections_agreement_summary.csv")
        m[~m.agree | m.label.eq(CAT_URBAN_IND)][zcols + keep + ["lab_coarse", "mine_coarse"]].to_csv(
            PRIV / "zero_sections_2026_disagreements.csv", index=False)
        log("\n" + summ.to_string(index=False) + "\n" + agree.to_string(index=False))

    # Step 7. Panel 2022 to 2026 with the register definition (the lab's match key).
    cat22, ind22 = categorise(P[2022], SIG[2022])
    SS = {}
    for year, cat, ind in ((2026, cat26, ind26), (2022, cat22, ind22)):
        f = DERIVED / f"sections_{year}_r2.parquet"
        require(f)
        d = pd.read_parquet(f, columns=KEY + ["NM_LOCAL_VOTACAO", "votes_pt", "votes_opp", "n", "is_indigenous"])
        for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"):
            d[c] = d[c].astype(int)
        d = d[d.n >= 1].merge(SEC[year][KEY + ["NR_LOCAL_VOTACAO"]], on=KEY, how="left")
        pp = P[year][PLACE].copy()
        pp["reg_village"], pp["reg_ind"] = cat.eq(CAT_VILLAGE).to_numpy(), ind.to_numpy()
        pp["register_category"] = cat.to_numpy()
        d = d.merge(pp, on=PLACE, how="left")
        d[["reg_village", "reg_ind"]] = d[["reg_village", "reg_ind"]].fillna(False).astype(bool)
        d["register_category"] = d.register_category.fillna(CAT_UNRES)
        # Per-section register category, read by steps 6 (reweighting) and 8 (category
        # table). register_label equals it, except that a 2026 zero section takes its
        # final label from part 3 (text fallback where no coordinate is usable).
        out = d[KEY + ["register_category", "reg_village"]].copy()
        out["register_label"] = out.register_category
        if year == 2026:
            lbl = out[KEY].merge(z[KEY + ["label"]], on=KEY, how="left")["label"]
            out["register_label"] = lbl.fillna(out.register_category).to_numpy()
        out.to_parquet(DERIVED / f"register_categories_{year}.parquet")
        d["place_name_norm"] = d.NM_LOCAL_VOTACAO.fillna("").map(norm)
        SS[year] = d
    keys = ["SG_UF", "CD_MUNICIPIO", "place_name_norm"]
    panel = []
    for flag in ("reg_village", "reg_ind", "is_indigenous"):
        fl = {y: set(map(tuple, SS[y].loc[SS[y][flag].astype(bool), keys].drop_duplicates().to_numpy()))
              for y in SS}
        both = fl[2026] & fl[2022]
        for y, d in SS.items():
            mask = d[keys].apply(tuple, axis=1).isin(both) & d[flag].astype(bool)
            g = d[mask]
            # Place-cluster bootstrap of the zero rate (Poisson weights per place, as in the lab).
            pz = g.assign(z=(g.votes_opp == 0).astype(int)).groupby(PLACE).z.agg(["sum", "size"]).to_numpy()
            w = np.random.default_rng(SEED + 2).poisson(1.0, (2000, len(pz)))
            bs = (w @ pz[:, 0]) / np.maximum(w @ pz[:, 1], 1)
            panel.append({"definition": {"reg_village": "register: indigenous village or community",
                                         "reg_ind": "register signal IND (any situation)",
                                         "is_indigenous": "lab text flag (for comparison)"}[flag],
                          "year": y, "places_in_both_years": len(both), "sections": len(g),
                          "zero_opp": int((g.votes_opp == 0).sum()), "zero_pt": int((g.votes_pt == 0).sum()),
                          "zero_rate_opp": (g.votes_opp == 0).mean() if len(g) else np.nan,
                          "zero_rate_opp_lo95": np.quantile(bs, .025), "zero_rate_opp_hi95": np.quantile(bs, .975),
                          "zero_rate_pt": (g.votes_pt == 0).mean() if len(g) else np.nan,
                          "pooled_share_opp": g.votes_opp.sum() / g.n.sum() if len(g) else np.nan})
    write_csv(pd.DataFrame(panel), "m5b_panel_2022_2026.csv")
    log("\n" + pd.DataFrame(panel).to_string(index=False))
    write_csv(counts, "m5b_register_feature_counts.csv")
    log("done")


if __name__ == "__main__":
    main()
