# Plan

Written 2026-10-04. The experiment design and success criteria were first set on 2026-10-05, before any model prompt was written or any model was run, in commit b831378.

We revised the design later on 2026-10-05, still before any model prompt was written or any model was run. The first version's primary test was on real bugs where a number typed by hand into the text had gone stale. Checking the patch notes against the game files found none of those among the 12 confirmed real bugs, and most of them were tooltip calculations. So the primary test moved to planted tooltip-calculation errors, tooltip calculations were added as a fourth kind of error, the baseline script gained a check for them, and the real bugs became a descriptive case study. We chose the new primary kind after seeing how the confirmed real bugs split by kind, and before any model run.

We revised it again on 2026-10-06, before any model run, and cut the scope to reach a first result sooner (see "Deferred"). The first planting code made calculation errors as renamed tooltip-only copies. A review found that 93 of the first 100 had a shape seen in only 9 of the 1,501 real records, and the baseline had already been run on that first development set (it caught all 100 errors its rules could reach), so the planting rules were changed to the in-place changes below. This version is the commit that adds this paragraph, and every commit that holds a result comes after it.

## The question

When a designer changes an ability, its tooltip is supposed to change with it. Sometimes it doesn't, players read wrong information, and the fix ships in a later patch. Can a language model, given each tooltip and the game data behind it, flag those mismatches more often than a simple script, at a false-alarm rate a person would put up with ([success criterion 2](#what-counts-as-success-decided-now))?

## Patch numbers

Riot's public patch names (26.x in 2026, 25.x in 2025) differ from the game's internal version numbers (16.x, 15.x) used by CommunityDragon, a fan-run archive of the game's files for each past patch. Up to 2024 the two match. This plan uses Riot's patch names, with the game version in parentheses where both appear.

## How tooltips work today

In League of Legends each champion (a playable character) has a passive and four abilities, on the Q, W, E and R keys, where R is the ultimate. All five are checked. The player raises each ability's rank during a match. Tooltips are mostly templates. The English text for Ahri's Q is stored as:

> Ahri throws then pulls back her orb, dealing @TotalDamage@ magic damage on the way out and @TotalDamage@ true damage on the way back.

`TotalDamage` is a named calculation in the ability's game data (base damage by rank plus 50% of ability power, a stat that makes many abilities stronger), so when a designer changes those values the tooltip updates on its own. That design already prevents the most obvious kind of stale number.

## What the templates can't catch

1. **Numbers typed into the English text by hand.** For example, Sion's ultimate charges "for 8 seconds" and Riven's E shield lasts "for 1.5 seconds". If the underlying value changes, the text doesn't.
2. **English words that disagree with the data.** The text says magic damage and the data deals physical, says "bonus AD" (only the attack damage added by items and other effects) where the formula uses total attack damage, describes a slow the ability no longer has, or leaves out an effect. A left-out effect counts as this kind when the files identify the left-out value: by its own name, by a label in the level-up list, or by another tooltip that shows it ([exact rule](answer_key/README.md#confirmations)).
3. **Translations.** Each language is its own copy of the text, so a number or a meaning can be wrong in another language while the English is right. Any bug that exists only outside English is this kind, even when it is a hand-typed number.
4. **Tooltip calculations.** A placeholder is filled from a calculation or value that only the tooltip uses, or points at the wrong calculation or value, and it disagrees with the value the ability actually uses, as shown elsewhere in the data or in the same text. In patch 10.20, Nami's W tooltip used a calculation with 150% of ability power while the spell itself used 50%; it was fixed in 10.21. In patch 12.8, Ekko's Q tooltip used a tooltip-only value of 40% of ability power where the spell uses 30%; it was fixed in 12.9.

So templates move the problem rather than end it. Most of the real tooltip bugs we confirmed from 2020 to 2026 are of the fourth kind, and none is a hand-typed number (see "Real bugs").

## Data

- Tooltip text and the per-patch game data, from [CommunityDragon](https://raw.communitydragon.org/). Each patch folder holds one build from around release day, but not always that patch's own (the folder named 10.11 holds a 10.10 build), so the build version is recorded for each bug.
- Riot's patch notes, for the list of tooltip bugs that were fixed and when.
- Riot's [Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon), the official list of champion names, used to find the patch-notes lines about each champion.
- Live patches only. No unreleased content in anything we publish.

The game files call each ability a "spell", and one ability can have more than one spell (a recast, for example). The experiment checks every tooltip text a champion ability links to: the main tooltip field, the extended text shown while Shift is held, including the part below its divider line, and the short simplified tooltip some abilities have. The one-line summary some abilities also have is not checked. The unit is a record: one text field of one spell. Two kinds of record are dropped ([scripts/README.md](scripts/README.md)): a second spell's link to a text that belongs to another spell, which would check the same text twice, and a short passive summary shown before a match rather than in a tooltip. Separate texts that happen to have the same words are each checked. In patch 26.19 there are 1,501 checked records, 945 of them in the main tooltip field.

The @...@ placeholders are filled in with values from the game data where the data allows: 93% of the placeholders in the main tooltip field in patch 26.19. An unfilled placeholder is shown to the model and the script as-is (the raw @Name@), and the script doesn't treat it as a typed number.

**Scope.** Champion abilities only. Items, runes and summoner spells (other parts of the game that have tooltips) are out. The scope may change only before the first model run (see "Keeping the test honest").

## The experiment

1. **Answer key.** Collect every tooltip correction in Riot's patch notes from patch 10.1 (January 2020) to patch 26.19 (the latest notes as of 2026-10-05). For each, confirm the bug is visible in the game files from before the fix. Each bug is checked in the CommunityDragon folder just before the first folder that holds the patch whose notes list the fix, so the files checked always predate the fix. The exact rule, including mid-patch updates and follow-up pages such as 13.1B, is in [answer_key/README.md](answer_key/README.md#which-game-files-to-compare).
   - **Unit:** one bug per champion and ability. A patch-notes line naming three champions is three bugs.
   - **Kind:** each confirmed bug is given one of the four kinds above. A candidate that isn't a mismatch between text and data is excluded, such as a tooltip not appearing on hover or a display not updating during play. So is a bug found only in the level-up list (the values a tooltip shows changing from rank to rank), because that list is not one of the checked text fields. Every exclusion is listed with its reason. The exact rules are in [answer_key/README.md](answer_key/README.md#confirmations).
2. **Planted errors.** Errors are planted in a live patch's English tooltips by fixed rules written in code, not by a language model, so the same kind of model doesn't both make and find them. The test set has 250 tooltip-calculation errors, split as equally as the counts allow among five rules:
   - change a stat ratio, such as the share of ability power, in a calculation the text shows;
   - change the per-rank base values that a shown calculation or a placeholder reads;
   - point a placeholder at another calculation or value of the same spell;
   - leave out one term of a shown calculation that has two or more;
   - change a multiplier inside a shown calculation, such as a duration or a hit count.

   Every change is made in place. Nothing is added, removed or renamed, so a planted input has the same shape as a real one. A value is changed only where nothing else in the data reads it (no level-up row, other calculation or other spell), and only where it agreed, before the change, with a value elsewhere in the input that the change leaves alone, such as the spell's coefficient or a level-up row. So each error shows as a disagreement inside the input, as real tooltip bugs do. Changes stay plausible: each size comes from a fixed list in the code, whole numbers stay whole, ranks keep their order, a count never drops below 1, and a placeholder is only pointed at the same kind of quantity, within a factor of 4 of the original. A rule with too few eligible records gives the rest of its share equally to the other rules, and each such move is recorded. At most one error goes on a spell, and at most one on each tooltip text within a champion. Each error is planted on its own in the unchanged patch data, so errors never interact, and only a flag on the record it was planted in can catch it.

   Development errors, which prompts are tuned on, are made with different random seeds in a patch older than the final-run patch. The final-run patch is the latest live patch on the date of the final session, so it is newer than every patch seen during tuning. The patches used are recorded with the run logs in the repo.
3. **Baseline.** A plain script with two checks. It compares each hand-typed number in the English text to the values in the game data. It also compares each value the text shows with the gameplay value it stands for, matched by fixed rules written in the script, such as a tooltip-only value against the gameplay value of the same name. It can't see wording or translation errors, or a tooltip calculation with no gameplay counterpart it can match, and it has no rule for a placeholder pointed at another value. The script was written knowing the answer key and the planting rules, the way a tools engineer would write one knowing which bugs they want caught, but until the freeze (see "Keeping the test honest") it is run only on the planted development set and the unmodified development patch. Knowing the rules favors the script on planted errors, so it makes the primary test harder for the model. It is also one of two reasons the results on real bugs are descriptive only; the other is that 12 bugs are too few for a test (see "Real bugs").
4. **Model checker.** Give a language model each checked record on its own, one record per call, and ask for every mismatch, with a reason. Each call shows both sides: the text, the value each placeholder shows and the formula behind it (its data values and coefficients, and whether the game marks it as tooltip-only), and the data around it: the spell's other values, its level-up list, the other spells of its ability and any spell it refers to. The script reads the same input. For the real translation bug, the model sees the English text and the translation side by side. For a real bug, the records of the bug's ability in the build checked are given to the model, and the script checks the same records. The bug counts as caught only through a flag on the bug's own record; flags on the ability's other records don't count toward recall. We use open-weight models (models whose weights are published) to keep the cost per run low, through [OpenRouter](https://openrouter.ai/), a service that serves many hosted models through one API:
   - small: Qwen3.8-27B (`qwen/qwen3.8-27b`)
   - strong: DeepSeek-V4-Pro-0813 (`deepseek/deepseek-v4-pro-0813`)

   Each model is pinned to a fixed version rather than a "latest" alias and runs at temperature 0 (the setting that makes it pick its most likely next token). Reasoning (thinking) is off in every run. That was fixed before any run, so it can't be tuned, and with it on the false-alarm sweep would likely cost more than success criterion 3 allows. Each is served by one pinned provider that runs the weights at 8-bit precision (fp8) or better rather than a more compressed copy, with fallback to other providers turned off, so a call fails rather than silently moving to a different provider. Every call is logged with its time and the provider that served it.

## Keeping the test honest

- Every confirmed real bug is in the test set. There is no development set of real bugs, and real bugs are never used for tuning.
- Prompts are tuned only on planted development errors. Planted development and test errors use different random seeds.
- Before the first model run of any kind, prompt tuning included, these are fixed and committed to this repo: the scope, the answer key (the confirmed bugs, the kind given to each, the exclusion list with reasons, and the build version per bug), the baseline script with both its checks, and the planting code (its rules and the size of each change).
- Before the final session, these are also fixed and committed: the planting seeds, the planted test set, the seed for the random draws (the flags to label and both spot checks), the final prompts, the catch rubric, the flag-labeling rubric, the judge's prompts, the provider and a backup provider chosen for each model, and the final-run patch number. The planted test set is committed as a manifest rather than as game text, so the repo doesn't re-host game files. For each error it gives the record, the rule, the change and a hash of the planted input, which is the exact text and data both methods receive for that error. The planting code makes the set again from CommunityDragon and its `--verify` mode checks every hash.
- The planted test set, the real bugs and the false-alarm sweep are run in one final session. Each model runs 3 times, because hosted models aren't fully deterministic even at temperature 0. For each bug and planted error, the majority vote of the 3 runs feeds every test below, and the range across runs is reported. The script is deterministic and runs once.
- A failed model call is retried up to 3 times with the same settings. A call that still fails, or whose output can't be parsed into flags, counts as no flags, and the number of such calls is reported for each run. If more than 5% of a run's calls still fail after retries, the whole final session is stopped and rerun on the backup providers, and the switch is reported. The trigger is the failure count alone. The first session's outputs are kept in the repo and not scored.
- Before judging and labeling, every flag is reduced to a common format (the tooltip, the text field, and the value or claim it names), and the model's reason is removed, so the judge can't tell methods apart by format.
- **What counts as a catch:** a flag that names the mismatched value or claim. Claude Opus 5.5 (model id `claude-opus-5-5`, at temperature 0) judges whether each flag catches its bug, using the catch rubric and the answer key's description of the bug. It does not see which method raised a flag: all methods' flags are pooled and shuffled. A flag on the right tooltip that names the wrong value or claim is not a catch. The author also checks 10 catch judgments, drawn at random with the committed seed, reported as a spot check with its interval, like the label check in "False alarms".

## Tests

**Recall** below means the share of bugs or planted errors a method catches.

**Primary test.** The strong model against the script, on the 250 planted tooltip-calculation errors in the test set, using an exact McNemar test (a paired test on the errors one method catches and the other misses), two-sided, p < 0.05, on the majority vote of 3 runs. This kind is the head-to-head test because most real bugs are of this kind and the script can check it too.

Power (the chance of detecting a gap that is really there), computed exactly for this test: if 15% of planted errors are caught by the model and missed by the script, and 5% the reverse, the test has about 94% power. If those shares are 20% and 10%, it has about 80% power. With fewer than 6 errors where the two methods disagree, the exact two-sided McNemar test cannot reach p < 0.05, so success criterion 1 is not met, and that is reported as the result.

**Secondary test.** The small model against the script, on the same 250 errors, with the same exact McNemar test, two-sided, at alpha 0.05 (the accepted chance of a false positive). It is the only secondary test, so no correction for several tests is needed.

**Real bugs.** The confirmed real bugs are a case study, labeled descriptive, with no significance test. For each method we report recall on them overall and by kind, with counts and 95% Clopper-Pearson intervals (an exact interval for a proportion, used for every interval in this plan). As of 2026-10-05 there are 12 confirmed real bugs: 8 tooltip calculations, 3 wording, 1 translation and 0 typed numbers ([answer_key/README.md](answer_key/README.md#confirmations)). With 12 bugs, even 12 caught out of 12 gives an interval that starts at about 74%.

Anything else we report is labeled exploratory and is not corrected for multiple tests.

## False alarms

- The sweep runs in the final session on the final-run patch, on English text only: every checked record of every champion ability (see "Data").
- Each model runs the sweep 3 times, like the test set. Precision (the share of flags that are real mismatches), the flags-per-1,000 rate and the cost criterion (success criterion 3) all come from run 1, and only run 1's flags are labeled. The flag counts of runs 2 and 3 are reported as a range. The script runs once.
- If a method raises 200 flags or fewer, all of them are labeled. Otherwise a random 200 are, drawn with the committed seed.
- Each flag is labeled real mismatch, not a mismatch, or can't tell from the files, following the flag-labeling rubric.
- Claude Opus 5.5 (`claude-opus-5-5`) labels every flag blind: the method is hidden, and all methods' flags are pooled and shuffled together.
- The author checks 10 labels, drawn at random with the committed seed from the pooled flags of all methods. This is reported as a spot check with its interval, not as validation: even 10 agreeing out of 10 gives a 95% Clopper-Pearson interval that starts at about 69% agreement.
- Precision is reported with its 95% Clopper-Pearson interval. Flags labeled can't tell count as not real. Their number is reported separately, and precision with them left out is reported as exploratory. We also report flags per 1,000 checked records.

## What counts as success, decided now

All three must hold for the strong model:

1. The primary test, on planted tooltip-calculation errors, is significant in the model's favor.
2. At least 50% of its flags are real mismatches (point estimate, reported with its 95% Clopper-Pearson interval).
3. Run 1 of the English false-alarm sweep by the strong model costs under $5 (US). This counts model calls only, not the judge, priced from logged token counts at the pinned provider's prices on the date of the final session.

If these aren't met, that is the result we publish.

## Deferred

Cut on 2026-10-06, before any model run, to reach a first result sooner, and left to a later study: planted typed-number, wording and translation errors, and the success criterion on the strong model's recall for planted wording and translation errors.

## Sources

- [CommunityDragon](https://www.communitydragon.org/)
- [Riot Developer Portal: Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon)
- [Riot legal: "Legal Jibber Jabber" policy](https://www.riotgames.com/en/legal)

tooltip-audit was created under Riot Games' "Legal Jibber Jabber" policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.
