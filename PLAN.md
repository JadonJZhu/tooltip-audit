# Plan

Written 2026-10-04. Experiment design and success criteria set 2026-10-05, before any model prompt was written or any model was run. The commit that adds this version is the record of the design; compare its date with the commits that hold the results.

## The question

When a designer changes an ability, its tooltip is supposed to change with it. Sometimes it doesn't, players read wrong information, and the fix ships in a later patch. Can a language model, given each tooltip and the game data behind it, flag those mismatches more often than a simple script, at a false-alarm rate a person would put up with?

## Patch numbers

Riot's public patch names (26.x in 2026, 25.x and the 25.S1 names in 2025) differ from the game's internal version numbers (16.x, 15.x) that CommunityDragon uses. Up to 2024 the two match. This plan uses Riot's patch names, with the game version in parentheses where both appear.

## How tooltips work today

League tooltips are mostly templates. The English text for Ahri's Q is stored as:

> Ahri throws then pulls back her orb, dealing @TotalDamage@ magic damage on the way out and @TotalDamage@ true damage on the way back.

`TotalDamage` is a named calculation in the ability's game data (base damage by rank plus 50% of ability power), so when a designer changes those values the tooltip updates on its own. That design already prevents the most obvious kind of stale number.

## What the templates can't catch

1. **Numbers typed into the English text by hand.** In patch 26.19 (game version 16.19), 215 of the 974 checked records in the main tooltip field (see "Data") have at least one number written directly into the sentence (292 numbers in all), for example Sion's ultimate charging "for 8 seconds" and Riven's E shield lasting "for 1.5 seconds". If the underlying value changes, the text doesn't.
2. **English words that disagree with the data.** The text says magic damage and the data deals physical, says "bonus AD" (only the attack damage added by items and other effects) where the formula uses total attack damage, describes a slow the ability no longer has, or leaves out a new effect.
3. **Translations.** Each language is its own copy of the text, so a number or a meaning can be wrong in another language while the English is right. Any bug that exists only outside English is this kind, even when it is a hand-typed number.

The script and the primary test use the English text only, so the script can only see the first kind. The second and third are where a language model might add something, and they are measured on planted errors, with recall on real bugs of those kinds reported as exploratory (see "Tests").

## Data

- Tooltip text and the per-patch game data, from [CommunityDragon](https://raw.communitydragon.org/), a fan-run archive of the game's files for each past patch. Each patch folder holds a build from around the patch's release day (the 10.16 folder is dated 2020-08-05), so a fix shipped in a mid-patch update may or may not be in that patch's own folder. The mapping from patch notes to folders is in [answer_key/README.md, "Which game files to compare"](answer_key/README.md#which-game-files-to-compare).
- Riot's patch notes, for the list of tooltip bugs that were fixed and when.
- Riot's [Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon), for champion, item, rune and summoner-spell names. The patch-notes search uses them to find lines about each; lines about items, runes and summoner spells are then left out (see "Scope"). Data Dragon has the tooltip text but not the values behind it, which is why CommunityDragon is needed.
- Live patches only. No unreleased content in anything we publish.

The experiment checks every tooltip text a champion ability links to: the main tooltip field, the extended text shown while Shift is held, and the short simplified tooltip some abilities have. The one-line summary some abilities also have is not checked. The unit is a record: one text field of one spell. Two kinds of record are dropped because they aren't tooltips to check ([scripts/README.md](scripts/README.md)): a spell's copy of a text another spell's record already holds, and the champion's short summary text from champion select. A few records that remain still hold the same text as another record, and each is checked. In patch 26.19 there are 1,540 checked records, 974 of them in the main tooltip field.

The @...@ placeholders are filled in with values from the game data where the data allows: 93% of the placeholders in the main tooltip field in patch 26.19. An unfilled placeholder is shown to the model and the script as-is (the raw @Name@), and the script doesn't treat it as a typed number.

**Scope.** Champion abilities only. Items, runes and summoner spells are out. The scope, the answer key and the baseline script may change before the first model run of any kind, never after (see "Keeping the test honest"), and any change is recorded here with its date.

## The experiment

1. **Answer key.** Collect every tooltip correction in Riot's patch notes from patch 10.1 (January 2020) to patch 26.19 (the latest notes as of 2026-10-05). For each, confirm the bug is visible in the game files from before the fix. For a fix listed in patch N's notes (including N's mid-patch updates), the bug is checked in the CommunityDragon folder just before the first folder that holds patch N (the exact rule is in [answer_key/README.md](answer_key/README.md#which-game-files-to-compare)). A lettered page such as 13.1B counts as its own N, so its bugs are checked in the 13.1 folder. The folder checked predates the fix whether or not the first folder for N holds it (see "Data"). The CommunityDragon build version used is recorded per bug.
   - **Unit:** one bug per champion and ability. A patch-notes line naming three champions is three bugs.
   - **Kind:** each confirmed bug is given one of the three kinds above. A candidate that isn't a mismatch between text and data is excluded: a tooltip not appearing on hover, a display not updating during play, live counters, text in the Collection tab. Every exclusion is listed with its reason.
2. **Planted errors.** Errors of each kind are inserted into a live patch's tooltips by fixed rules, not by a language model, so the same kind of model doesn't both make and find them. Translation errors are planted in German, Spanish, French and Brazilian Portuguese (`de_de`, `es_es`, `fr_fr`, `pt_br`), 25 in each language in the test set. Development errors, which prompts are tuned on, go into a patch older than the final-run patch. The final-run patch is the latest live patch on the date of the final session, so it is newer than every patch seen during tuning. The patches used are recorded.
3. **Baseline.** A plain script that compares each hand-typed number in the English text to the matching value in the game data.
4. **Model checker.** Give a language model each checked text on its own (one record per call, with its filled-in values) and ask for every mismatch, with a reason. For translation checks, the model sees the English text and the translation side by side. For a real bug, the records of the bug's ability in the folder checked are given to the model, and the script checks the same records. The bug counts as caught only through a flag on the bug's own record; flags on the ability's other records don't count toward recall. We use open-weight models (models whose weights are published) to keep the cost per run low, through [OpenRouter](https://openrouter.ai/), a service that serves many hosted models through one API:
   - small: Qwen3.8-27B (`qwen/qwen3.8-27b`)
   - strong: DeepSeek-V4-Pro-0813 (`deepseek/deepseek-v4-pro-0813`)

   Each model is pinned to a fixed version rather than a "latest" alias and runs at temperature 0 (the setting that makes it pick its most likely next token). Each is served by one pinned provider that runs the weights at 8-bit precision (fp8) or better rather than a more compressed copy, with fallback to other providers turned off, so a call fails rather than silently moving to a different provider. Every call logs which provider served it, as a check.
5. **Write up** the result, including where it failed.

## Keeping the test honest

- Every confirmed real bug is in the test set. There is no development set of real bugs.
- Prompts are tuned only on planted development errors. Planted development and test errors use different random seeds. The planted test set has 100 errors of each kind.
- Before the first model run of any kind, prompt tuning included, these are fixed and committed to this repo: the answer key (the confirmed bugs, the kind given to each, the exclusion list with reasons, and the build version per bug), the baseline script, and the planting code (the rules for making errors of each kind).
- Before the final session, these are also fixed and committed: the planting seeds, the planted test set, the seed for the random draws (the flags to label and the author's spot check, see "False alarms"), the final prompts, the catch rubric, the flag-labeling rubric, the judge's prompts, the provider and a backup provider chosen for each model, and the final-run patch number.
- The test sets and the false-alarm sweep are run in one final session. Each model runs 3 times, because hosted models aren't fully deterministic even at temperature 0. For each bug and planted error, the majority vote of the 3 runs feeds every test below, and the range across runs is reported. The false-alarm sweep uses run 1 (see "False alarms"). The script is deterministic and runs once.
- A failed model call is retried up to 3 times with the same settings. A call that still fails, or whose output can't be parsed into flags, counts as no flags, and the number of such calls is reported for each run. If more than 5% of a run's calls still fail after retries, the whole final session is stopped and rerun on the backup providers, and the switch is reported.
- Before judging and labeling, every flag is reduced to a common format (the tooltip, the text field, and the value or claim it names), and the model's reason is removed, so the judge can't tell methods apart by format.
- **What counts as a catch:** a flag that names the mismatched value or claim. Claude Opus 5.5 (model id `claude-opus-5-5`, at temperature 0) judges whether each flag catches its bug, using the catch rubric and the answer key's description of the bug. It does not see which method raised a flag: all methods' flags are pooled and shuffled. A flag on the right tooltip that names the wrong value or claim is not a catch.

## Tests

**Recall** below means the share of bugs or planted errors a method catches.

**Primary test.** The strong model against the script, on real bugs of the typed-number kind only, using an exact McNemar test (a paired test on the bugs one method catches and the other misses), two-sided, p < 0.05. Only the typed-number kind is compared head to head, because the script can't see the other two. The test runs on however many typed-number real bugs are confirmed. If there are few, it runs on what there is, with its lower power (the chance of detecting a gap that is really there) stated, and is not moved to planted errors.

**How many bugs it needs.** The patch-notes search read 163 patch-notes pages from 10.1 to 26.19 and found 336 candidate lines before any were checked by hand. We don't yet know how many will be confirmed, or how many of those will be typed numbers. If 35% of typed-number test bugs are caught by the model and missed by the script, and 5% the reverse, the test has about 86% power with 40 bugs, 71% with 30 and about 27% with 15. With fewer than 6 bugs where the two methods disagree, the exact two-sided McNemar test cannot reach p < 0.05, so success criterion 1 cannot be met, and that is reported as the result.

**Secondary tests.** One family of 7 tests, with the Holm correction for testing several things at once, at an overall alpha of 0.05 (the accepted chance of at least one false positive across all 7 tests):

1. The small model against the script, on typed-number real bugs (exact McNemar, two-sided).
2. The strong model against the script, on planted typed-number errors (exact McNemar, two-sided).
3. The small model against the script, on planted typed-number errors (exact McNemar, two-sided).
4. The strong model's recall on planted wording errors.
5. The strong model's recall on planted translation errors.
6. The small model's recall on planted wording errors.
7. The small model's recall on planted translation errors.

Tests 4 to 7 each use a one-sided exact binomial test, which checks whether recall is above 50% by more than chance would explain.

Each method's recall on real wording bugs and on real translation bugs is reported with counts, labeled exploratory. For a real translation bug the model sees the English text and that language's text side by side, as with planted translation errors.

Anything else we report is labeled exploratory and is not corrected for multiple tests. There is no pooled test across kinds.

## False alarms

- The sweep runs in the final session on the final-run patch, on English text only: every checked record of every champion ability (1,540 records in patch 26.19, the latest as of 2026-10-05).
- Each model runs the sweep 3 times, like the test sets. Precision (the share of flags that are real mismatches), the flags-per-1,000 rate and the cost criterion (success criterion 4) all come from run 1, and only run 1's flags are labeled. The flag counts of runs 2 and 3 are reported as a range. The script runs once.
- If a method raises 200 flags or fewer, all of them are labeled. Otherwise a random 200 are, drawn with the committed seed.
- Each flag is labeled real mismatch, not a mismatch, or can't tell from the files, following the flag-labeling rubric.
- Claude Opus 5.5 (`claude-opus-5-5`) labels every flag blind: the method is hidden, and all methods' flags are pooled and shuffled together.
- The author checks 10 of those labels, picked at random with the same seed. This is reported as a spot check with its interval, not as validation: even 10 agreeing out of 10 gives a 95% Clopper-Pearson interval (an exact interval for a proportion) that starts at about 69% agreement.
- Precision is reported with its 95% Wilson interval, a standard interval for a proportion whose width depends on how many flags were labeled. Flags labeled can't tell count as not real. Their number is reported separately, and precision with them left out is reported as exploratory. We also report flags per 1,000 checked records.

## What counts as success, decided now

All four must hold for the strong model:

1. The primary test is significant in the model's favor.
2. At least 50% of its flags are real mismatches (point estimate, reported with its 95% Wilson interval).
3. Its recall on planted wording errors and on planted translation errors is above 50%, shown by secondary tests 4 and 5 being significant after the Holm correction.
4. Run 1 of the English false-alarm sweep by the strong model costs under $5 (US). This counts model calls only, not the judge, priced from logged token counts at the pinned provider's prices on the date of the final session.

If these aren't met, that is the result we publish.

## Sources

- [CommunityDragon](https://www.communitydragon.org/)
- [Riot Developer Portal: Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon)
- [Riot legal: "Legal Jibber Jabber" policy](https://www.riotgames.com/en/legal)

tooltip-audit was created under Riot Games' "Legal Jibber Jabber" policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.
