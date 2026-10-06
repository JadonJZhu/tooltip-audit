# Prompt tuning runs

All tuning used patch 16.18 only: the 125 planted errors in `data/planted/dev.jsonl`, a slice of 200 unmodified records (`data/tuning/1618_slice200.jsonl`), and once at the end a held-out set of 400 unmodified records (`data/tuning/1618_holdout400.jsonl`). Each version was run once (run 1). Catches on the planted set were judged, and flags on unmodified records were labeled, by `scripts/evaluate.py`.

The final prompt is v1, the text in `scripts/check_model.py`. The texts of v2 to v4 were not kept. Each added general rules about what counts as a disagreement (two different values for the same quantity, compared only with the placeholder's own formula, level-up row and coefficients; rounding and the same value written another way are not mismatches), and v4 also asked the model to work out both values first. `data/` is not in this repo; the run files here hold every flag.

## Strong model, by prompt version

Planted set (catches out of cases, by planting rule):

| Version | Total | stat_ratio | drop_term | other_value | multiplier | base_values |
|---|---|---|---|---|---|---|
| v1 | 51/125 | 12/54 | 29/51 | 7/14 | 2/3 | 1/3 |
| v2 | 31/125 | 7/54 | 22/51 | 1/14 | 1/3 | 0/3 |
| v3 | 47/125 | 11/54 | 29/51 | 4/14 | 2/3 | 1/3 |
| v4 | 25/125 | 8/54 | 14/51 | 2/14 | 1/3 | 0/3 |

Slice of 200 unmodified records (every flag labeled):

| Version | Flags | Real mismatch | Not a mismatch | Can't tell | Precision |
|---|---|---|---|---|---|
| v1 | 18 | 1 | 15 | 2 | 1/18 (6%) |
| v2 | 10 | 0 | 9 | 1 | 0/10 (0%) |
| v3 | 9 | 0 | 8 | 1 | 0/9 (0%) |
| v4 | 4 | 0 | 3 | 1 | 0/4 (0%) |

## Final prompt (v1), both models

| Model | Planted set catches | Held-out flags | Real mismatch | Not a mismatch | Can't tell | Precision |
|---|---|---|---|---|---|---|
| strong | 51/125 | 19 | 1 | 15 | 3 | 1/19 (5%) |
| small | 46/125 | 18 | 2 | 12 | 4 | 2/18 (11%) |

Small model on the planted set by rule: stat_ratio 8/54, drop_term 34/51, other_value 4/14, multiplier 0/3, base_values 0/3.

## Cost per run (USD)

| Run | Strong | Small |
|---|---|---|
| Planted set (125) | 0.20 to 0.23 | 0.03 |
| Slice (200) | 0.30 to 0.35 | |
| Held-out (400) | 0.59 | 0.10 |

Judging and labeling for all of the runs above cost $1.09 in total.
