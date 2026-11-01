# Zero-vote sections in Brazil's presidential runoffs, 2018, 2022 and 2026

The research record behind the Vinarise Lab piece on sections where one runoff candidate got no votes. Everything here comes from the open data of the Tribunal Superior Eleitoral (TSE): the code, the questions and rules written before the results, the notebook that runs the analysis top to bottom, the ledger of every number it produced, the findings generated from that ledger, and the tables the piece and its map read.

No file names a section, a polling place or a community, and no count of zero sections is given below the level of a state.

## What is here

- `EXPERIMENT.md`: the questions, models and the rules for "unexpected", written before any result, with every deviation since, each dated and explained. Read its section "Status of this registration" first.
- `zero_vote_sections.ipynb` and `zero_vote_sections.executed.ipynb`: the notebook, and the sealed run of it with its outputs.
- `results.csv`: the append-only ledger. One row per measured arm per run, with the hashes of the inputs, the code, the environment and the table each number was read from.
- `FINDINGS.md`: generated from the ledger. Section 1 checks every number the published piece states against its ledger row.
- `results/`, `interactive/`, `finding/`: the published tables and the map's data files.
- `environment.md`, `sources.lock.tsv`, `inputs.extra.tsv`, `sources.freshness-2026-11-01.tsv`: the machine, the libraries, and every input with its URL, size and SHA-256.
- `REPRODUCE.md`: how to rerun it, what you need, and what to expect without the private inputs.
- `recount/`: an independent recount of the headline counts from the raw TSE files, in awk, with its expected output and a script that compares it with the ledger. `REPRODUCE.md`, section 7, carries the same script and output inside the seal.

## Rerun it

```
shasum -a 256 -c BUNDLE.sha256
./run_all.sh
```

Linux x86_64, Python 3.13.5, `pdftotext`, about 12 GB of disk. The first run downloads the TSE files, about 4.9 GB. `REPRODUCE.md` has the details.

## The seal

`BUNDLE.sha256` lists every sealed file with its SHA-256. The bundle hash, the SHA-256 of `BUNDLE.sha256` itself, is:

```
18fed139d418a309b1a291e352a04565fd54c82aac75c9932f4a090a92bfe70c
```

`BUNDLE.sha256.ots` is an OpenTimestamps proof of that file, submitted on 1 November 2026 at 21:53 UTC to four OpenTimestamps calendars and pending until they put it in a Bitcoin block. After the proof is upgraded in a later commit, `ots verify BUNDLE.sha256.ots` confirms the Bitcoin block. Until then it reports pending.

## Licence

Code under Apache License 2.0, derived data under CC BY 4.0, text under CC BY-ND 4.0. The TSE data keep their own licence (CC BY, attribution to the Tribunal Superior Eleitoral). `LICENSE.md` has the details and the exceptions.
