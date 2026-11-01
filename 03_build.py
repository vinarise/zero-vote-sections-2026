"""Step 3. Build one section table per year and round for President.

Output DERIVED/sections_<year>_r<round>.parquet with, per section:
  key, region, electorate, turnout, nominal, blank, null,
  votes_pt, votes_opp (the two runoff candidates by side), n = votes_pt + votes_opp,
  polling-place id, name, address, official place type, inferred place flags.
Also writes results/candidates.csv with the names read from the data.

Place flags (v2, after a full recheck on 2026-10-29, items M4 and M5):
  - The official place type is used. is_prison = DS_TIPO_LOCAL "Preso provisório".
  - The indigenous flag is rebuilt (rules below) and kept per text field, so a flag
    that comes only from the district label can be separated across years.
  - The v1 flags are kept as *_v1 columns, so every v1 number can be reproduced.
  - Quilombola is its own inferred flag. It stays inside the rural composite.
All place flags except prison are INFERRED from text. They are not official categories.
"""
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BALLOT, DERIVED, KEY, REGION, write_csv  # noqa: E402

# v1 patterns, unchanged except that groups are non-capturing, on place name +
# address + district. Kept so the v1 counts can be reproduced and compared.
PAT_V1 = {
    "indigenous": r"\bALDEIA|INDIGENA|\bINDIOS?\b|TERRA IND|\bETNIA\b|\bPOLO BASE\b",
    "river": r"IGARAPE|RIBEIRINH|\bRESEX\b|EXTRATIVISTA|MARGEM (?:DIREITA|ESQUERDA)|\bFURO\b"
             r"|\bRIO\b.*\b(?:COMUNIDADE|LOCALIDADE|ALDEIA)\b|\b(?:COMUNIDADE|LOCALIDADE)\b.*\bRIO\b",
    "rural": r"ZONA RURAL|\bSITIO\b|\bFAZENDA\b|\bPOVOADO\b|ASSENTAMENTO|\bLINHA\b|\bLOCALIDADE\b"
             r"|\bCOMUNIDADE\b|\bDISTRITO\b|\bGLEBA\b|QUILOMB|\bRAMAL\b|\bVICINAL\b|\bSERINGAL\b"
             r"|\bCORREGO\b|\bINTERIOR\b|\bAGROVILA\b|\bCOLONIA\b",
    "school": r"ESCOLA|\bESC\b|\bE M\b|\bE E\b|\bU E\b|\bUE\b|\bEMEF|\bEMEI|\bEMEB|\bEEEF|\bEEF\b"
              r"|COLEGIO|GRUPO ESCOLAR|UNIDADE ESCOLAR|CRECHE|EDUCACIONAL|INSTITUTO|UNIVERSIDADE"
              r"|FACULDADE|\bEMEIEF|\bEEIEF|ENSINO",
}

# v2 indigenous rules, applied to each text field separately.
#  1. Strong words: INDIGENA and its misspellings and truncations (INDIGINA, INDIGE),
#     "terra / território indígena", ETNIA, POLO BASE (indigenous health post),
#     TEKOA / TEKOHA (Guarani for village), MBYA, KARAI.
#  2. ALDEIA ("village") followed by a proper name ("ALDEIA <name>"). Dropped:
#     ALDEIA after an urban or generic word ("JARDIM DA ALDEIA", "PARQUE ALDEIA",
#     "RUA ... DA ALDEIA", "POVOADO ALDEIA"), ALDEIA followed by a preposition
#     ("ALDEIA DE ...", "ALDEIA DA SERRA", "ALDEIAS INFANTIS") and a bare ALDEIA
#     district. These are urban neighbourhoods, streets and institutions.
#  3. MALOCA in Roraima only, where it names indigenous communities. Elsewhere it is
#     also an ordinary word.
#  4. The acronym EEIEF in Rio Grande do Sul only, where it names state indigenous
#     schools. In Ceará the same acronym names infant and primary schools (312 sections).
#  Dropped from v1: bare INDIO / INDIOS. It matched people, towns and rivers named
#  with the word, for example schools named after a person called Índio.
#  Not used: a list of ethnonyms (names of peoples). Tested on 2026 it matched
#  streets and urban districts named after peoples, so it would add more false
#  positives than it removes misses.
#  These rules were fixed before the precision sample in 09_classifier_check.py was
#  drawn, and were not tuned on it.
STRONG = (r"\bINDIG[EI]|\bTERRA IND|\bTERRITORIO IND|\bETNIA\b|\bPOLO BASE\b|\bTEKO[AH]|\bMBYA\b"
          r"|\bKARAI\b")
URBAN_ALDEIA = (r"\b(?:JARDIM|PARQUE|RESIDENCIAL|CONDOMINIO|LOTEAMENTO|RUA|R|AVENIDA|AV|TRAVESSA|PORTO"
                r"|PASSO|PONTE|POVOADO|SAO PEDRO|VILA|CHACARAS?|SITIO)(?: D[AEO]S?)? ALDEIAS?\b")
ALDEIA_NAMED = r"\bALDEIAS? (?!(?:D[AEO]S?|VELHA|PARQUE|INFANTIS|UNIDADE|ZONA)\b)[A-Z]"
QUILOMBOLA = r"QUILOMB"
RURAL_V2 = PAT_V1["rural"] + r"|\bRURAL\b|\bMALOCA\b"
PRISON_BY_NAME = (r"PRESIDIO|PENITENCIARI|CADEIA PUBLICA|CENTRO DE DETENCAO|\bCDP\b|UNIDADE PRISIONAL"
                  r"|RESSOCIALIZACAO|SOCIOEDUCATIV|CENTRO DE INTERNACAO|CASA DE CUSTODIA|\bCOLONIA PENAL")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"[.\-/,;:()]", " ", s.upper())
    return re.sub(r"\s+", " ", s).strip()


def indigenous_field(t, uf):
    """v2 indigenous rule on one normalised text field."""
    strong = t.str.contains(STRONG, regex=True)
    stripped = t.str.replace(URBAN_ALDEIA, " ", regex=True)
    aldeia = stripped.str.contains(ALDEIA_NAMED, regex=True)
    maloca = (uf == "RR") & t.str.contains(r"\bMALOCA\b", regex=True)
    eeief = (uf == "RS") & t.str.contains(r"\bEEIEF\b", regex=True)
    return strong | aldeia | maloca | eeief


def flags(s):
    nm = s.NM_LOCAL_VOTACAO.map(norm)
    ad = s.DS_LOCAL_VOTACAO_ENDERECO.map(norm)
    ba = s.NM_BAIRRO.map(norm)
    t = nm + " | " + ad + " | " + ba
    out = {f"is_{k}_v1": t.str.contains(p, regex=True) for k, p in PAT_V1.items()}
    out["is_indig_rural_river_v1"] = out["is_indigenous_v1"] | out["is_river_v1"] | out["is_rural_v1"]
    uf = s.SG_UF
    out["ind_name"] = indigenous_field(nm, uf)
    out["ind_address"] = indigenous_field(ad, uf)
    out["ind_district"] = indigenous_field(ba, uf)
    out["district_is_zona_rural_indigena"] = ba.eq("ZONA RURAL INDIGENA")
    out["is_indigenous"] = out["ind_name"] | out["ind_address"] | out["ind_district"]
    out["ind_district_only"] = out["ind_district"] & ~out["ind_name"] & ~out["ind_address"]
    out["is_quilombola"] = t.str.contains(QUILOMBOLA, regex=True)
    out["is_river"] = out["is_river_v1"]
    out["is_rural"] = t.str.contains(RURAL_V2, regex=True)
    out["is_school"] = out["is_school_v1"]
    out["is_prison"] = s.DS_TIPO_LOCAL.eq("Preso provisório")
    out["is_prison_by_name"] = nm.str.contains(PRISON_BY_NAME, regex=True)
    out["is_indig_rural_river"] = out["is_indigenous"] | out["is_river"] | out["is_rural"]
    f = pd.DataFrame(out, index=s.index)
    # One exclusive inferred category, in this order of priority.
    f["place_category"] = np.select(
        [f.is_prison, f.is_indigenous, f.is_quilombola, f.is_river, f.is_rural],
        ["prison (official type)", "indigenous (inferred)", "quilombola (inferred)",
         "river (inferred)", "rural (inferred)"], "other")
    f["place_name_norm"] = nm
    return f


def build(year, rnd):
    v = pd.read_parquet(DERIVED / f"votes_{year}.parquet")
    d = pd.read_parquet(DERIVED / f"detail_{year}.parquet")
    v = v[v.NR_TURNO == rnd]
    d = d[d.NR_TURNO == rnd].copy()
    assert not d.duplicated(KEY).any(), "duplicate section keys in detail"

    sides = BALLOT[year]
    names = {}
    for side, num in sides.items():
        nm = v.loc[v.NR_VOTAVEL == num, "NM_VOTAVEL"].unique()
        names[side] = nm[0] if len(nm) else "?"
    cand = v[v.NR_VOTAVEL.isin(sides.values())]
    wide = cand.pivot_table(index=KEY, columns="NR_VOTAVEL", values="QT_VOTOS",
                            aggfunc="sum", fill_value=0)
    wide = wide.rename(columns={sides["pt"]: "votes_pt", sides["opp"]: "votes_opp"})
    for c in ("votes_pt", "votes_opp"):
        if c not in wide:
            wide[c] = 0
    wide = wide[["votes_pt", "votes_opp"]].reset_index()

    # Section universe = detail file. A missing candidate row means zero votes.
    s = d.merge(wide, on=KEY, how="left", validate="one_to_one")
    s[["votes_pt", "votes_opp"]] = s[["votes_pt", "votes_opp"]].fillna(0).astype("int64")
    orphan = wide.merge(d[KEY], on=KEY, how="left", indicator=True)
    n_orphan = int((orphan["_merge"] == "left_only").sum())

    s["n"] = s.votes_pt + s.votes_opp
    s["region"] = s.SG_UF.map(REGION)
    assert s.region.notna().all()

    # Polling-place text. Prefer the detail file's columns, else the votes file's.
    if "NM_LOCAL_VOTACAO" not in s or (s.get("NM_LOCAL_VOTACAO", "") == "").all():
        loc = v.drop_duplicates(KEY)[KEY + ["NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO",
                                            "DS_LOCAL_VOTACAO_ENDERECO"]]
        s = s.drop(columns=[c for c in ["NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO",
                                        "DS_LOCAL_VOTACAO_ENDERECO"] if c in s])
        s = s.merge(loc, on=KEY, how="left")
    s["NM_LOCAL_VOTACAO"] = s["NM_LOCAL_VOTACAO"].fillna("")
    s["DS_LOCAL_VOTACAO_ENDERECO"] = s["DS_LOCAL_VOTACAO_ENDERECO"].fillna("")

    # Official place type and district/neighbourhood from the polling-place register.
    pfile = DERIVED / f"places_{year}.parquet"
    if pfile.exists():
        p = pd.read_parquet(pfile)
        if "NR_TURNO" in p:
            p = p[p.NR_TURNO.astype(int) == rnd] if (p.NR_TURNO.astype(int) == rnd).any() else p
        if "DS_TIPO_SECAO_AGREGADA" in p:
            p = p[p.DS_TIPO_SECAO_AGREGADA.str.upper().str.startswith("PRINC")]
        for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"):
            p[c] = p[c].astype(int)
        keep = [c for c in ["DS_TIPO_LOCAL", "NM_BAIRRO", "DS_ENDERECO", "NR_LATITUDE",
                            "NR_LONGITUDE", "QT_ELEITOR_SECAO"] if c in p]
        p = p.drop_duplicates(KEY)[KEY + keep]
        s = s.merge(p, on=KEY, how="left")
    for c in ("DS_TIPO_LOCAL", "NM_BAIRRO"):
        if c not in s:
            s[c] = ""
        s[c] = s[c].fillna("")

    s = s.reset_index(drop=True)
    s = pd.concat([s, flags(s)], axis=1)
    s["year"], s["round"] = year, rnd
    s.to_parquet(DERIVED / f"sections_{year}_r{rnd}.parquet")
    return {"year": year, "round": rnd, "pt_number": sides["pt"], "pt_name": names["pt"],
            "opp_number": sides["opp"], "opp_name": names["opp"], "sections": len(s),
            "vote_rows_without_detail_section": n_orphan}


if __name__ == "__main__":
    rows = [build(y, r) for y in (2026, 2022, 2018) for r in (1, 2)]
    write_csv(pd.DataFrame(rows), "candidates.csv")
    print(pd.DataFrame(rows).to_string())
