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

`kind_guess` is a rough first sort. During hand confirmation, each confirmed bug is either given one of the four kinds in `PLAN.md` (`typed_number`, `wording`, `translation` or `tooltip_calc`), or excluded with its reason written down (for example, a tooltip that didn't appear on hover). `typed_number` means a number typed by hand into the English text that disagrees with the game. A number that is wrong in another language only is `translation`. Real bugs are reported per kind as a descriptive case study. The primary test is described in `PLAN.md`.

## Which game files to compare

Riot's patch notes and CommunityDragon number patches differently, so `scripts/patches.py` maps one to the other. Patches 10.1 to 14.24 keep their number. The 2025 names become 15.x: `25.S1.1`, `25.S1.2` and `2025.S1.3` are 15.1, 15.2 and 15.3, and `25.04` to `25.24` are 15.4 to 15.24. The 2026 names `26.N` become 16.N.

`cdragon_patch` is that folder and `prefix_patch` is the folder before it in CommunityDragon's live list, so the gaps come out right: CommunityDragon has no 10.17, 12.24 or 13.2 folder, so the folder before 13.1 is 12.23 and the one before 13.3 is 13.1. Two pages describe a release that got no game version of its own. The page titled Patch 10.17 (its address says 10.16b) shipped as a 10.16 build, and 13.1B as a 13.1 build. CommunityDragon's folders hold a build from around release day: the 10.16 folder holds build 10.16.3309186, dated 2020-08-05, and the 13.1 folder holds one dated 2023-01-14 (checked on 2026-10-05). So those two pages' changes first appear in 10.18 and 13.3, with 10.16 and 13.1 as the folders before. In code, any lettered name, or a number with no folder of its own, maps to the next folder.

All 163 pages map to a folder pair. Lines in a page's Mid-Patch Updates section shipped later in that patch, so the `cdragon_patch` folder may or may not hold the fix. `prefix_patch` comes before the change either way, so checking against it is safe. The 10.1 page's `prefix_patch` is 9.24, from 2019.

## Confirmations

`confirmations.csv` holds the result of checking each candidate line by hand against the game files. It is a draft until it is frozen in the commit made before the first model run of any kind, as `PLAN.md` requires.

A candidate line that could be about a champion ability became one or more units, one per champion and ability, so a line naming three champions gives three units. The other 117 lines, about items, runes, summoner spells, game-mode features or the client, have no unit (see below). Each of the 228 units from the first check was checked against the files and then rechecked by a second, independent pass. The 7 units added later, when the lines with no champion folder were read again, were each checked once, and the verifier spot-checked them. All 7 are excluded as not champion abilities.

Every one of the 336 lines was handled in one of three ways:

- 212 lines were checked as units from the start: the 148 with a champion in `champion_folder`, and the 64 whose notes say no subject was found. Five of those 64 do have a `subject` but no champion folder (the two K'Sante lines, Warden's Mail, Muramana and a page heading), and the two K'Sante lines became K'Sante units.
- The other 124 lines have no champion folder. 78 of them name an item, rune, summoner spell or other subject that isn't a champion, and 46 are game-mode lines with no subject (the no-subject note is never added to a game-mode line). Each was read by its subject, quote and section. Seven could be about a champion ability, because they name a champion, one of a champion's abilities or champion abilities in general, or (rows 213 and 220) are tooltips for Ult-ernate Summoner Spells, champion ultimates offered as summoner spells in Ultimate Spellbook. They were checked and added as units. All seven are text that exists only in a game mode, so all seven are excluded.
- The remaining 117 lines are about items, runes, summoner spells, game-mode features or the client, and have no unit.

So the file covers 219 of the 336 lines. Of its 235 units, 12 are confirmed (8 `tooltip_calc`, 3 `wording`, 1 `translation` and no `typed_number`), 24 are not confirmed and 199 are excluded. None is disputed: the units the two passes disagreed on were settled by the rules below and a recheck of the files.

| Column | Meaning |
|---|---|
| `unit_id` | `<patch_name>-<champion_folder>-<slot>`, with `none` or `any` when either is missing. When two units would share an id, `-r<row_index>` is added |
| `row_index` | The line's data row in `candidates.csv`, counting from 0 |
| `patch_name`, `prefix_patch` | Copied from `candidates.csv` |
| `prefix_cdragon_version` | The CommunityDragon build in the `prefix_patch` folder. The folder named 10.11 holds a 10.10 build, so rows checked there were checked against 10.10 |
| `champion_folder`, `slot`, `spell_path`, `text_field`, `loc_key` | The record the bug is about, as far as one was found. For a confirmed unit, this is the one checked record a flag must land on |
| `locale` | The language of that text: `en_us`, or the language of a translation bug (`zh_cn`). Empty when no record was found |
| `status` | See below |
| `mechanism` | See below |
| `text_says`, `data_says` | What the text and the data say in the folder checked, as short excerpts |
| `post_fix_change` | What changed in the folders after the fix |
| `reason` | Why the unit got its status |

**Status**

- `confirmed`: the line states a bug, the text disagrees with the game data in the folder checked, and the fix changed that.
- `not_confirmed`: the line names a champion and no exclusion applies, but the text agrees with the data, the ability or the mismatch can't be found in the files, or the line is not a stated bug (see the rules below). Two of these units (Rek'Sai in 14.5 and Dr. Mundo in 12.22) have no record: the line names no ability, and none of that champion's text disagreed with the data.
- `excluded`: not a mismatch between a champion ability's text and its data, for the reason in `mechanism`.
- `disputed`: the two passes reached different verdicts and no decision has been made. No unit has this status now.

**Mechanism**

The first four are the kinds in `PLAN.md`:

- `typed_number`: a number typed by hand into the English text disagrees with the data.
- `wording`: English words disagree with the data, including an effect the text leaves out whose value is shown in the data (see the rules below).
- `translation`: the text is wrong only in a language other than English.
- `tooltip_calc`: a placeholder is filled from a calculation or value used only by the tooltip, or points at the wrong calculation or value, and it disagrees with the value the ability actually uses. That value is shown elsewhere in the data or in the same text (Shyvana E's total uses 4.5 seconds while its own sentence says 4).

The rest are reasons for exclusion:

- `not_champion_ability`: items, runes, summoner spells, client screens, and text that exists only in a game mode (Arena, ARAM, Swarm, Ultimate Spellbook, League Classic).
- `not_text_vs_data`: a tooltip that didn't appear, a display flag that hid or changed how text or a calculation is shown, a display that didn't update during play, a live counter, Collection tab or shop text, a balance change or rework, or a game fix that made the game match a correct tooltip.
- `not_visible_in_files`: the text may well have been wrong, but the true value or rule lives in the game's scripts, or is not shown in the `prefix_patch` data as the rules below define it, so the files can't show the bug.
- `level_up_list_only`: the bug is only in the generated level-up list, which is not a checked text field.
- `same_bug_as_other_row`: the same fix as another unit; the reason names it.
- `record_not_found`: the line names no champion whose ability could be looked up.

These rules were decided on 2026-10-05 and apply to every unit:

- A value counts as shown in the files only when the `prefix_patch` folder identifies what it is, in one of three ways: by its own name (a data value, a calculation, or an engine field with a fixed meaning such as the spell's AP ratio), by a label in the same spell's level-up list, or by a tooltip text in the same folder that fills a placeholder with it and says what it is (in 10.12, Sion W's own text says it "gains @Effect5Amount@ maximum Health", which identifies that value). A value whose meaning comes only from matching the fix, or only from a later folder, is not shown (Warwick's passive, Vladimir Q, Singed W).
- An effect the text leaves out counts as `wording` when its value is shown in this way (Lillia W's `MinionDamageMod`, Yorick E's minimum damage, labeled in its level-up list). Otherwise it is `not_visible_in_files`.
- When a confirmed mismatch fits two kinds, its kind is the side the fix changed. Shyvana E in 14.15 types "4 seconds", which disagrees with the 4.5 seconds its tooltip-only calculation uses. The fix changed the calculation, so it is `tooltip_calc`.
- A line Riot words as a clarification (clarify, clarified, clarifies, clarity), or one that only gives designer context and reports no change, is not a stated bug. A unit that would otherwise be confirmed is then `not_confirmed`, even when the data supports the new text (Yorick's passive in 14.5, Yasuo's and Yone's passives in 11.1). A line saying the tooltip now shows or displays something reports a change to what it shows, and is checked like a fix (Malzahar W in 25.S1.2, Yorick E in 11.23).
- Exclusions are decided before the stated-bug rule, which applies only to units no exclusion covers. A clarification whose true rule lives in the game's scripts is therefore `not_visible_in_files`, not `not_confirmed`. A line that names a champion but whose ability or mismatch can't be found is `not_confirmed`; `record_not_found` is only for a line that names no champion.
- A bug only in a level-up list is excluded as `level_up_list_only`, because no flag on a checked record can catch it (Garen E, Sion Q, Riven Q, Elise E).
- A display flag or a client display problem is `not_text_vs_data` (Caitlyn R, Miss Fortune's passive, the Zac, Gangplank and Nocturne passive cooldowns in 25.10).
- A bug is checked only in `prefix_patch`. Diana's passive is not confirmed, because the balance change that caused its bug shipped one patch before the fix, so the 14.5 folder shows no mismatch.

Patch notes text is quoted only in short lines for reference. It belongs to Riot Games.
