# Licences

Decided on 1 November 2026. Each part of this package is published under the licence below. The source data keep their own terms.

## This package

| Part | Files | Licence |
|---|---|---|
| Code | `*.py`, `zvnb/`, `run_all.sh`, `zero_vote_sections.ipynb` | Apache License 2.0 |
| Derived data | `results/`, `interactive/`, `finding/`, `results.csv`, `dataset.json` | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| Text | `EXPERIMENT.md`, `EXTERNAL-CHECK-PLAN.md`, `FINDINGS.md`, `REPRODUCE.md`, `environment.md`, `LICENSE.md` | Creative Commons Attribution-NoDerivatives 4.0 International (CC BY-ND 4.0) |

One derived file is an exception. `finding/br_states.json` redraws IBGE's state outlines, so the outlines keep IBGE's terms (below), and CC BY 4.0 covers only what this package adds to them.

The executed notebook, `zero_vote_sections.executed.ipynb`, is code with its outputs. Its code is under Apache 2.0 and its outputs under CC BY 4.0, like the derived data they show.

Full texts:
- Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0
- CC BY 4.0: https://creativecommons.org/licenses/by/4.0/legalcode
- CC BY-ND 4.0: https://creativecommons.org/licenses/by-nd/4.0/legalcode

Attribution for the derived data: "Vinarise, zero-vote sections in Brazil's presidential runoffs, derived from open data of the Tribunal Superior Eleitoral."

Why these. Apache 2.0 lets anyone rerun, change and reuse the code, with a patent grant. CC BY 4.0 for the derived tables matches the licence of the TSE data they come from, so nobody downstream meets two sets of terms. CC BY-ND 4.0 for the text keeps the registration and the findings from being republished in altered form under this package's name, while allowing them to be copied whole.

## The source data

These are not redistributed here. `run_all.sh` downloads them from their publishers, and their own terms apply.

- **TSE files.** The TSE open-data portal lists every package this Lab uses (`resultados-2026`, `resultados-2026-boletim-de-urna`, `resultados-2022`, `resultados-2018`, `eleitorado-2026`, `codigos-oficiais-de-uf-e-municipios-segundo-o-tse-e-o-ibge`) under the licence `cc-by`, read from its CKAN API on 2026-10-29. Attribution: Tribunal Superior Eleitoral.
- **IBGE, FUNAI and INCRA registers, and the IBGE municipal mesh.** Their download pages state no licence. Brazilian federal open-data policy (Decreto 8.777/2016) applies, by inference. They are cited and not redistributed.
- **IBGE state mesh and municipality names** (the map inputs). No licence statement was found on IBGE's API pages. The map file `finding/br_states.json` is drawn from the state mesh, and its `source` field names IBGE's API. Whether this use needs more than attribution is still a question for legal review.
