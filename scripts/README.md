# Scripts

Run everything from the project root. Every script takes `--help`. Downloads and outputs go under `data/`, which is not committed. The usual order is: mine the patch notes, fetch the patches they point to, then resolve those patches.

## fetch_cdragon.py

Downloads live patches from CommunityDragon into `data/raw/<patch>/`, keeping the server's paths. For each patch it saves the build file (`content-metadata.json`), the tooltip text for each requested language, the champion list (`champion-summary.json`) and every playable champion's game data (`game/data/characters/<champion>/<champion>.bin.json`). For patches before 11.1 it also saves each champion's binary `.bin` file, because the JSON exports of those patches leave out the class names the resolver needs.

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

`manifest.json` in each patch folder records the build, which text file was saved for each language (`stringtable_layout`, `stringtable_path`), the champion counts (`champions`, with `bin_saved` for patches before 11.1), every file with its size, any failures, and how long the first download took.

CommunityDragon sometimes replaces a patch folder with a later build. Each run first compares the server's build with the one on disk. If they match, files already on disk are checked and reused. If they differ, the script stops for that patch rather than mix two builds; `--refresh` deletes the folder and downloads it again. The script exits with code 1 if any patch stopped or any file failed.

## resolve_tooltips.py

Links each champion ability to its tooltip text and works out the number behind every `@placeholder@`, per rank, keeping stat scalings symbolic (`+50% AP`). It also lists numbers typed straight into the text. It reads every tooltip field a spell names: the tooltip, the longer text shown while Shift is held, and the simple tooltip. It reads the text file from every place in the table above, including the binary table of patch 10.25 and older, and for patches before 11.1 it reads the champion `.bin` files that fetch saved.

```
python3 scripts/resolve_tooltips.py --patches 16.19 15.1
python3 scripts/resolve_tooltips.py                         # every patch under data/raw
python3 scripts/resolve_tooltips.py --patches 16.19 --locale fr_fr
```

It writes two files per patch and language: `data/resolved/<patch>.<locale>.jsonl` with one record per spell and text field, and `data/resolved/<patch>.<locale>.summary.json` with coverage counts, the reasons any value was not worked out, and the CommunityDragon build the files came from (`cdragon_version`). Coverage and reasons are given for all records and again for slots P, Q, W, E and R alone (`placeholder_coverage_pqwer_slots`, `unresolved_reasons_pqwer_slots`). Each record has `champion_folder` and `slot` (`P`, `Q`, `W`, `E`, `R`; a second form of an ability is `Q-form` and so on, other spells are `ability-child` or `other`).

Two kinds of record are not tooltips to check, and are dropped when building the set of tooltips that get checked. The summary's `checked_records` counts the records left after dropping them, overall and for `keyTooltip`.

- A record with `duplicate_of` set holds a text that a spell under a hashed path shares with the spell the text belongs to, and `duplicate_of` gives that spell's path. When two or more spells of a champion name the same text, it belongs to the only one of them in slot P, Q, W, E or R. If none or several are, it belongs to the only one whose script name the text key carries (`Spell_<Script>_Tooltip`). The owner may itself be stored under a hashed path. Every other spell under a hashed path that names the text gets `duplicate_of`; spells under readable paths never do. If neither rule finds a single owner, no record is marked.
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

To look up the tooltip a candidate line is about, fetch and resolve its `prefix_patch`, then find the records in `data/resolved/<prefix_patch>.en_us.jsonl` whose `champion_folder` and `slot` match the line (allowing `<slot>-form` too). The `slot` column lines up with `champion_folder` by position, so each champion is matched only with its own slots (`answer_key/README.md` has the format). For a translation row, fetch and resolve the `prefix_patch` in the language the line names (`--locales zh_cn` for fetch, `--locale zh_cn` for resolve) and look in `data/resolved/<prefix_patch>.<locale>.jsonl` instead.

## Tests

```
python3 -m unittest discover -s tests
```

The tests need no network.
