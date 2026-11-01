"""Step 5. Question 6: consistency checks between public files.

These files are all published by the TSE and derived from one totalisation
database. Agreement between them is expected by construction. A pass shows the
published files are consistent with each other. It does not show that a bulletin
records what voters typed, and it does not authenticate any file.

1. SHA-512 of each round-2 bulletin zip against the hash file the TSE publishes
   next to it on the same CDN. This shows the download is intact. It does not
   show the content is authentic, because the hash comes from the same server.
2. Bulletin (bweb_2t) vs section file, per section and per votable, 2026 round 2.
   Also electorate and turnout per section, bulletin vs section-detail file.
3. Turnout above electorate in any section (all three years, round 2).
4. Sum of sections vs published municipal-zone totals (all three years, round 2).
5. Sum of sections vs the national totalization report (2026 round 2).
Writes aggregate results to results/consistency_*.csv. Any per-section difference
list goes to the private data folder (they are all empty in the reference run).
The checks NOT run are listed in results/consistency_checks_not_run.csv.
Needs the pdftotext command (poppler-utils) for check 5.
"""
import hashlib
import io
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DERIVED, KEY, RAW, write_csv  # noqa: E402
summary = []


def note(check, result, detail=""):
    summary.append({"check": check, "result": result, "detail": detail})
    print(f"{check}: {result} {detail}")


# 1. Hashes
rows = []
for z in sorted(RAW.glob("bweb_2t_*.zip")):
    expected = (RAW / (z.name + ".sha512")).read_text().split()[0].lower()
    h = hashlib.sha512()
    with open(z, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    rows.append({"file": z.name, "sha512_published": expected, "sha512_computed": h.hexdigest(),
                 "match": expected == h.hexdigest()})
hashes = pd.DataFrame(rows)
write_csv(hashes, "consistency_sha512.csv")
note("bulletin zip SHA-512 matches the hash file on the same CDN (download intact, not authenticity)",
     f"{hashes.match.sum()}/{len(hashes)}")

# 2. Bulletins vs section file
use = KEY + ["NR_TURNO", "CD_CARGO_PERGUNTA", "NR_VOTAVEL", "QT_VOTOS", "QT_APTOS",
             "QT_COMPARECIMENTO", "DS_TIPO_URNA"]
parts = []
for z in sorted(RAW.glob("bweb_2t_*.zip")):
    with zipfile.ZipFile(z) as zz:
        m = [x for x in zz.namelist() if x.lower().endswith(".csv")][0]
        with zz.open(m) as fh:
            df = pd.read_csv(io.TextIOWrapper(fh, encoding="latin1"), sep=";", usecols=use,
                             dtype=str, na_filter=False)
    parts.append(df[df.CD_CARGO_PERGUNTA == "1"])
bu = pd.concat(parts, ignore_index=True)
for c in ["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_TURNO", "NR_VOTAVEL", "QT_VOTOS",
          "QT_APTOS", "QT_COMPARECIMENTO"]:
    bu[c] = bu[c].astype(int)
assert (bu.NR_TURNO == 2).all()
note("bulletin rows for President, round 2", len(bu),
     "urn types: " + "; ".join(f"{k}={v}" for k, v in bu.drop_duplicates(KEY).DS_TIPO_URNA
                                 .value_counts().items()))

bu_votes = bu.groupby(KEY + ["NR_VOTAVEL"]).QT_VOTOS.sum().rename("bu_votes")
v = pd.read_parquet(DERIVED / "votes_2026.parquet")
v = v[v.NR_TURNO == 2]
sec_votes = v.groupby(KEY + ["NR_VOTAVEL"]).QT_VOTOS.sum().rename("sec_votes")
cmp = pd.concat([bu_votes, sec_votes], axis=1).fillna(0).astype(int).reset_index()
diff = cmp[cmp.bu_votes != cmp.sec_votes]
write_csv(diff, "consistency_bulletin_vs_section_diffs.csv", private=True)
n_sec_bu = bu[KEY].drop_duplicates().shape[0]
d = pd.read_parquet(DERIVED / "detail_2026.parquet")
d = d[d.NR_TURNO == 2]
note("sections in bulletins / sections in detail file", f"{n_sec_bu} / {len(d)}",
     f"sections in detail not in bulletins: {len(d) - d.merge(bu[KEY].drop_duplicates(), on=KEY).shape[0]}")
note("(section, votable) pairs compared", len(cmp), f"pairs that differ: {len(diff)}")

# Electorate and turnout, bulletin vs detail
bu_sec = bu.drop_duplicates(KEY)[KEY + ["QT_APTOS", "QT_COMPARECIMENTO", "DS_TIPO_URNA"]]
m = d.merge(bu_sec, on=KEY, how="outer", suffixes=("_det", "_bu"), indicator=True)
only = m[m["_merge"] != "both"]
only[KEY + ["_merge", "QT_APTOS_det", "QT_COMPARECIMENTO_det", "DS_ORIGEM_VOTO",
            "ST_SECAO_INSTALADA"]].pipe(write_csv, "consistency_sections_missing_from_one_file.csv",
                                        private=True)
# Describe the sections with no bulletin row (added in v2).
nb = only.assign(abroad=only.SG_UF.eq("ZZ"))
(nb.groupby(["abroad", "DS_ORIGEM_VOTO", "ST_SECAO_INSTALADA"])
   .agg(sections=("NR_SECAO", "size"), turnout=("QT_COMPARECIMENTO_det", "sum"),
        electorate=("QT_APTOS_det", "sum"))
   .reset_index().pipe(write_csv, "consistency_sections_without_bulletin.csv"))
note("sections without a bulletin row that are abroad", f"{int(nb.abroad.sum())}/{len(nb)}",
     f"installed: {int(nb.ST_SECAO_INSTALADA.eq('Sim').sum())}; total turnout: "
     f"{int(nb.QT_COMPARECIMENTO_det.sum())}")
both = m[m["_merge"] == "both"]
bad = both[(both.QT_APTOS_det != both.QT_APTOS_bu) |
           (both.QT_COMPARECIMENTO_det != both.QT_COMPARECIMENTO_bu)]
write_csv(bad, "consistency_electorate_turnout_diffs.csv", private=True)
note("sections where electorate or turnout differ, bulletin vs detail", len(bad))
note("sections present in only one of bulletin/detail", len(only),
     "; ".join(f"{k}={v}" for k, v in only["_merge"].value_counts().items() if v)
     + " | detail origin of those: "
     + "; ".join(f"{k}={v}" for k, v in only.DS_ORIGEM_VOTO.fillna("n/a").value_counts().items()))

# Totals of the four votables, bulletins vs section file
tot = cmp.groupby("NR_VOTAVEL")[["bu_votes", "sec_votes"]].sum()
write_csv(tot, "consistency_bulletin_vs_section_totals.csv", index=True)
print(tot)

# 3. Turnout above electorate, and ballot arithmetic, round 2 of each year
for year in (2026, 2022, 2018):
    dd = pd.read_parquet(DERIVED / f"detail_{year}.parquet")
    dd = dd[dd.NR_TURNO == 2]
    over = dd[dd.QT_COMPARECIMENTO > dd.QT_APTOS]
    write_csv(over, f"consistency_turnout_over_electorate_{year}.csv", private=True)
    s = pd.read_parquet(DERIVED / f"sections_{year}_r2.parquet")
    arith = s[s.QT_COMPARECIMENTO != s.n + s.QT_VOTOS_BRANCOS + s.QT_VOTOS_NULOS]
    write_csv(arith, f"consistency_ballot_arithmetic_{year}.csv", private=True)
    note(f"{year} R2 sections with turnout > electorate", len(over), f"of {len(dd)}")
    note(f"{year} R2 sections where turnout != valid + blank + null", len(arith))

# 4. Sum of sections vs published municipal-zone totals
for year in (2026, 2022, 2018):
    mz = pd.read_parquet(DERIVED / f"munzona_{year}.parquet")
    mz = mz[mz.NR_TURNO == 2]
    pub = mz.groupby(["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_CANDIDATO"]) \
        .QT_VOTOS_NOMINAIS.sum().rename("published")
    vv = pd.read_parquet(DERIVED / f"votes_{year}.parquet")
    vv = vv[(vv.NR_TURNO == 2) & vv.NR_VOTAVEL.isin(mz.NR_CANDIDATO.unique())]
    ss = vv.groupby(["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_VOTAVEL"]).QT_VOTOS.sum() \
        .rename("sum_of_sections")
    ss.index = ss.index.set_names("NR_CANDIDATO", level=3)
    c = pd.concat([pub, ss], axis=1).fillna(0).astype(int).reset_index()
    dz = c[c.published != c.sum_of_sections]
    write_csv(dz, f"consistency_munzona_diffs_{year}.csv")
    cm = c.groupby(["SG_UF", "CD_MUNICIPIO", "NR_CANDIDATO"])[["published", "sum_of_sections"]].sum()
    note(f"{year} R2 (municipality, zone, candidate) cells: sum of sections vs published",
         f"{len(c)} cells, {len(dz)} differ",
         f"municipality level differ: {(cm.published != cm.sum_of_sections).sum()}; "
         "national published by candidate: "
         + ", ".join(f"{k}={int(v)}" for k, v in c.groupby("NR_CANDIDATO").published.sum().items())
         + ". Sum of sections: "
         + ", ".join(f"{k}={int(v)}" for k, v in c.groupby("NR_CANDIDATO").sum_of_sections.sum().items()))

# 5. National totalization report, 2026 round 2
pdf = DERIVED / "pdf" / "6258_BR_BRASIL_2026_T2_PRESIDENTE.pdf"
if not pdf.exists():
    with zipfile.ZipFile(RAW / "Relatorio_Resultado_Totalizacao_2026_BR.zip") as zz:
        zz.extract(pdf.name, pdf.parent)
txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True,
                     text=True, check=True).stdout


def grab(pattern):
    mm = re.search(pattern + r"[^\n]*?([\d.]{5,})\s*$", txt, re.M)
    return int(mm.group(1).replace(".", "")) if mm else None


report = {"aptos": grab(r"2\.2 Eleitorado apto a votar"), "comparecimento": grab(r"2\.3 Comparecimento"),
          "lula_13": grab(r"\*?13 - LUIZ IN.CIO LULA DA SILVA\s+([\d.]+)"),
          "flavio_22": grab(r"22 - FLAVIO NANTES BOLSONARO\s+([\d.]+)"),
          "nulos": grab(r"b\) Votos nulos"), "brancos": grab(r"c\) Votos em branco")}
# Candidate lines have the vote count right after the name, not at line end.
for k, pat in (("lula_13", r"13 - LUIZ IN.CIO LULA DA SILVA\s+([\d.]+)"),
               ("flavio_22", r"22 - FLAVIO NANTES BOLSONARO\s+([\d.]+)")):
    mm = re.search(pat, txt)
    report[k] = int(mm.group(1).replace(".", "")) if mm else None
s = pd.read_parquet(DERIVED / "sections_2026_r2.parquet")
ours = {"aptos": int(s.QT_APTOS.sum()), "comparecimento": int(s.QT_COMPARECIMENTO.sum()),
        "lula_13": int(s.votes_pt.sum()), "flavio_22": int(s.votes_opp.sum()),
        "nulos": int(s.QT_VOTOS_NULOS.sum()), "brancos": int(s.QT_VOTOS_BRANCOS.sum())}
nat = pd.DataFrame({"national_report": report, "sum_of_sections": ours})
nat["match"] = nat.national_report == nat.sum_of_sections
write_csv(nat, "consistency_national_report_2026.csv", index=True)
print(nat)
note("2026 R2 national report vs sum of sections", f"{nat.match.sum()}/{len(nat)} lines match")

write_csv(pd.DataFrame(summary), "consistency_summary.csv")

# Public checks that exist and were not run, with the reason (added in v2).
write_csv(pd.DataFrame([
    {"check": "Signatures of the per-machine files (bu.dat, .vscmr, logs, RDV) in "
              "bu_imgbu_logjez_rdv_vscmr_2026_2t_<UF>.zip",
     "status": "not run",
     "reason": "Needs the TSE file-format specification and the public-key certificate chain. "
               "The tse.jus.br pages that document them returned HTTP 403 to scripted requests "
               "on 2026-10-29, and no verifier was available. Bundles are 0.2 to 25.8 GB per state."},
    {"check": "Bulletin values decoded from bu.dat against the BWEB rows",
     "status": "not run", "reason": "Same files and same specification as above."},
    {"check": "Bulletin image text (imgbu) against the BWEB rows",
     "status": "not run", "reason": "Needs the machine bundles above. Not downloaded."},
    {"check": "Machine logs: votes computed against bulletin turnout",
     "status": "not run", "reason": "Needs the machine bundles above. Not downloaded."},
    {"check": "Any check of what a voter typed against what the bulletin recorded",
     "status": "not possible with public files",
     "reason": "Public files start at the bulletin. Nothing public records a voter's input."},
]), "consistency_checks_not_run.csv")
