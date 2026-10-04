# Plan

Written 2026-10-04, before any code. It records the question, what we found about how tooltips work today, and the experiment, so the result can be judged against what was decided in advance.

## The question

When a designer changes an ability, its tooltip is supposed to change with it. Sometimes it doesn't, players read wrong information, and the fix ships in a later patch. Can a language model, given each tooltip and the game data behind it, flag those mismatches more often than a simple script, at a false-alarm rate a person would put up with?

## How tooltips work today

League tooltips are mostly templates. The English text for Ahri's Q is stored as:

> Ahri throws then pulls back her orb, dealing @TotalDamage@ magic damage on the way out and @TotalDamage@ true damage on the way back.

`TotalDamage` is a named calculation in the ability's game data (base damage by rank plus 50% of ability power), so when a designer changes those values the tooltip updates on its own. That design already prevents the most obvious kind of stale number.

Riot also runs a large automated test system (about 100,000 test cases a day, per its tech blog) and has QA and localization teams. We found nothing public about whether any of those checks read tooltip text, so we don't assume either way.

## What the templates can't catch

1. **Numbers typed into the text by hand.** In the current patch, a rough pattern match found about 156 of 1,366 ability tooltips with a number written directly into the sentence, for example Sion's ultimate charging "for 8 seconds" and Riven's E shield lasting "for 1.5 seconds". If the underlying value changes, the text doesn't. The count is rough and gets checked properly in step 1.
2. **Words that disagree with the data.** The text says magic damage and the data deals physical, says "bonus AD" where the formula uses total AD, describes a slow the ability no longer has, or leaves out a new effect.
3. **Translations.** Each language is its own copy of the text, so a hand-typed number or a meaning can drift in one language and not the others.

The simple script can only see the first kind. The second and third are where a language model might add something.

## Data

- Tooltip text in every language and the per-patch game data, from [CommunityDragon](https://raw.communitydragon.org/), which keeps an archive of past patches.
- Riot's patch notes, for the list of tooltip bugs that were fixed and when.
- Live patches only. No unreleased content in anything we publish.

## The experiment

1. **Answer key.** Collect every tooltip correction from the last 30 to 40 patch notes. For each, pull the files from the patch before the fix, when the bug was live, and confirm the bug is visible in them.
2. **Baseline.** A plain script that compares each hand-typed number to the matching value in the game data.
3. **Model checker.** Give a language model each tooltip with its resolved values and ask for every mismatch, with a reason.
4. **Measure.**
   - Recall on the answer key: how many of Riot's later fixes each method flags while the bug was live.
   - Recall on 50 planted errors in a clean patch, spread across the three kinds above.
   - False alarms, from a hand-checked sample of flags on a clean patch.
   - Cost per full run.
5. **Write up** the result, including where it failed.

**What counts as failure, decided now:** if the model doesn't catch clearly more than the script, at a cost that stays small per patch, that is the result we publish.

Target: a first result within one to two weeks of starting.

## If it works: how a studio would use it

- **On every check-in (main use).** When an ability's data or text changes, check just that ability, script first and model second, and send any flag to the person who made the change while it's still fresh.
- **At patch lock.** One full sweep of about 1,400 tooltips as a safety net.
- **When translations arrive.** Check each language against English on its own schedule.
- **People decide.** Flags are suggestions in an existing queue, never automatic edits. Every dismissed flag is logged, which gives a running false-alarm rate.

## Open questions

- Does Riot's official data download carry enough of the tooltip text and values to skip CommunityDragon entirely? Check on day one.
- How do older patches store their text? The file layout changed somewhere before patch 15.1.
- Which model, and at what cost per run? Decide after the baseline exists.

## Sources

- [Riot Tech Blog: Automated Testing for League of Legends](https://technology.riotgames.com/node/33)
- [Riot developer post on tooltip formulas and placeholders](https://www.surrenderat20.net/2018/07/red-post-collection-god-king-darius.html?m=1)
- [CommunityDragon](https://www.communitydragon.org/)
- [Riot legal: "Legal Jibber Jabber" policy](https://www.riotgames.com/en/legal)
