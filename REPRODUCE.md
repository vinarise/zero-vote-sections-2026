# Reproduce

One command rebuilds the whole record from the public TSE files: the tables, the ledger, the findings and the map files.

```
./run_all.sh
```

To keep the data somewhere else: `ZV_DATA_DIR=/path/with/12GB ./run_all.sh`.

To check the files you downloaded against the seal, before running anything:

```
shasum -a 256 -c BUNDLE.sha256
```

## 1. What you need

- Linux x86_64. The reference run used it. macOS was not tested.
- Python 3.13.5 (`.python-version`). The notebook's first cell stops on any other version, because output hashes can change with it.
- `pdftotext`, from poppler-utils.
- Network access to the TSE and IBGE servers and to the Python package index, for the first run only.
- Disk: about 12 GB in the data folder. Memory: about 6 GB at the peak.

## 2. What the command does

1. Builds `.venv` from `requirements.lock` (the analysis) and `requirements-notebook.lock` (the notebook runner), with `--require-hashes`, so every package file must match the SHA-256 published by PyPI.
2. Runs `01_download.py` if a public input is missing. It downloads the public files and stops if the TSE has changed one since the reference download. When every input is present, nothing is fetched.
3. Executes `zero_vote_sections.ipynb` top to bottom with nbconvert and writes `zero_vote_sections.executed.ipynb`. The notebook checks the environment and the size and SHA-256 of every input, runs the known-answer tests, runs the analysis stages in order, computes the 378 model arms itself and asserts them equal to stage 4's tables, writes one ledger row per arm to `results.csv`, compares the 63 published tables with the reference checksums, builds the map files and evaluates the registered rules.
4. Writes `FINDINGS.md` from the ledger with `make_findings.py`, which also compares every number the published piece states with the ledger and fails if one differs.
5. Checks with `check_notebook.py` that the executed notebook holds no path or name of the machine that ran it, and compares every sealed file with `BUNDLE.sha256`.

## 3. Time

The sealed run's notebook printed a total of 1,405 s, about 23 minutes, and building the environment takes about two minutes more. The analysis stages took 792 s of it, mostly on one core. The cell that computes the 378 model arms took 344 s. The rest is hashing the 6.4 GB of inputs and writing the ledger, each row flushed to disk. Another run of the record and other jobs shared the machine during the sealed run, so it is slower than an idle machine would be. A first run also downloads about 4.9 GB.

## 4. Inputs you may not have

- **The analyst labels.** Two private files label the 110 zero sections of 2026 and a sample of 200 flagged sections. They identify small communities, so they are not published. Without them the notebook skips the agreement table between the registers and the labels, stage 10 reports 7 tables as skipped, `make_findings.py` reports the two numbers of the piece that come from that table as needing the labels, and `make_bundle.py --check` reports the 7 tables as skipped, not missing.
- **The two IBGE map inputs** (`inputs.extra.tsv`, kind `map`). Put them in `data/map/`. IBGE builds the mesh on request, so a fresh download may differ from the pinned hash, and the notebook then stops at its pre-flight. Without them the notebook skips the map files, and the bundle check reports the three `finding/` files as skipped.
- **Republished TSE files.** The TSE sometimes republishes a file. On 1 November 2026 it had republished four, with the same rows: `sources.freshness-2026-11-01.tsv` lists them with both hashes and what differs. A file that differs from its lock stops the notebook's pre-flight and names the flag to set. `ZV_ALLOW_CHANGED_SOURCES=1` runs on the new version, and every ledger row then carries a different inputs identity. If the content changed, tables may differ: that is a data revision, not a reproduction failure, and the notebook records it instead of stopping.
- **Rebuilt registers.** FUNAI builds its files on request and INCRA rebuilds its file every night, so a fresh download will usually differ from the pinned copy. `ZV_ACCEPT_NEW_REGISTERS=1` runs on it, and the register tables (`results/m5b_*`) may then differ from the published ones.

The command was run this way on 1 November 2026, on the reference machine, with no labels, no map inputs and the four republished TSE files, as a stranger would have it that day. It used the reference machine's Python environment, already built from the locks, so building that environment was not part of this run.

```
ZV_ALLOW_CHANGED_SOURCES=1 ./run_all.sh
```

What it reported:

- The pre-flight listed the four republished files as changed and accepted them, and listed the two label files and the two map inputs as absent.
- 37 of 37 known-answer tests passed.
- The notebook wrote 666 ledger rows, none failed. The sealed run wrote 675: the 9 more are the 3 rows that compare the registers with the labels and the 6 rows that check the map files.
- The 378 model arms, computed in the notebook from the republished files, equal stage 4's tables.
- Stage 10: 56 of the 63 published tables identical to the reference, 0 different, 0 missing, 7 skipped because they need the labels. The privacy rule holds.
- Every number in those 666 rows equals the sealed run's, except the count of identical tables.
- `make_findings.py`: 133 of the 135 numbers of the piece identical, and 2 (N092 and N093, "103 of 106") need the labels.
- `check_notebook.py`: no absolute path, local folder or machine name.
- The notebook took 1,404 s, and the command exited with status 0.

`make_bundle.py --check`, run on that folder with this `BUNDLE.sha256` in place, reports the 7 label tables and the 3 map files as skipped, the 4 files that record a run (`results.csv`, the executed notebook, `FINDINGS.md`, `environment.md`) as differing, as expected, and nothing missing, and exits 0.

## 5. Expected hashes

On the reference platform the published tables come out byte for byte as in `checksums/results.sha256`, the v2 reference, and the notebook asserts it. A few of them, and the three map files:

```
ea4c347351132334169b612a55e7697000aedacb16c2c286c0fb5c8ba623d97c  results/scale.csv
66abeabb42a14110dcc890471594778e4bc7b9861e58c9960fb05bc838c0cae1  results/observed_vs_expected.csv
20a6057ea616a314425c241800756edb7326a33e7b41e9fa699187b0baa48015  results/u2_history_check.csv
5aea13aa62458986cc159aa92f20394cecb5cfe1f23c893c49e9668089126458  results/model_scores.csv
ddfe1ab0daf5b0b2cf50dd0d833111a2192434492abae399b6e89d68c6d3159f  results/consistency_summary.csv
f2af016ea9793a11a9b05c40f573d4ddd105fdb6398a26a9df2b31946c627bed  results/m5b_zero_sections_categories.csv
08201c8ba9e3a7e58c4b8c2c3dcbf49d7e37a7a4d5d863a67b9ee602c8b51464  results/m5b_panel_2022_2026.csv
eeb2decf7fb4f0ce148ea99720a276cbc00086c896076405094ae038e7095913  interactive/zero_sections_by_category.csv
23581dc52999ecc59c02aa387f5e401adb22e0a728f3c6a68408eb5bbe044a40  finding/zero_by_state.json
addc117abe83cc763aeae1184699957bd549baad040b061d10b2a7d978e0b603  finding/places_2026.json
2a0271228796a5e7f8eb94ac7cede6da8e6854c1519a6403480a776704024969  finding/br_states.json
```

The files that record a run differ on every run: `results.csv` gains new rows (each names the row it supersedes), and `zero_vote_sections.executed.ipynb`, `FINDINGS.md`, `environment.md` and `dataset.json` carry the new run's identity. `make_bundle.py --check` lists them as expected differences.

## 6. The seal

`BUNDLE.sha256` lists every sealed file with its SHA-256. The bundle hash is the SHA-256 of `BUNDLE.sha256` itself. Every sealed file is published, the executed notebook included. It prints no path or name of the machine that ran it, and `check_notebook.py` asserts that on every run. `BUNDLE.sha256.ots` is an OpenTimestamps proof of `BUNDLE.sha256`: `ots verify BUNDLE.sha256.ots` checks it against the Bitcoin block that holds it, once the calendars have put it there.

## 7. An independent recount

The headline counts can be checked without this package's code. The awk script below reads each raw TSE section file as the TSE publishes it and counts, for round 2 of the presidential election, the sections with a valid vote, the zero sections of each side at three minimum sizes, the other side's votes in them, both totals and the margin. It shares no code with the notebook. It stops with exit status 1 on an unexpected header, or when it reads no section of round 2 for a year.

Its first run on 1 November 2026 had no such guard and read no rows for 2022, because the 2022 file quotes every field and the other two years quote only the text. The output was visibly empty, so the fault was caught and fixed the same hour. The quotes are now removed before any field is read, and the guard turns an empty read into a failure.

The same script and output are in the folder `recount/` of the repository, with `compare.py`, which compares them with the ledger.

```
for y in 2018 2022 2026; do
  opp=22; [ "$y" = 2018 ] && opp=17
  unzip -p "data/raw/votacao_secao_${y}_BR.zip" "votacao_secao_${y}_BR.csv" \
    | LC_ALL=C awk -v year="$y" -v pt=13 -v opp="$opp" -f recount/recount.awk || exit 1
done > recount.txt
python3 recount/compare.py recount.txt results.csv
```

The script, `recount/recount.awk`:

```
# Independent recount of round 2, President, from one raw TSE section file. Shares no code with the record.
#   unzip -p votacao_secao_2026_BR.zip votacao_secao_2026_BR.csv | LC_ALL=C awk -v year=2026 -v pt=13 -v opp=22 -f recount.awk
# The PL side's ballot number is 17 in 2018 and 22 in 2022 and 2026. The PT side's is 13.
# Columns: 6 NR_TURNO, 11 SG_UF, 14 CD_MUNICIPIO, 16 NR_ZONA, 17 NR_SECAO, 18 CD_CARGO, 20 NR_VOTAVEL, 22 QT_VOTOS.
# It fails, exit 1, on an unexpected header or when no section of round 2 is read.
BEGIN { FS = ";" }
# 2022 quotes every field, 2026 and 2018 only the text. Quotes go before the fields are read.
{ gsub(/"/, "") }
NR == 1 { if ($6 != "NR_TURNO" || $17 != "NR_SECAO" || $20 != "NR_VOTAVEL" || $22 != "QT_VOTOS") { print "unexpected header" > "/dev/stderr"; bad = 1; exit 1 } next }
{ nf[NF]++ }
$6 == 2 && $18 == 1 {
  k = $11 FS $14 FS $16 FS $17
  seen[k] = 1
  if ($20 == pt) P[k] += $22
  else if ($20 == opp) O[k] += $22
}
END {
  if (bad) exit 1
  for (k in seen) {
    sections++
    n = P[k] + O[k]; tp += P[k]; to += O[k]
    for (i = 1; i <= 3; i++) {
      m = (i == 1 ? 1 : (i == 2 ? 10 : 50))
      if (n >= m) { valid[m]++; if (O[k] == 0) { zo[m]++; vo[m] += P[k] } if (P[k] == 0) { zp[m]++; vp[m] += O[k] } }
    }
  }
  if (sections == 0) { printf "year %s: no section of round 2 was read\n", year > "/dev/stderr"; exit 1 }
  printf "year %s: sections with a round-2 row %d, votes pt %d, votes opp %d, margin %d\n", year, sections, tp, to, tp - to
  for (i = 1; i <= 3; i++) {
    m = (i == 1 ? 1 : (i == 2 ? 10 : 50))
    printf "  at least %2d valid votes: sections %d, zero for opp %d (pt votes in them %d), zero for pt %d (opp votes in them %d)\n", m, valid[m], zo[m], vo[m], zp[m], vp[m]
  }
}
```

Its output on the locked TSE files:

```
year 2018: sections with a round-2 row 454448, votes pt 47040906, votes opp 57797847, margin -10756941
  at least  1 valid votes: sections 454447, zero for opp 328 (pt votes in them 36608), zero for pt 4 (opp votes in them 315)
  at least 10 valid votes: sections 454436, zero for opp 326 (pt votes in them 36598), zero for pt 4 (opp votes in them 315)
  at least 50 valid votes: sections 452505, zero for opp 261 (pt votes in them 34495), zero for pt 2 (opp votes in them 229)
year 2022: sections with a round-2 row 472028, votes pt 60345999, votes opp 58206354, margin 2139645
  at least  1 valid votes: sections 472027, zero for opp 143 (pt votes in them 16455), zero for pt 4 (opp votes in them 124)
  at least 10 valid votes: sections 472017, zero for opp 142 (pt votes in them 16450), zero for pt 2 (opp votes in them 118)
  at least 50 valid votes: sections 471326, zero for opp 118 (pt votes in them 15739), zero for pt 1 (opp votes in them 79)
year 2026: sections with a round-2 row 499205, votes pt 64256232, votes opp 59826041, margin 4430191
  at least  1 valid votes: sections 499205, zero for opp 106 (pt votes in them 14860), zero for pt 4 (opp votes in them 296)
  at least 10 valid votes: sections 499201, zero for opp 106 (pt votes in them 14860), zero for pt 4 (opp votes in them 296)
  at least 50 valid votes: sections 498528, zero for opp 88 (pt votes in them 14209), zero for pt 3 (opp votes in them 248)
```

`compare.py` then prints `63 fields equal, 0 differ` for run `20261101T211017Z-2b3ff462`. It fails if a year is missing, if a year read no section, or if any field differs.
