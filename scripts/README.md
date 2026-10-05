# Scripts

Run everything from the project root. Every script takes `--help`. Downloads and outputs go under `data/`, which is not committed. The usual order is: mine the patch notes, fetch the patches they point to, then resolve those patches.

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

`manifest.json` in each patch folder records the build, which text file was saved for each language (`stringtable_layout`, `stringtable_path`), the champion counts (`champions`, with `bin_saved` for patches before 11.1, and `list_source`, which says where the champion list came from: for a borrowed list, `from_patch`, the list's path in that patch as `file`, and `saved_in_this_folder: false`. Manifests written before `list_source` was added don't have it, and older ones that have it may lack `saved_in_this_folder` or give `file` with the patch in front, as in `11.6/plugins/...`), every file with its size, any failures, and how long the first download took.

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

The summary counts how many spells-file lines are in a slot-spell group and in an ability-object group (`spell_contexts_in_slot_spell_group` and `spell_contexts_in_ability_object_group`, under `counts`), and how many joined by each rule (`spell_contexts_joined_by`). For a readable text file it also counts the tooltip keys found only under their hash rather than their name (`keys_found_only_by_hash`) and the level-up labels found that way (`level_up_labels_found_only_by_hash`). Both are null for a binary table, which holds only hashes.

A record of the text shown while Shift is held has `extended_text_hidden_in_game: true` when its spell turns that text off (`EnableExtendedTooltip` false), so players never see it. It is still a checked record.

The game numbers each stat a scaling can use (AP, bonus AD and so on), and the numbering has changed four times. The summary's `stat_layout` says which numbering the resolver found: D for 10.20 and older, C for 10.21 to 11.10, A for 11.11 to 15.6, E for 15.7 to 15.15 and B for 15.16 on.

Two kinds of record are not tooltips to check, and are dropped when building the set of tooltips that get checked. The summary's `checked_records` counts the records left after dropping them, overall and for `keyTooltip`.

- A record with `duplicate_of` set holds a text that another spell of the same champion shares with the spell the text belongs to, and `duplicate_of` gives that spell's path. When two or more spells of a champion name the same text, it belongs to the only one of them in slot P, Q, W, E or R. If none or several are, it belongs to the only one whose script name the text key carries (`Spell_<Script>_Tooltip`). The owner may itself be stored under a hashed path. Every other spell of the champion that names the text gets `duplicate_of`, under a hashed or a readable path (`MalzaharWCancel` in 15.1 is marked as a duplicate of `MalzaharW`). If neither rule finds a single owner, no record is marked.
- A record whose `text_field` is `passiveToolTip` is the champion's short summary text (the passive description shown in champion select), not an in-game tooltip. It is read only when no passive spell names a `keyTooltip`: either the passive spell has none, or no passive spell is found at all. These records have been seen in early patches such as 10.1 and 10.20.

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
