# EXPERIMENT: zero-vote sections in Brazil's 2026 presidential runoff

Written 2026-10-29 before any result was computed. Only file listings and
HTTP headers had been seen at this point. Changes made after results are
listed at the end under "Deviations", with the reason.

## The claim under test (press reports, 2026-10-28)

- 106 sections where Flávio Bolsonaro got zero votes in round 2. Lula got
  14,860 votes in them. 65 are in the North, 29 in the Northeast. About 68 are
  reportedly in indigenous villages or schools.
- 4 sections where Lula got zero: [Redacted before publication: four municipality
  names given in the press report. HMAC-SHA256 with the key in item 17:
  82db8da1e2cdb8568996ed7821d590e0a70e1d641cf585260b68766c190f2b98]. Flávio got 296 votes in them.

Neutral question: are these zero-vote sections what one would expect from how
people voted locally, for each candidate symmetrically, and compared with the
2022 and 2018 runoffs?

## Data

All files come from the TSE open-data CDN (cdn.tse.jus.br), listed on
dadosabertos.tse.jus.br. `00_download.sh` records URL, size, HTTP
last-modified, download time and SHA-256 in `sources.tsv`. Where the portal
publishes a SHA-512 file, `01_verify_hashes.py` checks it.

- Votes by section, president: `votacao_secao_<year>_BR.zip` (2026, 2022, 2018).
- Section detail (electorate, turnout, blank, null): `detalhe_votacao_secao_<year>.zip`.
- Municipal totals: `votacao_candidato_munzona_<year>.zip`.
- Polling places: `eleitorado_local_votacao_<year>.zip`.
- Ballot-box bulletins, 2026 round 2: `bweb_2t_<UF>_261020260742.zip` and `.sha512`.

## Definitions

- **Section**: one row key (state, municipality code, zone, section number)
  for round 2 (`NR_TURNO = 2`) and the office of President (`CD_CARGO = 1`).
  The universe of sections comes from the section-detail file, so a candidate
  with no row in the votes file for a section that exists counts as zero.
  Sections abroad (state code `ZZ`) are kept and shown as region "Abroad".
  Sections that were merged into another section on election day are counted
  as the TSE file reports them. No re-aggregation.
- **Valid votes (n)**: votes for the two candidates in that section. Blank and
  null votes are not valid votes.
- **Zero votes for candidate X**: X has 0 votes in a section with n >= 1. Sections
  with n = 0 (no valid vote at all) are reported separately and are not zeros
  for either side, because they say nothing about preference.
- **Small sections**: the primary count uses all sections with n >= 1. Sensitivity
  counts use n >= 10 and n >= 50. Models handle size directly because the
  probability of a zero depends on n.
- **Near zero**: (a) X's share of valid votes below 1%, and (b) X has 2 votes or
  fewer. Both with n >= 1. Zeros are included in both.
- **Candidates by year**: 2026 Lula vs Flávio Bolsonaro. 2022 Lula vs Jair
  Bolsonaro. 2018 Jair Bolsonaro vs Fernando Haddad. The comparison across
  years is by side: the PT candidate (Lula 2026, Lula 2022, Haddad 2018) and the
  opposing candidate (Flávio 2026, Bolsonaro 2022, Bolsonaro 2018). Names come
  from the data files, not from this document.
- **Region**: the five IBGE macro-regions from the state code, plus Abroad.

## Models (expected number of zeros for each candidate)

For section i with n_i valid votes, let q_i be the probability that candidate
X gets zero votes. Expected zeros E = sum of q_i. Its spread comes from the
sum of q_i(1 - q_i) (sections treated as independent). Each model is fitted and
evaluated in the same way for both candidates and all three years.

1. **Binomial, municipality leave-one-out (B-mun).** p_i = X's share of valid
   votes in the rest of the municipality, excluding section i.
   q_i = (1 - p_i)^n_i. If the rest of the municipality has no valid votes,
   the state leave-one-out share is used.
2. **Binomial, polling-place leave-one-out (B-place).** Same, with p_i taken
   from the other sections of the same polling place. Falls back to B-mun when
   the place has no other section with valid votes.
3. **Beta-binomial, municipality level (BB-mun).** The section share is drawn
   from a Beta distribution with mean equal to the municipality leave-one-out
   share and concentration phi. phi is estimated by maximum likelihood, one value
   per state per year, from all sections of that state. Then
   q_i = B(a, b + n_i) / B(a, b) with a = mu_i * phi, b = (1 - mu_i) * phi.
   Leave-one-out shares are clipped to [1e-4, 1 - 1e-4] so a and b stay positive.
   The likelihood is fitted to the counts of one candidate. The beta-binomial is
   symmetric in the two candidates, so one fit serves both.
4. **Beta-binomial, polling-place mean (BB-place).** Same as 3 with the
   polling-place leave-one-out mean. Sensitivity only.

The same machinery gives expected near-zero counts (share < 1%, votes <= 2) by
summing the model probability of those events per section.

## Questions

1. Replicate the counts of zero sections per candidate in 2026 round 2, with
   regional breakdown and the opponent's votes in those sections. Compare to
   106 / 14,860 and 4 / 296. Explain any gap (definition, abroad, data revision).
2. Describe the zero sections: electorate, turnout, valid votes, state,
   municipality, polling place name and type. Classify place names by text
   pattern into indigenous, rural or river community, school, other. This
   classification is inferred from text, not an official category. Also show
   the same section's round-1 2026 share for that candidate.
3. Observed against expected zeros and near zeros, under models 1 to 4, for each
   candidate.
4. The same for 2022 and 2018 round 2, by side.
5. Scale: share of sections and valid votes held by zero sections, national
   margin, and the extreme-case arithmetic (remove all opponent votes in those
   sections, or move them to the other side).
6. Integrity checks: bulletin vs section file per section and candidate; sum of
   sections vs published municipal totals; turnout vs electorate per section.

## What counts as "unexpected"

These were fixed before results:

- **U1 model.** Observed zeros above the 99.9% upper bound of a model (normal
  approximation to the sum of Bernoulli terms). Because real voting clusters
  more than any of these models assume, U1 is expected to fire for the binomial
  models in every year and on both sides. U1 alone is therefore not read as
  evidence of anything. It is read only together with U2.
- **U2 history.** For the same model, the 2026 observed/expected ratio for a
  candidate lies outside the range of the four baseline ratios (2018 and 2022,
  both sides) by more than a factor of 1.5.
- **U3 persistence.** Among round-2 zero sections for a candidate, the share
  where that candidate had 10% or more of the valid votes in round 1 of the same
  year in the same section. Unexpected if this share in 2026 is more than twice
  the 2022 value for the same side and involves 5 or more sections.
- **U4 integrity.** Any section where bulletin and section-file counts differ,
  any section with turnout above its electorate, or any municipality where the
  sum of sections differs from the published municipal total. Each case is
  listed.
- **U5 scale.** The votes in the zero sections are compared with the national
  margin. Reported as plain arithmetic, not as a test.

## Resources

[Redacted before publication: the name of the internal machine and its disk path. The paragraph also said: at most 8 worker processes, CPU only. HMAC-SHA256 of the original line, UTF-8, no trailing newline, with a private key (see item 17): af31be6b19a6f666535ff088be78ba6b4e6e3ad5569cfd4e8314955bc1de7d19]

## Deviations

Recorded after results, with reasons.

1. **Place-name patterns tightened before any result.** While writing the build
   script, two school patterns ("EM" and "CE") were dropped because they also match
   the Portuguese word "em" and the state code CE in addresses. A loose "T.I."
   pattern for indigenous land was dropped for the same reason. No result had
   been computed.
2. **History match with 2022 added during the build, not pre-registered.**
   `04_models.py` matches each 2026 zero section to the same section key in 2022
   and keeps only matches with the same polling-place name. Section numbers can be
   renumbered between elections, so this is approximate. It is descriptive only.
3. **National totalization report check added.** The brief asked for sums against
   the published national totals. The round-2 national report (PDF) in the
   `Relatorio_Resultado_Totalizacao_2026_BR.zip` file was parsed with pdftotext.
4. **Exploratory diagnostics added after U2 fired** (`06_diagnostics.py`). U2 fired
   for the municipality-mean beta-binomial on the non-PT side in 2026 and not for
   the polling-place models. The script splits observed and expected zeros by the
   inferred place-name flag and compares how one-sided the text-flagged indigenous
   places were in each year. It was written after seeing the U2 result, so it is
   exploratory and is labelled so in the report.
   The same script also writes two summary tables of facts already computed by
   `04_models.py`: the round-1 share in the 2026 zero sections (the U3 input) and
   the 2022 history match. They add no new test.
5. **Two extra scale fields** (votes as a share of the margin, votes needed to
   flip) were added to `scale.csv` after the first run, to state the arithmetic.

## v2 deviations (all dated 2026-10-29, after a full recheck of v1)

Everything above this heading is the v1 text, word for word, except two
redactions made before publication: the "Resources" paragraph (item 17) and the
four municipality names in the press claim (item 18). The HMAC-SHA256 of the
unredacted v1 file, with the private key of item 17, is
`68fe90b7e636dee8a433a3f80cef5f3065346e3c8e2fd54e1a00fb1a019685ba`.
The pre-registration was self-declared. It was not frozen with a hash or a commit
before the first model run, so it cannot be verified. The "Resources" paragraph
names the internal machine and disk the work ran on. Before publication that line was redacted, and a keyed HMAC-SHA256 of it is printed in its place, so anyone given the original line and the key can check it (item 17).
Errata to the text above: `01_verify_hashes.py` never existed. In v1 the hash
check was in `05_integrity.py`, and in v2 it is in `05_consistency.py`. Question 6
is renamed "Consistency checks".

Every item below was decided after the v1 results and the recheck were seen. Each
says what changed and why.

6. **BB-place dispersion fixed.** What: sections alone at their place use the
   municipality dispersion, and the place dispersion is fitted only on sections
   with place-mates. Why: v1 fitted it on all sections, which mixed municipality
   means into the place fit and inflated the spread. Pre-registered text: "same as
   3 with the polling-place leave-one-out mean", and the fallback is the
   municipality model, so the fix follows the text. The v1 code is kept as
   "BB-place (v1 code)" so the effect can be seen.
7. **Exact tails.** What: U1 uses the exact Poisson-binomial 99.9% quantile and
   P(X >= observed). The normal bound is still reported. Why: the normal
   approximation sits below the true quantile when expectations are small.
8. **Two models added.** What: EB-place and EB-r1, beta-binomial posterior
   predictives that start from the municipality mean and dispersion and update
   with the place-mates' votes (EB-place) or the same section's round-1 votes
   (EB-r1). Why: the place models give probability 1 when every place-mate is
   zero, which is circular. EB-r1 uses no round-2 outcome.
9. **Section-level checks.** What: expectation per section and where it falls,
   calibration by bins of probability, and proper scores (Bernoulli log score,
   Brier) over all sections. "Best model" means the highest log score and nothing
   else. Why: a matching total does not show that a model finds the zero sections.
10. **U2 per side.** What: each side compared with its own 2018 and 2022 ratios,
    reported next to the pooled rule written above. All 72 pre-registered checks
    are listed. Why: the pooled range is set by the side with larger ratios, so
    the rule as written cannot fire for the other side.
11. **Place-cluster bootstrap.** What: a 95% interval for each observed/expected
    ratio from resampling polling places (1,000 Poisson weights per place). Why:
    sections at one place are not independent.
12. **Classifier v2.** What: rules in `03_build.py`, the official place type,
    prison and quilombola flags, a manual check of all 110 zero sections of 2026,
    and a manual check of a random sample of 200 flagged sections. The rules were
    fixed before the sample was drawn. Why: v1 missed indigenous places, counted
    urban ones, and did not use the official type.
13. **Diagnostic redone.** What: composition reweighting, denominators, the local
    share (D3), flag components by year, and places matched across years. Why: the
    v1 diagnostic stated a cause it did not support. Note on the two matching
    keys (municipality plus place name, and place key plus place name): they give
    identical counts for indigenous-flagged places. This was checked, and it is
    not a code fault. Over all places the keys differ: 70,869 places match by
    name between 2026 and 2022 and 70,116 by key and name (87,705 and 87,224
    between 2022 and 2018). Among indigenous-flagged places, every place that
    matches by name also kept its zone and place number (350 and 422 places).
14. **Interactive files rebuilt under a privacy rule.** What: no section or place
    is named or located. Why: v1 listed small, prison and unanimous sections with
    coordinates.
15. **Reproducible package.** What: a portable downloader checked against
    `sources.lock.tsv`, pinned package versions, a configurable data folder,
    output checksums, IBGE codes from the TSE table `municipio_tse_ibge`, and
    section-level lists moved out of the published results. Why: the work is to be
    published and must run on a stranger's machine without exposing small
    communities. No number changed.
16. **External check of the place categories (step 11).** What: the place
    categories are compared with outside registers (IBGE 2022 Census indigenous and
    quilombola localities and census sectors, FUNAI indigenous lands and villages,
    INCRA quilombola territories), by each polling place's TSE coordinate. Its
    method is fixed in `EXTERNAL-CHECK-PLAN.md`, written before that check was run.
    It was later made step 11 of `run_all.sh`, its packages merged into
    `requirements.lock` and its files added to `sources.lock.tsv`. No number of
    that check changed in the merge. Why: the analyst labels read only the TSE
    text fields, so they could not show whether a place is in fact an indigenous
    or quilombola community (second recheck, items M3 and S7).
17. **"Resources" paragraph redacted.** What: the paragraph's single line was
    replaced by a redaction notice that keeps its harmless content (CPU only, at
    most 8 worker processes) and a keyed hash. Why: the line named the internal
    machine and the disk path of the raw data, which are never published. How the
    hash was computed: HMAC-SHA256 over the exact bytes of the original line as
    stored in the file, UTF-8, without the trailing newline (73 bytes), with a
    random 32-byte key. The result is
    `af31be6b19a6f666535ff088be78ba6b4e6e3ad5569cfd4e8314955bc1de7d19`. The unredacted v1 file's HMAC-SHA256 with the same key is
    `68fe90b7e636dee8a433a3f80cef5f3065346e3c8e2fd54e1a00fb1a019685ba`. Why keyed: the line is short and the notice says what it held, so a
    plain SHA-256 would let a reader confirm a guessed line. Without the key,
    a guess cannot be checked. The key is held privately by the lab and is not
    published. It can be disclosed to anyone asked to verify that the original line
    and file match these values (third recheck, item S6). Earlier drafts printed plain
    SHA-256 values. They are withdrawn.
18. **Municipality names in the press claim redacted.** What: the press report's
    four municipality names for the sections where the PT side had zero votes
    were replaced by a redaction notice with a keyed hash. Why: the text named the
    zero-section municipalities of one side only, which is asymmetric, and naming
    the municipality of a zero section breaks the lab's privacy rule. Zero sections
    are published only nationally, by region and by state. How the hash was
    computed: HMAC-SHA256, with the private key of item 17, over the exact bytes
    of the redacted span as stored in the original file, UTF-8: from the first
    letter of the first name to the closing parenthesis after the fourth, with
    the line break and the two-space indent between them (72 bytes). The
    result is `82db8da1e2cdb8568996ed7821d590e0a70e1d641cf585260b68766c190f2b98`. The key can be disclosed to anyone asked to verify it.

## Status of this registration (added 2026-11-01, revised the same day)

Everything above this heading is the published v2 text of this file, byte for byte. Its SHA-256, over those bytes alone, is `9d97b20920ab2da9bd7359334d401408954c049b7d43d1d21c88b4b13b35f617`.

**When it was written.** The questions, definitions, models and the rules under "What counts as unexpected" were written on 29 October 2026, before any result was computed. Only file listings and HTTP headers had been seen.

**What was not done.** The text was not frozen before the first model run. The earliest commitment to it is in signed commits of the site's source, dated 29 October 2026 by their author. No third party holds those commits, so their dates rest on the writer's word. The same text, byte for byte, is published at https://vinarise.com/labs/2026-10-zero-vote-sections/EXPERIMENT.md, where anyone can check the SHA-256 above. The host's deployment record dates the published copy to 29 October 2026, 11:21:07 UTC, a time kept by a party other than the author. The v1 results were computed before those commits, so the claim that the rules came before the results still rests on the word of whoever wrote them.

**How to read the deviations.** Items 1 to 5 were recorded in v1, after its results. Items 6 to 18 were decided on 29 October 2026, after the v1 results and a full recheck. The dates of items 1 to 18 rest on the same author-dated commits. All eighteen are in the published copy, so the host's date of 11:21:07 UTC on 29 October is the latest they can have been written. Every item says what changed and why. The ones that matter most for reading the results:

- Item 4: `06_diagnostics.py` is exploratory. It was written after the U2 rule fired, and every number it produces is labelled exploratory in the ledger.
- Items 8 and 9: the two EB models and the choice of the best model by log score came after results. The model the article calls best is one of them.
- Item 10: U2 per side was added after results. The pooled U2 as written above is still reported, all 72 checks.
- Items 12, 13 and 16: the place classifier, the matched-place comparison and the outside-register check came after results. The register check's method was fixed in `EXTERNAL-CHECK-PLAN.md` before that check ran.
- Items 17 and 18: the two redactions. Their keyed hashes are in the signed commits of 29 October named above, and in the published copy, because they are part of the text above.

**Deviations of 1 November 2026, the notebook record.** None changes a number.

19. **The run is a notebook.** `zero_vote_sections.ipynb` runs stages 2 to 6 and 8 to 11 of the v2 code, byte for byte, each in its own interpreter, and `run_all.sh` executes it top to bottom with nbconvert. Why: the record must show every step, in order, against an identified environment.
20. **Stage 1 runs only when an input is missing.** The notebook checks the size and SHA-256 of every input against `sources.lock.tsv` before anything else, without network access. `01_download.py` runs only if that check fails. Why: the reference files are on disk, and step 1 makes HTTP requests even when nothing needs downloading.
21. **Stage 7 is not run.** It draws one PNG chart and no number depends on it. Why: charts are drawn from the ledger by the site.
22. **A ledger.** Every number is a row of `results.csv`, written by `run_arm()` with the hashes of the inputs, the code, the environment, the config and the table it read. `FINDINGS.md` is generated from it by `make_findings.py`, and it replaces `FINDINGS-v2.md` as the list of numbers. Why: a number must trace to a row written by code.
23. **Wilson intervals.** Every proportion in the ledger carries its n and a Wilson 95% interval. The place-cluster intervals of item 11 are kept beside them. Why: a proportion without its denominator and interval cannot be compared. These intervals are new reporting, not a test, and no rule above uses them.
24. **Known-answer tests and independent counts.** The notebook tests its counting, the intervals, the model functions of `04_models.py`, the ledger and the map checks on small synthetic tables before any arm runs. It counts the zero sections, the votes and the margins again from the section tables and asserts them equal to the stage tables, and it recomputes the B-mun expectation on its own. Why: a number checked two ways is less likely to carry a code fault.
25. **Four more pinned inputs.** `inputs.extra.tsv` pins the two private analyst-label files and the two IBGE files the map data are drawn from, by size and SHA-256. Why: every input of the run must be identified.
26. **The map's data files.** `finding/zero_by_state.json`, `finding/places_2026.json` and `finding/br_states.json` follow the site's contract `vr-zero-vote/1`. Cities abroad are left out of the municipal file, because the contract allows only the 27 federative units. Why: the site's map reads these files, and they should come from the record rather than from a copy of it.
27. **Two reference runs were superseded before sealing.** The reference run of 1 November 2026 was repeated twice the same day, and only the third, run `20261101T110959Z-2b3ff462`, was sealed. Item 36 says how that seal was replaced the same evening. The first run (`20261101T090907Z-2b3ff462`) was replaced because a helper script listed, in a check pattern, names that no file of this package may carry. The second (`20261101T101152Z-2b3ff462`) was replaced because a pandas performance warning printed the kernel's temporary file path into the executed notebook, which the stricter check refused, and the index it warned about was then sorted. Each fix changed the code, so the harness hash changed and the run had to be repeated. The earlier runs' rows stay in `results.csv`, each superseded by the next run's row of the same arm. Across the three runs, every metric of every arm is identical. Only the notes that cite row ids differ.

**Deviations of 1 November 2026, the second seal.** None changes a number. Each was made after the first seal and before anything was published.

28. **The inputs were checked again.** Between 19:34 and 20:08 UTC every public input was compared with its source by an HTTP HEAD request, and a file was downloaded only if it had changed. `sources.freshness-2026-11-01.tsv` lists every file with its result. 71 TSE and IBGE files are unchanged: 49 by size and date, and 22 small hash files by date, because the server sends no size for them. The TSE had republished four: the municipal and zone results of 2022 and 2026, the national totalization report of 2026 and its table of TSE and IBGE municipality codes. Each was downloaded and compared with the locked copy. The rows the stages read are the same in all four. What differs is the generation date and time, the order of rows, the archive's member dates, and one municipality name in a column no stage reads. Two FUNAI files and the IBGE municipal mesh cannot be checked without a download, because their servers send no size or date, and the INCRA host did not resolve. The sealed run reads the locked copies. Why: a record published days after its inputs were fetched should say whether they still stand.
29. **The notebook computes the model arms.** The 378 arms of observed against expected zeros are computed in the notebook with the functions of `04_models.py`: the shares, the dispersion fits, each section's probability, the expected count, both 99.9% bounds and the exact tail, and the log score and Brier sum. Each value is asserted equal to the row stage 4 wrote, to the ten significant digits both write, and all are. Stage 4 stays as the oracle. Why: the notebook should carry the analysis, not copy a script's answers.
30. **The whole output of every stage is printed.** Before, the notebook showed a stage's first lines and its last 15. The output holds national, regional and state tables only. Why: a reader should see everything a stage reports.
31. **The decision says whether the registered expectation held.** The ledger gains one column, `expectation_held`. Every earlier row keeps its cells and gains an empty one. Anyone can check that: the ledger of the first seal had the SHA-256 `9f1e9325d2601d28c8ae0b3fa8ce2c88acf938e71316b94a4d36b5d2d112e071`, and `head -n 2008 results.csv | sed '1s/,expectation_held$//; 2,$s/,$//' | shasum -a 256` rebuilds it from this ledger. U1 is read twice: over the four registered models, for which nothing was registered as expected, and over the two binomial models, which the registration expected to fire in every year on both sides. On the PL side the two binomial models fired in all 18 checks in each year, so the expectation held. On the PT side they fired in 5, 13 and 15 of 18 checks in 2018, 2022 and 2026, so it did not hold. The other rules were registered without an expected outcome. Decision rows and the known-answer row carry no interval, because they count rules and tests, not a sample. Why: the decision is where a reader looks for whether an expectation held, and both sides are held to one standard.
32. **The baseline rows name their table.** The rows of the electorate, the votes and the margins are counted from the private section tables. Each row now names its table and carries its SHA-256, and section 8.1 asserts the same totals equal to `results/scale.csv`. Why: every number should point to the bytes it was counted from.
33. **Pooled rows never reach the map.** A row of `08_interactive.py` that pools several municipalities is dropped from `finding/places_2026.json`, inside a state as well as abroad, and the contract check refuses one. Two known-answer tests cover it. Today the only pooled row is the one abroad, so the file does not change. Why: the contract allows municipalities only.
34. **A run without the private inputs.** The notebook skips what needs the analyst labels or the map inputs, and the bundle check reports their tables as skipped instead of missing. A run without labels, without map inputs and with the four republished files is reported in `REPRODUCE.md`, section 4. The pre-flight now accepts a republished public file when the flag of `01_download.py` for its kind is set, and every ledger row of such a run carries the different inputs identity. `run_all.sh` runs `01_download.py` only when a public input is missing, as item 20 already said. Why: every reader runs without the labels, and many will download after the TSE republishes.
35. **The executed notebook is published.** It printed the path of its data folder once, and that line now prints only whether `ZV_DATA_DIR` was set. Two stage scripts print the full path of a label file they cannot find, so the notebook prints every stage's output with the data folder written as `$ZV_DATA_DIR` and the package folder as `.`, and the log in the data folder keeps the stage's own words. `check_notebook.py` asserts that the notebook holds no absolute path, no local folder and no host or user name, and the sanitized copy and the withheld status are gone. Why: a withheld file whose hash is public lets anyone confirm a guessed line, which is what item 17 avoided with a keyed hash.
36. **The first seal was replaced.** The bundle of the first seal, `f3b1b1eda041beea6cf6398b1682d253937dc69a8cc92cee2a62c109f85c34d6`, was never published. Items 28 to 35 and the licence decision changed sealed files, so the record was run again from the top and sealed again. Two runs of the second seal were replaced the same evening. Run `20261101T201213Z-2b3ff462` was replaced because a run without the labels showed that two stage scripts print the path of the missing label file (item 35), and masking it changed the code. Run `20261101T204207Z-2b3ff462` was replaced because its review showed that the bundle check reported a map file as skipped even when it was present, and that the decision table of `FINDINGS.md` labelled rules other than U1 with U1's checks. The sealed run is `20261101T211017Z-2b3ff462`. Every metric of every arm the first seal and the second seal share is identical, with two exceptions. The twelve decision rows that count checks and the known-answer row no longer carry a share and an interval (item 31), and the known-answer row counts 37 tests instead of 31. Otherwise only notes, provenance and the named interval method differ. Why: a changed file changes the bundle, and the bundle must come from one run.
37. **The licence was decided.** `LICENSE.md` grants Apache 2.0 for the code, CC BY 4.0 for the derived data and CC BY-ND 4.0 for the text, and names the source data's own terms. Why: a public record needs terms a reader can rely on.
38. **The second seal was replaced by its documents alone.** The bundle of the second seal, `0eefbbbff2925786e49b6b593cfbe3f9d4490044d20372c6171e2dc38f9853dd`, was never published. Its Status section said that the commits of 29 October sat in a private repository that readers could check later. No third party has ever held them, so that sentence now says their dates rest on the writer's word, and points to the copy the site has published since 29 October, dated by its host. The commit ids are gone. `REPRODUCE.md` now carries the independent recount script with a guard against reading no rows, its expected output, and the fault the guard closes, and says that the run without the private inputs reused the built environment. Item 31 gives the first ledger's hash. Nothing was run again: the ledger, the tables, the notebooks and the code are those of run `20261101T211017Z-2b3ff462`. Why: a sealed sentence must not promise evidence that does not exist.
