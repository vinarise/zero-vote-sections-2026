"""Step 2. Load the raw TSE files into compact Parquet tables (President only).

Outputs in DERIVED:
  votes_<year>.parquet    one row per (round, section, votable) for President
  detail_<year>.parquet   one row per (round, section) for President
  places_<year>.parquet   polling-place register (2026, 2022, 2018)
  munzona_<year>.parquet  published municipal and zone totals for President
"""
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DERIVED, KEY, RAW  # noqa: E402


def read_csv_from_zip(zpath, member, usecols, chunksize=2_000_000, filt=None):
    """Stream one CSV member of a zip, keep usecols that exist, apply filt."""
    with zipfile.ZipFile(zpath) as z:
        with z.open(member) as fh:
            head = fh.readline().decode("latin1").strip().split(";")
        cols = [c.strip('"') for c in head]
        keep = [c for c in usecols if c in cols]
        out = []
        with z.open(member) as fh:
            for ch in pd.read_csv(io.TextIOWrapper(fh, encoding="latin1"), sep=";",
                                  usecols=keep, dtype=str, chunksize=chunksize,
                                  na_filter=False):
                if filt is not None:
                    ch = ch[filt(ch)]
                out.append(ch)
    return pd.concat(out, ignore_index=True), cols


def members(zpath):
    with zipfile.ZipFile(zpath) as z:
        return [m for m in z.namelist() if m.lower().endswith(".csv")]


def to_int(df, cols):
    for c in cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="raise").astype("int64")
    return df


def load_votes(year):
    z = RAW / f"votacao_secao_{year}_BR.zip"
    m = [x for x in members(z) if x.endswith(f"{year}_BR.csv")][0]
    use = ["NR_TURNO", *KEY, "NM_MUNICIPIO", "CD_CARGO", "NR_VOTAVEL", "NM_VOTAVEL",
           "QT_VOTOS", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_LOCAL_VOTACAO_ENDERECO"]
    df, cols = read_csv_from_zip(z, m, use, filt=lambda d: d["CD_CARGO"] == "1")
    df = to_int(df, ["NR_TURNO", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO",
                     "NR_VOTAVEL", "QT_VOTOS", "NR_LOCAL_VOTACAO"])
    df.to_parquet(DERIVED / f"votes_{year}.parquet")
    print(year, "votes", len(df), sorted(df.NR_TURNO.unique()), file=sys.stderr)


def load_detail(year):
    z = RAW / f"detalhe_votacao_secao_{year}.zip"
    ms = members(z)
    # Prefer the national presidential member when it exists, else all UF files.
    br = [x for x in ms if x.endswith(f"{year}_BR.csv")]
    ms = br if br else [x for x in ms if "BRASIL" not in x]
    use = ["NR_TURNO", *KEY, "NM_MUNICIPIO", "CD_CARGO", "QT_APTOS", "QT_COMPARECIMENTO",
           "QT_ABSTENCOES", "QT_VOTOS_NOMINAIS", "QT_VOTOS_BRANCOS", "QT_VOTOS_NULOS",
           "QT_VOTOS_LEGENDA", "QT_VOTOS_ANULADOS_APU_SEP", "QT_VOTOS_ANULADOS",
           "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_LOCAL_VOTACAO_ENDERECO",
           "DS_ORIGEM_VOTO", "ST_SECAO_INSTALADA", "ST_SECAO_ANULADA", "DS_MODELO_URNA"]
    parts = []
    for m in ms:
        df, _ = read_csv_from_zip(z, m, use, filt=lambda d: d["CD_CARGO"] == "1")
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    num = [c for c in df.columns if c.startswith("QT_")] + [
        "NR_TURNO", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "CD_CARGO", "NR_LOCAL_VOTACAO"]
    df = to_int(df, num)
    df.to_parquet(DERIVED / f"detail_{year}.parquet")
    print(year, "detail", len(df), "members", ms, file=sys.stderr)


def load_places(year):
    z = RAW / f"eleitorado_local_votacao_{year}.zip"
    ms = members(z)
    br = [x for x in ms if "BRASIL" in x]
    ms = br if br else ms
    use = ["NR_TURNO", *KEY, "NM_MUNICIPIO", "DS_TIPO_SECAO_AGREGADA", "NR_SECAO_PRINCIPAL",
           "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "CD_TIPO_LOCAL", "DS_TIPO_LOCAL",
           "DS_ENDERECO", "NM_BAIRRO", "NR_LATITUDE", "NR_LONGITUDE", "DS_SITU_LOCALIDADE",
           "DS_SITU_SECAO", "QT_ELEITOR_SECAO", "QT_ELEITOR", "QT_ELEITOR_ELEICAO_FEDERAL"]
    parts = []
    for m in ms:
        df, _ = read_csv_from_zip(z, m, use)
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(DERIVED / f"places_{year}.parquet")
    print(year, "places", len(df), list(df.columns), file=sys.stderr)


def load_munzona(year):
    z = RAW / f"votacao_candidato_munzona_{year}.zip"
    ms = members(z)
    br = [x for x in ms if x.endswith(f"{year}_BR.csv")]
    ms = br if br else [x for x in ms if "BRASIL" not in x]
    use = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "CD_CARGO",
           "NR_CANDIDATO", "NM_URNA_CANDIDATO", "QT_VOTOS_NOMINAIS",
           "QT_VOTOS_NOMINAIS_VALIDOS", "ST_VOTO_EM_TRANSITO"]
    parts = []
    for m in ms:
        df, _ = read_csv_from_zip(z, m, use, filt=lambda d: d["CD_CARGO"] == "1")
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    df = to_int(df, ["NR_TURNO", "CD_MUNICIPIO", "NR_ZONA", "CD_CARGO", "NR_CANDIDATO",
                     "QT_VOTOS_NOMINAIS", "QT_VOTOS_NOMINAIS_VALIDOS"])
    df.to_parquet(DERIVED / f"munzona_{year}.parquet")
    print(year, "munzona", len(df), "members", ms, file=sys.stderr)


if __name__ == "__main__":
    # usage: 02_load.py [year ...] [table ...]   (defaults: all years, all tables)
    years = [int(a) for a in sys.argv[1:] if a.isdigit()] or [2026, 2022, 2018]
    what = [a for a in sys.argv[1:] if not a.isdigit()] or ["votes", "detail", "places", "munzona"]
    for year in years:
        for w in what:
            globals()[f"load_{w}"](year)
