"""Settings shared by every step: where data lives, keys, regions, candidates.

Data location. Set ZV_DATA_DIR to any directory with about 10 GB free. It
defaults to ./data next to this file. Inside it:
  raw/       the public TSE and IBGE source files, as downloaded
  registers/ the outside registers used by step 11 (IBGE, FUNAI, INCRA)
  derived/   intermediate tables (Parquet), rebuilt by every run
  private/   section-level lists and the analyst labels. Never publish these.
Published outputs go to results/ and interactive/ next to this file.
"""
import functools
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("ZV_DATA_DIR", HERE / "data")).resolve()
RAW = DATA / "raw"
DERIVED = DATA / "derived"
PRIVATE = DATA / "private"
HANDCHECK = Path(os.environ.get("ZV_LABELS_DIR", PRIVATE / "labels")).resolve()  # analyst labels
REGISTERS = Path(os.environ.get("ZV_REGISTERS_DIR", DATA / "registers")).resolve()  # outside registers
RES = HERE / "results"
INTERACTIVE = HERE / "interactive"
for d in (RAW, DERIVED, PRIVATE, RES):
    d.mkdir(parents=True, exist_ok=True)

KEY = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO"]          # one section
MUN = ["SG_UF", "CD_MUNICIPIO"]                                   # one municipality
PLACE = ["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO"]  # one polling place
YEARS = (2026, 2022, 2018)
SIDES = ("pt", "opp")
SEED = 20261029

# Ballot numbers of the two runoff candidates, by side. Names are read from the data.
BALLOT = {2026: {"pt": 13, "opp": 22}, 2022: {"pt": 13, "opp": 22}, 2018: {"pt": 13, "opp": 17}}

REGION = {
    **dict.fromkeys(["AC", "AM", "AP", "PA", "RO", "RR", "TO"], "North"),
    **dict.fromkeys(["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"], "Northeast"),
    **dict.fromkeys(["DF", "GO", "MS", "MT"], "Center-West"),
    **dict.fromkeys(["ES", "MG", "RJ", "SP"], "Southeast"),
    **dict.fromkeys(["PR", "RS", "SC"], "South"),
    "ZZ": "Abroad",
}

# Floats are written with 10 significant digits, so output hashes do not depend
# on the last bits of floating-point arithmetic.
FLOAT_FORMAT = "%.10g"


def write_csv(df, name, private=False, **kw):
    """Write a table to results/ (published) or to the private data folder."""
    path = (PRIVATE if private else RES) / name
    df.to_csv(path, index=kw.pop("index", False), float_format=FLOAT_FORMAT, **kw)
    return path


@functools.lru_cache(maxsize=None)
def cand_name(year, side):
    """Runoff candidate name for a side, as written in the TSE votes file."""
    import pandas as pd
    c = pd.read_csv(RES / "candidates.csv")
    return c[(c.year == year) & (c["round"] == 2)].iloc[0][f"{side}_name"]
