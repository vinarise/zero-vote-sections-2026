# Interactive data files, v2

These files replace the v1 interactive files. v1 listed 408 named sections with coordinates. v2 lists none.

## Privacy rule

1. PRIVACY RULE. No section or polling place is named, located or listed. The smallest unit is the municipality (a city, for votes abroad).
2. A municipality or city is named only if it has at least 50 apt voters and neither candidate has 0 votes or all the valid votes in it. Others are pooled per state as 'other, pooled'.
3. No municipal-level file counts zero or near-unanimous sections. Zero sections are published only nationally, by region and by state, and as national place-category totals by two methods (official registers within 1 km, and the text rule), with cells under 10 sections suppressed.

Every CSV here starts with the rule as `#` comment lines. Read with `pandas.read_csv(path, comment="#")`.

## Files

- `municipal_2026_2t.csv`: one row per municipality or city abroad that passes the rule, plus one pooled row per state for units that do not. Sections, electorate, turnout, votes and shares only. It has no count of zero or near-unanimous sections, because a small municipality's count can point at a single community. Zero sections by state and by region are in `results/zero_by_state_2026.csv` and `results/zero_by_region_2026.csv`.
- `zero_sections_by_category.csv`: national counts by place category, by two methods. `registers, 1 km` is the headline method: the polling place's category from official IBGE, FUNAI and INCRA registers (step 11). `text rule` is the category inferred from the place's name, address and district (step 3). Against the registers the text rule finds about 41% of indigenous places (recall 41.2%, 95% interval 26.4% to 60.6%, `results/m5b_text_rule_samples.csv`), so its counts are lower bounds. Neither method is ground truth.
- `summary_by_year.json`: observed and expected zeros and near zeros, 2018, 2022, 2026.
- `SOURCES.md`: every source file.
