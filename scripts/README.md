# Scripts

Run everything from the project root. Every script takes `--help`. Downloads and outputs go under `data/`, which is not committed. The usual order is: mine the patch notes, fetch the patches they point to, resolve those patches, build the checkers' inputs from them, plant errors, and run the baseline script.

## fetch_cdragon.py

Downloads live patches from CommunityDragon into `data/raw/<patch>/`, keeping the server's paths. For each patch it saves the build file (`content-metadata.json`), the tooltip text for each requested language, the champion list (`champion-summary.json`) and every playable champion's game data (`game/data/characters/<champion>/<champion>.bin.json`). For patches before 11.1 it also saves each champion's binary `.bin` file, because the JSON exports of those patches leave out the class names the resolver needs.

A few folders (11.7 and 13.3) have no champion list. For those the script uses the list of the nearest earlier patch that has one, since champions are never removed, and saves each champion on it whose folder this patch has. It also reads the nearest later list: a champion only on that list who has a folder here may have been released in the gap, so it is not saved. It is listed under `champions.release_unknown_not_saved` in the manifest and counted as a failure. If no earlier patch has a list, the later one is used, and that is also a failure, since it can name champions released after this patch. The borrowed list is not saved in the patch folder.

```
python3 scripts/fetch_cdragon.py --list                    # live patches and languages
python3 scripts/fetch_cdragon.py --patches latest 15.1
python3 scripts/fetch_cdragon.py --since 15.1              # every patch from 15.1 on
python3 scripts/fetch_cdragon.py --patches 16.19 --locales all
python3 scripts/fetch_cdragon.py --patches 16.19 --refresh
```

The text file has been kept in the places below, and the script looks in the right one for each patch:

| Patches | Text file |
|---|---|
| 10.25 and older | `game/data/menu/fontconfig_<locale>.txt` (a binary string table, despite the name) |
| 11.1 to 12.22 | `game/data/menu/fontconfig_<locale>.txt.json` |
| 12.23 to 14.3 | `game/data/menu/main_<locale>.stringtable.json` |
| 14.4 to 14.14 | `game/<locale>/data/menu/en_us/main.stringtable.json` |
| 14.15 and later | `game/<locale>/data/menu/en_us/lol.stringtable.json` |

`manifest.json` in each patch folder records the build, which text file was saved for each language (`stringtable_layout`, `stringtable_path`), the champion counts (`champions`, with `bin_saved` for patches before 11.1, and `list_source`, which says where the champion list came from: for a borrowed list, `from_patch`, the list's path in that patch as `file`, and `saved_in_this_folder: false`. Manifests written before `list_source` was added don't have it, and older ones that have it may lack `saved_in_this_folder`), every file with its size, any failures, and how long the first download took.

CommunityDragon sometimes replaces a patch folder with a later build. Each run first compares the server's build with the one on disk. If they match, files already on disk are checked and reused. If they differ, the script stops for that patch rather than mix two builds; `--refresh` deletes the folder and downloads it again. The script exits with code 1 if any patch stopped or any file failed.

## resolve_tooltips.py

Links each champion ability to its tooltip text and works out the number behind every `@placeholder@`, per rank, keeping stat scalings symbolic (`+50% AP`). It also lists numbers typed straight into the text. It reads every tooltip field a spell names: the tooltip, the longer text shown while Shift is held, and the simple tooltip. It reads the text file from every place in the table above, including the binary table of patch 10.25 and older, and for patches before 11.1 it reads the champion `.bin` files that fetch saved.

```
python3 scripts/resolve_tooltips.py --patches 16.19 15.1
python3 scripts/resolve_tooltips.py                         # every patch under data/raw
python3 scripts/resolve_tooltips.py --patches 16.19 --locale fr_fr
```

It writes three files per patch and language: `data/resolved/<patch>.<locale>.jsonl` with one record per spell and text field, `data/resolved/<patch>.<locale>.spells.jsonl` with the game data behind those records, and `data/resolved/<patch>.<locale>.summary.json` with coverage counts, the reasons any value was not worked out, and the CommunityDragon build the files came from (`cdragon_version`). Coverage and reasons are given for all records and again for slots P, Q, W, E and R alone (`placeholder_coverage_pqwer_slots`, `unresolved_reasons_pqwer_slots`). Each record has `champion_folder` and `slot` (`P`, `Q`, `W`, `E`, `R`; a second form of an ability is `Q-form` and so on, other spells are `ability-child` or `other`).

The spells file has one line for every spell that has a record, is grouped with one, or is read by one. Each line is found by its `key`, `<champion_folder>:<spell_path>`, and a record's `spell_context` gives the key of its spell. A line holds the spell's values per rank as the game stores them (data values, effect amounts, cooldown, cost, ammo and range), its damage coefficients, every calculation as written with its worked-out result, the rows of the panel that compares ranks when the ability is levelled up (with their label in this language), and the game's `EnableExtendedTooltip` flag. Older patches name a calculation's data value only by a hash; the resolver adds the name beside it (`data_value_name`, or `start_data_value_name` and `end_data_value_name`). A level-up row keeps the stored `value` and adds `value_times_multiplier`, the number the game shows. A line's ranks can differ from those of its records: each record keeps its own `ranks` and `rank_source`, so a record may show rank 1 only while its line shows ranks 1 to 5.

`group` lists the other spells of the same ability, with the rule that put the spell there in `joined_by`. Where the game names an ability's spells in an ability object, that is the group (source `AbilityObject`). Most champions gained ability objects between 11.1 and 12.6. The rules below never change a group made from an ability object. Each P, Q, W, E or R spell that no ability object names starts a group (source `slot spell`), and a spell joins it by the first of these rules that fits. Spells of a game mode (script names starting with `NightmareBot`, `Odyssey` or `Strawberry_`) start no group and join none by these rules, though an ability object that names one still groups it. URF spells are marked by a suffix instead (`SonaW_URF`), so they are not caught and can still join by rule 1.

1. `script-name prefix`: its script name begins with the slot spell's, followed by an uppercase letter, a digit or `_` (`SionWDetonate` joins `SionW`; `GarenRunCycleManager` does not join `GarenR`).
2. `AbilityObject in <patch>`: the first later patch with an ability object rooted at that slot spell puts it there (in 11.7, Corki's `GGSpray` joins `GGun` because of 11.23's ability object). So a patch's groups depend on which later patches are under `data/raw`.
3. The link rule (`joined_by` says it names or is named by a spell of the group): spells that name each other in their data join the one group their links reach, and none if they reach two. It does not read `mAlternateName`, which often holds a name copied from another spell, and basic and critical attacks join only by rule 1. So some real members are in no group (in 11.7, Orianna's `OrianaReturn`), and the links it still makes can be false, so a reader can drop its members by `joined_by`.

`refers_to` lists other spells its calculations read, and a record's `referenced_spells` lists the spells its text and its placeholders' calculations read.

The summary counts how many spells-file lines are in a slot-spell group and in an ability-object group (`spell_contexts_in_slot_spell_group` and `spell_contexts_in_ability_object_group`, under `counts`; either is left out when no line is in that kind of group, so 16.19, where every group comes from an ability object, has no `spell_contexts_in_slot_spell_group`), and how many joined by each rule (`spell_contexts_joined_by`). For a readable text file it also counts the tooltip keys found only under their hash rather than their name (`keys_found_only_by_hash`) and the level-up labels found that way (`level_up_labels_found_only_by_hash`). Both are null for a binary table, which holds only hashes.

A record of the text shown while Shift is held has `extended_text_hidden_in_game: true` when its spell turns that text off (`EnableExtendedTooltip` false), so players never see it. It is still a checked record.

The game numbers each stat a scaling can use (AP, bonus AD and so on), and the numbering has changed four times. The summary's `stat_layout` says which numbering the resolver found: D for 10.20 and older, C for 10.21 to 11.10, A for 11.11 to 15.6, E for 15.7 to 15.15 and B for 15.16 on.

Two kinds of record are not tooltips to check, and are dropped when building the set of tooltips that get checked. The summary's `checked_records` counts the records left after dropping them, overall and for `keyTooltip`.

- A record with `duplicate_of` set holds a text that another spell of the same champion shares with the spell the text belongs to, and `duplicate_of` gives that spell's path. When two or more spells of a champion name the same text, it belongs to the only one of them in slot P, Q, W, E or R. If none or several are, it belongs to the only one whose script name the text key carries (`Spell_<Script>_Tooltip`). The owner may itself be stored under a hashed path. Every other spell of the champion that names the text gets `duplicate_of`, under a hashed or a readable path (`MalzaharWCancel` in 15.1 is marked as a duplicate of `MalzaharW`). If neither rule finds a single owner, no record is marked.
- A record whose `text_field` is `passiveToolTip` is the champion's short summary text (the passive description shown in champion select), not an in-game tooltip. It is read only when no passive spell names a `keyTooltip`: either the passive spell has none, or no passive spell is found at all. These records have been seen in early patches such as 10.1 and 10.20.

## inputs.py

Builds what each checker reads: one input per checked record of a resolved patch and language, the same set as the summary's `checked_records`. The baseline script, the planting code and the model checker all read these inputs.

```
python3 scripts/inputs.py --patch 16.19
python3 scripts/inputs.py --patch 16.18 --locale fr_fr      # needs 16.18 resolved in en_us too
```

It writes `data/inputs/<patch>.<locale>.jsonl`, one input per line, and prints the count, the total size in characters, an estimate of the tokens (characters divided by 3.0, from the tokenizer count below) and the median and largest input. An input holds:

- `id`: `<patch>:<locale>:<champion_folder>:<spell_path>:<text_field>`, and the champion, slot, text field and the record's ranks.
- `text`, the text with its `@placeholders@`, and `filled`, the same text with each placeholder replaced by the value it shows. An unresolved placeholder stays as written.
- `typed_numbers`: each number typed into the text, with its `start` and `end` in `text`.
- `placeholders`: for each placeholder, the value it shows (one per rank, joined by `/`, as in `35/60/85 (+50% AP)`), and for a calculation the formula it comes from, with its own worked-out value: each part with its data value name, coefficient and stat, any multiplier, and `tooltip_only` where the game marks it so. A calculation's `damage_type` is written as a word (`physical`, `magic` or `true`; the evidence for each is in a comment above `DAMAGE_TYPES`). Where a field that names another calculation holds only a hash and the input shows that calculation under a readable name, the field gives the name. `of` names the other spell a `@spell.X:Name@` placeholder reads.
- `spell`: the record's own spell, with its own `ranks` and `rank_source`, its `EnableExtendedTooltip` flag, its data values, effect amounts, coefficients, cooldown, cost and other per-rank stats, the calculations no placeholder shows, and its level-up list as rows of label, value read and value shown.
- `ability`: the other spells of the same ability in the same form, each with the rule that grouped it (`joined_by`) when the group did not come from the game's ability object. `referenced`: any other spell the record's placeholders or its spell's calculations read. `spells_not_in_file` lists any of these spells, the record's own included, whose line was not handed in.
- `extended_text_hidden_in_game`, `rank_source` (when it is not the level-up list), `varies_by_rank` and `includes`, copied from the record.
- For a language other than English, `english`: the `text` and `filled` of the English input for the same `spell_path` and `text_field`, since the game data is the same in every language. `english_missing` is set when there is no English record.

A value that is the same at every rank is written once; one that differs by rank is written in full. Formulas keep every part and number of the game's own, with shorter names (`{"dv": "BaseDamage"}`, `{"stat": "AP", "coef": 0.5}`), and leave out only the fields that choose an icon or layout in the tooltip.

`build_input(rec, lines, english=None)` builds one input and `build_inputs(records, lines, english_records=None, english_lines=None)` builds a patch's. Both work only on what they are handed and read no file, and the input they return shares no object with it. Every worked-out value in an input (placeholder values, calculation values and the level-up list's shown values) is the one resolve_tooltips.py wrote, so the planting code resolves a changed copy again before building its input.

In 16.19 the 1,501 English inputs come to 3.42 million characters, with a median input of 1,998 characters. An earlier build of 3.33 million characters came to 1,113,760 tokens with the DeepSeek-V3 tokenizer, used as a stand-in for DeepSeek-V4-Pro's, about 3.0 characters per token.

## plant.py

Plants tooltip-calculation errors in a resolved patch's English records by the five fixed rules in PLAN.md ("Planted errors"). Each error makes a value that a placeholder of the text shows disagree with the same value shown elsewhere in the input. The change is made in place in the champion's data or the tooltip's text: nothing is added, one rule leaves out a part of a formula and another points a placeholder at a different value of the same spell. The champion is then resolved again with resolve_tooltips.py's own code and the input built again with inputs.py, so no worked-out value is left over from before the change. An error that fails the script's self-check is not written; it is counted and the next draw takes its place. The anchor rules, the size of each change and how records are drawn are in the script's `--help`.

```
python3 scripts/plant.py --patch 16.18 --set dev --seed 1003 --counts tooltip_calc=125 --max-share 0.5
python3 scripts/plant.py --verify data/planted/dev.manifest.json
```

The test set is made the same way on the final-run patch, with seed 2001, `--counts tooltip_calc=250`, no `--max-share` cap and `--exclude-manifest data/planted/dev.manifest.json`, and its manifest is written to `planted/test.manifest.json` in this repo.

It reads the patch from `data/raw` in English and writes `data/planted/<set>.jsonl`, one planted error per line with its planted input and an answer for the catch judge, and `data/planted/<set>.manifest.json` (`--manifest-out` puts it elsewhere). The manifest holds no tooltip text, only names and numbers: the seed, the patch and its CommunityDragon build, the counts requested and made, the `--max-share` cap, each rule's eligible records, spells and abilities and its cap, each share a rule gave to the others and why (`reallocated`), the draws not written and why, the project's git commit and the sha256 of plant.py, inputs.py and resolve_tooltips.py, the abilities left out by `--exclude-manifest`, and for each error its record, ability, rule, change (with its anchor) and the sha256 of its planted and original inputs. `--verify` makes the set again from `data/raw` and checks every hash. The same seed gives byte-identical files.

## baseline.py

The baseline script (PLAN.md, "Baseline"). It reads an inputs file or a planted set and writes one flag per line to `data/baseline/<name>.flags.jsonl`: the input id, text field, language, the value or claim the flag names, the check and rule that raised it, and a short reason. It checks English text only and has two checks, typed numbers and tooltip calculations. It prints how many pairs it could not compare because one side is unresolved. Its exact rules are in its `--help`. It has no randomness, so a second run gives the same file.

```
python3 scripts/baseline.py data/inputs/16.18.en_us.jsonl
python3 scripts/baseline.py data/planted/dev.jsonl --dev-report
```

On a planted set, `--dev-report` prints how many planted errors of each rule a flag catches: a flag on the planted record's placeholder that shows the changed calculation, the pointed-at value or a calculation that reads the changed data value. That count is for development only. Real catches are judged by the judge model (PLAN.md, "Keeping the test honest").

## check_model.py

The model checker (PLAN.md, "The experiment", step 4). It sends each record of an inputs file, a planted set or `data/inputs/realbugs.jsonl` to a language model through OpenRouter, one record per call, and writes one line per call to the `--out` file. A line that holds its input under `input` is read by its own `id`. Each call sends the fixed instructions and then the record as compact JSON without its id, so the model never sees a planted id. Each model's settings are fixed in `MODELS`. The strong model runs at temperature 1.0 with low reasoning effort, and the small model at temperature 0 with reasoning on. Both allow at most 32,000 tokens in the answer and use one pinned provider with fallbacks off. `--backup` uses the backup provider.

```
python3 scripts/check_model.py data/planted/dev.jsonl --model strong --run 1 --out runs/dev.strong.1.jsonl
python3 scripts/check_model.py data/inputs/16.19.en_us.jsonl --model small --run 1 --out runs/sweep.small.1.jsonl --backup
python3 scripts/check_model.py data/planted/dev.jsonl --model strong --run 1 --out x.jsonl --dry-run
```

A call that fails, for any reason or because its answer can't be read as flags, is retried up to 3 times with the same settings, then written with no flags and `failed` true. Running the same command again skips the records whose last line has `failed` false and calls the rest again, adding a new line for each; every reader takes the last line of each id. At the end it prints how many records failed, and warns when that is more than 5% (PLAN.md says to rerun on the backup providers).

Each line holds the id, the model, the provider asked for (`pinned`) and the one that served the call, the prompt version, the run number, the time (UTC), the prompt, completion and cached tokens and OpenRouter's cost (each added up over every attempt that returned them), the flags, `failed`, the number of attempts and, for a failed call, the last error. `PRICES` gives each provider's price per million tokens, which evaluate.py uses for the cost of run 1. The key is read from `OPEN_ROUTER_API_KEY`, or from the `.env` file of the parent folder.

## evaluate.py

Scores the runs (PLAN.md, "Keeping the test honest", "Tests", "False alarms") in three steps. Each method is named as `NAME=file[,file...]`, one file per run in run order; the script's file is baseline.py's output and its method is named `baseline`.

```
python3 scripts/evaluate.py judge data/planted/test.jsonl --run strong=r1,r2,r3 --run small=r1,r2,r3 --run baseline=flags.jsonl --out data/eval/judged.test.json
python3 scripts/evaluate.py judge answer_key/confirmations.csv --run strong=r1,r2,r3 --run small=r1,r2,r3 --run baseline=realbugs.flags.jsonl --out data/eval/judged.real.json
python3 scripts/evaluate.py label data/inputs/16.19.en_us.jsonl --run strong=r1,r2,r3 --run small=r1,r2,r3 --run baseline=flags.jsonl --out data/eval/labels.json
python3 scripts/evaluate.py report --judged data/eval/judged.test.json --judged data/eval/judged.real.json --labels data/eval/labels.json --out data/eval/report.json
```

`judge` takes each planted error, found by its planted id, or each confirmed real bug, found by its record's id (the id of its line in `data/inputs/realbugs.jsonl`). It reduces every method's flags on that record to a common form, then pools, shuffles and sends them to the judge model, which says whether each flag names the error. A method catches an error on a run if any of its flags does, and a model catches it if it does so on 2 of its 3 runs. `label` draws up to 200 flags per method from run 1 of the false-alarm sweep, pools and shuffles them, and the judge labels each one from the record alone: real mismatch, not a mismatch, or can't tell. A model run is read as the last line of each id.

A flag's common form keeps the record, the text field and what it names: its `@Placeholder@` tokens, or else a few of its quoted words with any HTML tags taken out. A script flag on a typed number keeps the number with up to two whole words of the same sentence on each side, so it reads like a short quote (`"Cooldown by 50%"`).

`report` gives the McNemar tests, recall by rule and by kind with their intervals, precision and flags per 1,000 records, the failed calls on every planted, real-bug and sweep run, and the cost of the strong model's run 1 of the sweep. That cost is worked out from the logged tokens at the pinned provider's prices, with cached prompt tokens at the cache-read price, and OpenRouter's billed cost is given beside it. Given both a planted set's judgments and the labels, the first report writes `data/eval/spot_check.csv` with 10 catch judgments from the planted set and 10 labels; fill in its `author` column and run report again to score them. Without both, it skips the spot checks and says so.

Judgments are cached in `--cache`, so a stopped run picks up where it left off and an identical pair is judged once. The judge thinks at medium effort with at most 16,000 tokens. `--dry-run` prints the number of calls still to make and the first request, and makes no call.

## realbug_inputs.py

Builds the checkers' inputs for the real bugs (PLAN.md, "Real bugs"). For each confirmed bug in `answer_key/confirmations.csv`, it builds, in the patch the bug was checked in, the input of every checked record of the bug's ability: the bug's own spell, the spells in its group and the records in its slot. A translation bug's inputs are in its language, each with the English text of the same record beside it. The resolved files must come from the CommunityDragon build the answer key names; otherwise the script stops and says which patch to resolve.

```
python3 scripts/realbug_inputs.py
```

It writes `data/inputs/realbugs.jsonl`, one line per input: `{"id", "kind": "real", "bug", "own_record", "input"}`, where `id` is the input's own id and `own_record` marks the bug's own record, the only one where a flag can count as a catch. baseline.py and check_model.py both read the file like a planted set, so their lines carry the record's id, which evaluate.py uses to find the bug.

## Final session

The order of the final session (PLAN.md, "Keeping the test honest"). `P` is the final-run patch, 16.19 (Riot's 26.19), chosen 2026-10-07. Model runs and judgments go in `runs/final/`, which is committed.

```
python3 scripts/fetch_cdragon.py --patches P
python3 scripts/resolve_tooltips.py --patches P
python3 scripts/inputs.py --patch P
python3 scripts/plant.py --patch P --set test --seed 2001 --counts tooltip_calc=250 --exclude-manifest data/planted/dev.manifest.json --manifest-out planted/test.manifest.json
# commit planted/test.manifest.json and P before any model call on P
python3 scripts/baseline.py data/planted/test.jsonl --out runs/final/test.baseline.jsonl
python3 scripts/baseline.py data/inputs/P.en_us.jsonl --out runs/final/sweep.baseline.jsonl
python3 scripts/baseline.py data/inputs/realbugs.jsonl --out runs/final/real.baseline.jsonl
# for M in strong small, N in 1 2 3:
python3 scripts/check_model.py data/planted/test.jsonl --model M --run N --out runs/final/test.M.N.jsonl
python3 scripts/check_model.py data/inputs/P.en_us.jsonl --model M --run N --out runs/final/sweep.M.N.jsonl
python3 scripts/check_model.py data/inputs/realbugs.jsonl --model M --run N --out runs/final/real.M.N.jsonl
python3 scripts/evaluate.py judge data/planted/test.jsonl --run strong=runs/final/test.strong.1.jsonl,runs/final/test.strong.2.jsonl,runs/final/test.strong.3.jsonl --run small=... --run baseline=runs/final/test.baseline.jsonl --out runs/final/judged.test.json --cache runs/final/judge_cache.jsonl
python3 scripts/evaluate.py judge answer_key/confirmations.csv --run strong=... --run small=... --run baseline=runs/final/real.baseline.jsonl --out runs/final/judged.real.json --cache runs/final/judge_cache.jsonl
python3 scripts/evaluate.py label data/inputs/P.en_us.jsonl --run strong=... --run small=... --run baseline=runs/final/sweep.baseline.jsonl --out runs/final/labels.json --cache runs/final/judge_cache.jsonl
python3 scripts/evaluate.py report --judged runs/final/judged.test.json --judged runs/final/judged.real.json --labels runs/final/labels.json --out runs/final/report.json
```

If more than 5% of a run's calls still fail, the whole session is rerun with `--backup` into a new folder, and the first session's files are kept and not scored. Sweep run 1 is not resumed, since its cost would then leave out the failed first attempts.

## mine_patch_notes.py and patches.py

`mine_patch_notes.py` reads Riot's English patch notes from 2020 on and lists every line that reports a tooltip or text correction in `answer_key/candidates.csv`, for checking by hand. `answer_key/README.md` explains the columns and how lines are rated.

```
python3 scripts/mine_patch_notes.py                  # download what is missing, then rebuild the list
python3 scripts/mine_patch_notes.py --offline        # rebuild from the saved pages only
```

`patches.py` turns a patch notes name (`13.1B`, `25.S1.2`, `25.04`, `26.19`) into the CommunityDragon folder the change first appears in and the folder before it, using CommunityDragon's live patch list. It also maps champion names to their CommunityDragon folders. The miner uses it to fill the `cdragon_patch`, `prefix_patch` and `champion_folder` columns. Run on its own, it prints the mapping for every patch in a CSV (`answer_key/candidates.csv` unless another is named):

```
python3 scripts/patches.py
python3 scripts/patches.py --offline                 # use the saved patch list
```

To look up the tooltip a candidate line is about, fetch and resolve its `prefix_patch`, then find the records in `data/resolved/<prefix_patch>.en_us.jsonl` whose `champion_folder` matches the line and whose spell is in the group of that slot's spell: a record's `spell_context` leads to its line in the spells file, and the line's `group` lists the ability's spells. Matching `slot` alone (even allowing `<slot>-form`) misses spells in slot `other`, such as 10.12 `SionWDetonate`, which is part of Sion's W. The `slot` column lines up with `champion_folder` by position, so each champion is matched only with its own slots (`answer_key/README.md` has the format). For a translation row, fetch and resolve the `prefix_patch` in the language the line names (`--locales zh_cn` for fetch, `--locale zh_cn` for resolve) and look in `data/resolved/<prefix_patch>.<locale>.jsonl` instead.

## Tests

```
python3 -m unittest discover -s tests
```

The tests need no network.
