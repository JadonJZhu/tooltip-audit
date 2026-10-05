# Answer key candidates

`candidates.csv` lists every line in Riot's official League of Legends patch notes, from patch 10.1 (January 2020) to 26.19, that reports a correction to a tooltip, an ability or item description, or other in-game text. These are leads, not confirmed bugs. A line becomes part of the answer key only after the bug is found in the game files from the patch before the fix.

The script found 163 patch notes pages for that range. Every patch number in that range has a page except 12.24 and 13.2, which don't exist; 13.1B came out between 13.1 and 13.3 and has its own page.

## How it was made

`scripts/mine_patch_notes.py` downloads the English patch notes pages from leagueoflegends.com, keeps a copy under `data/patch_notes/` (not committed), and splits each page into lines with their headings. A line is kept if it talks about a tooltip, description or displayed text. A line about visual effects, skins, the client, the Collection tab or other text that isn't part of an ability, item, rune or summoner spell is dropped, unless it also mentions a tooltip or description: then it is kept as borderline with a note. Champion, item, rune and summoner spell names come from Riot's Data Dragon files for the latest patch and the first patch of each year since 2020, so items and runes removed since then are still recognized. CommunityDragon's patch list and champion list, and Data Dragon's ability names, are saved under `data/` the same way, so `--offline` works once they have been downloaded. Lines are rated by simple word rules, so the ratings are a first sort for a person to check, not a verdict.

```
python3 scripts/mine_patch_notes.py                  # 2020 to now
python3 scripts/mine_patch_notes.py --offline        # rebuild from the saved pages
python3 scripts/mine_patch_notes.py --recheck-missing  # look again for pages that were missing, e.g. a new patch
```

The script stops with an error if it can't load the names, because without them no line can be rated high and the file would look complete when it isn't.

## Columns

| Column | Meaning |
|---|---|
| `patch_name` | Riot's name for the patch, as in the page title (`10.25`, `13.1B`, `25.S1.2`, `2025.S1.3`, `26.19`) |
| `cdragon_patch` | The CommunityDragon folder whose game files first include the change (see below) |
| `prefix_patch` | The CommunityDragon folder just before `cdragon_patch`: the last one without the change, where a fixed bug should still be visible |
| `notes_url` | The patch notes page |
| `section` | The page section and sub-heading the line sits under |
| `subject` | Champion, item, rune or summoner spell the line is about, when it could be worked out (several names are separated by `;`) |
| `champion_folder` | For a line about a champion, the champion's folder name on CommunityDragon: the alias in `champion-summary.json`, in lower case (Wukong is `monkeyking`, Nunu & Willump is `nunu`). Several are separated by `;`. Empty for a line about an item's text that also names a champion (Bloodward's description, upgraded by Ornn) |
| `slot` | For a champion line, the ability it names for each champion in `champion_folder`, in the same order and also separated by `;`: `P` (passive), `Q`, `W`, `E` or `R`. One champion's several slots are joined by `+` (`Q+E`). An entry is empty when no slot is named for that champion (`mel;lulu` has slot `W;`), and the whole column is empty when none is named for any of them. See below for how slots are found |
| `quote` | The line itself, shortened to the relevant sentences when it is long |
| `kind_guess` | `typed_number` (the line mentions a number or value; a broader guess than the confirmed category defined below), `wording` (the text says the wrong thing), `translation` (wrong in one language only) or `other` |
| `confidence` | `high`: phrased as a fix to a named champion, item, rune or spell's text, with none of the notes below. `borderline`: anything else worth a look |
| `notes` | Empty for high rows. For borderline rows, every reason that applies: game mode only, a clarification rather than a stated bug, a balance change, designer commentary, a designer note that the tooltip will catch up later, the game was changed to match the text, the tooltip didn't appear (on hover, for example), the display didn't update during play, a live stat counter, Collection tab text, other non-ability text, formatting only, a weak text signal, not phrased as a fix, no subject found, or item text mentioning a champion |

The slot comes from the ability heading above the line, which belongs to the first champion. Failing that, it comes from a slot letter or the word Passive in the line, and failing those, from the champion's ability names in Data Dragon (an ability name that has been in two of that champion's slots gives none). On a line with one champion, every slot it names is that champion's. On a line with several, a slot counts only when a champion's name comes just before it ("Mel's W"; "Zac, Gangplank, and Nocturne's passive" gives `P;P;P`). A slot that can't be tied to one champion is left empty.

`kind_guess` is a rough first sort. During hand confirmation, each confirmed bug is either given one of `typed_number`, `wording` or `translation`, or excluded with its reason written down (for example, a tooltip that didn't appear on hover). `typed_number` means a number typed by hand into the English text that disagrees with the game. A number that is wrong in another language only is `translation`. Only `typed_number` bugs enter the main test of the model against the script, because the script can only check numbers.

## Which game files to compare

Riot's patch notes and CommunityDragon number patches differently, so `scripts/patches.py` maps one to the other. Patches 10.1 to 14.24 keep their number. The 2025 names become 15.x: `25.S1.1`, `25.S1.2` and `2025.S1.3` are 15.1, 15.2 and 15.3, and `25.04` to `25.24` are 15.4 to 15.24. The 2026 names `26.N` become 16.N.

`cdragon_patch` is that folder and `prefix_patch` is the folder before it in CommunityDragon's live list, so the gaps come out right: CommunityDragon has no 10.17, 12.24 or 13.2 folder, so the folder before 13.1 is 12.23 and the one before 13.3 is 13.1. Two pages describe a release that got no game version of its own. The page titled Patch 10.17 (its address says 10.16b) shipped as a 10.16 build, and 13.1B as a 13.1 build. CommunityDragon's folders hold a build from around release day: the 10.16 folder holds build 10.16.3309186, dated 2020-08-05, and the 13.1 folder holds one dated 2023-01-14 (checked on 2026-10-05). So those two pages' changes first appear in 10.18 and 13.3, with 10.16 and 13.1 as the folders before. In code, any lettered name, or a number with no folder of its own, maps to the next folder.

All 163 pages map to a folder pair. Lines in a page's Mid-Patch Updates section shipped later in that patch, so the `cdragon_patch` folder may or may not hold the fix. `prefix_patch` comes before the change either way, so checking against it is safe. The 10.1 page's `prefix_patch` is 9.24, from 2019.

Patch notes text is quoted only in short lines for reference. It belongs to Riot Games.
