#!/usr/bin/env python3
"""Work out the numbers each champion ability tooltip shows, from the game data.

Reads what fetch_cdragon.py saved under data/raw/<patch>/ and writes, per patch and language:
  data/resolved/<patch>.<locale>.jsonl          one record per (spell, tooltip text field) pair
  data/resolved/<patch>.<locale>.summary.json   coverage counts and the reasons values were not resolved

How a tooltip is found. Each champion SpellObject names its text through
mSpell.mClientData.mTooltipData.mLocKeys. The script reads every text field there whose name
starts with keyTooltip: keyTooltip (the tooltip), keyTooltipExtended and
keyTooltipExtendedBelowLine (the longer text shown while Shift is held) and keyTooltipSimple.
Each record says which field its text came from. Text is never matched by searching the
string table, because it also holds old and unused entries (Ahri's 'spell_ahriq_tooltip'
is the pre-rework text). Older champion records have no mCharacterPassiveSpell. The field was
added champion by champion from about 10.10; the last (Tahm Kench) got it after 10.23, and none
lacks it in 10.25. Without it the passive is found by name and text key (see
Champion.unlinked_passive). Most of those passive spells name a keyTooltip like any other spell
(80 of the 148 champions in 10.1). Where none does, the record's passiveToolTip is read instead,
and the record says it is the short champion summary text (the passive description shown in
champion select), not an in-game tooltip. In 10.1 that is 68 champions: 62 whose passive spell
names no keyTooltip (Nasus among them) and 6 with no passive spell found at all (Bard, Jayce,
Kennen, Twisted Fate, Vayne and Viktor). Keys and champion folders for the 2026 'Jade' mode variants are skipped and counted.
A {{Name}} include inside a text is listed on the record but not expanded.

Some exports store an entry under the FNV-1a hash of its path instead of the path (Senna's
record and spells in 10.1). The champion record is then found by the hash of
Characters/<Folder>/CharacterRecords/Root, and the spells it names by the hashes of their
paths. A spell stored under a hash sometimes names the same text as the spell the text
belongs to (Aurora's R missile, '{36b6a65c}' in 15.16, reuses the R tooltip); its records
carry duplicate_of with that spell's path, so they can be dropped, and the summary counts them
(see duplicate_targets for the rule). The summary's checked_records counts the records left
once duplicate_of and passiveToolTip records are dropped, overall and per text field.

Each record and summary carries the build (cdragon_version) from the fetch manifest, and the
summary copies the manifest's list of failed downloads.

Where the text lives. The text file has five forms over the years, listed with their patches
in scripts/README.md, and this script reads all five. The oldest, fontconfig_<locale>.txt, is
a binary string table despite its name. The file is found from the path the manifest
fetch_cdragon.py writes (stringtable_path[locale]), or else by looking for the known paths,
starting with the manifest's stringtable_layout[locale].
A key the table stores only as a hash is looked up by the same hash the table uses
(XXH64 of the lower-case key, keeping the low 40 bits in table versions 2 and 3 and the low
39 bits from version 4).

Old champion files. Up to 11.7 the exported files leave some field names as hashes (32-bit
FNV-1a of the lower-case name, for example mSpellCalculations is {94572284}); the script
renames every one it reads, in every patch. Exports before 11.1 (patch 10 and
earlier) give no class names at all, so a part such as {"mDataValue": "X"} could be a plain
data value or a data value times AP. For those patches the script reads the binary .bin file
next to the export, which does carry the class of every object, and takes entry names from
the export. Field names changed again between 15.16 and 15.17 (mDataValues, mName and mValues
became DataValues, name and values); both spellings are read.

How a placeholder is read. A token is @[spell.Script:]Name[.precision][*factor]@. Name is
looked up, in this order, as a spell stat (Cooldown, Cost, AmmoRechargeTime, MaxAmmo,
CastRange), a calculation in mSpellCalculations, a data value, EffectNAmount, or NameN for
the value at rank N. @f1@ and its kin are set by the spell's script while the game runs, so
no file holds them; they are reported as unresolved. A name may contain spaces (Kennen E's
@Movement Speed*100@ in 15.1 reads the data value named 'movement speed'). Names match without regard to case, and a name the export left as a
hash ({xxxxxxxx}, FNV-1a of the lower-case name) is matched too. The lookup order and the token
grammar follow LeagueToolkit's ltk-manager (crates/atlas/src/spell_tooltip.rs). Older
tooltips (before 12.x) also use @CharAbilityPower@, @CharBonusPhysical@ and
@CharTotalPhysical@, with a 2 on the end for the second ratio; these read the spell's
mCoefficient or mCoefficient2 times AP, bonus AD or total AD, which Data Dragon's own ratio
list confirms for 332 of the 333 such tokens in 10.1.

Values. Arrays in the champion files hold 7 entries and index 0 is rank 0, so rank r reads
index r (the last entry when the array is shorter). Mana cost arrays are the exception and
start at rank 1. A value that scales with a stat, a buff or the champion's level is kept
symbolic ('+50% AP', '20 to 180 by level'); no stat value is ever invented. Where the data
names something it does not hold (an effect index above 10, a product with a missing side,
a level formula with no values), the placeholder is reported as unresolved rather than read
as 0.

Ranks. The number of ranks comes from the spell's LevelUp list, or its ability's root spell.
A spell with neither gets one rank. If its data still changes between ranks 1 and 5 (Samira's
E buff, for example), its rank_source says so, because the single value shown may not be the
one the tooltip uses.

Stat codes. mStat numbers changed several times: before 11.11 the codes from 4 up sat one
lower; up to 10.20 health and current health sat one lower again; codes from 11 or 12 up
moved from patch to patch until 11.11; and between 15.1 and 15.16 three stats were inserted. That gives four layouts, D (oldest), C, A and B. The script tells them
apart from eight anchor calculations and labels stats only when one layout fits every anchor
that names a stat. Otherwise the layout is 'unknown' and stats are labeled 'stat #N'. In
layouts C and D only the codes whose meaning held steady are named. The summary counts stat
scalings and how many of them are unnamed. mStatFormula is 0 total, 1 base, 2 bonus. Stats the
game stores as a fraction (crit chance 0.25 means 25%) are labeled per 100% of the stat.

A patch that cannot be resolved (no manifest, no text file, a truncated file or any other
error) is reported as failed with the error's type, and the run goes on to the next patch; the
script then exits with an error naming the failed patches.

Examples (run from the project root):
  python3 scripts/resolve_tooltips.py --patches 16.19 15.1
  python3 scripts/resolve_tooltips.py            # every patch under data/raw
"""

import argparse
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW = PROJECT_ROOT / "data" / "raw"
DEFAULT_OUT = PROJECT_ROOT / "data" / "resolved"

MAX_LEVEL = 18
DEPTH = 10
DEFAULT_DECIMALS = 2
MAX_EFFECT_INDEX = 10

# Text fields read from mLocKeys, in output order. Any other key starting with keyTooltip is
# read too and listed after these.
TEXT_FIELDS = ("keyTooltip", "keyTooltipExtended", "keyTooltipExtendedBelowLine", "keyTooltipSimple")
JADE_KEY_RE = re.compile(r"(^|_)jade(_|$)", re.I)

# ---------------------------------------------------------------------------------------
# Stat codes

# The 15.1 layout. Names from moonshadow565/calcrev (reverse-engineered from the client);
# checked against 15.1 data: Akshan passive scales with 3 (attack speed), Braum W with 5 (MR),
# Alistar passive with 11 (health), Zac's health cost with 12 (current health), Pyke with 26
# (lethality), Urgot passive range with 28 (attack range).
STATS_A = {
    0: "AP", 1: "armor", 2: "AD", 3: "attack speed", 4: "attack windup", 5: "MR",
    6: "move speed", 7: "crit chance", 8: "crit damage", 9: "cooldown reduction",
    10: "ability haste", 11: "health", 12: "current health", 13: "missing health",
    14: None, 15: "life steal", 17: "omnivamp", 18: "physical vamp",
    19: "flat magic pen", 20: "% magic pen", 21: "% bonus magic pen", 22: "magic lethality",
    23: "flat armor pen", 24: "% armor pen", 25: "% bonus armor pen", 26: "lethality",
    27: "tenacity", 28: "attack range", 29: "health regen", 30: "resource regen",
}
# The 16.19 layout. Pairing every identical stat part in 15.1 and 16.19 (1,200 parts) gives
# 0-2 unchanged, 3-11 moved up by 1, 12 to 14, 13 and later moved up by 3. Codes 3, 13 and 15
# are new and unnamed. LeagueToolkit's own table agrees (4 attack speed, 6 MR, 7 move speed,
# 12 health, 31 attack range).
STATS_B = {0: "AP", 1: "armor", 2: "AD", 3: None, 13: None, 15: None}
for _code, _name in STATS_A.items():
    if 3 <= _code <= 11:
        STATS_B[_code + 1] = _name
    elif _code == 12:
        STATS_B[14] = _name
    elif _code >= 13:
        STATS_B[_code + 3] = _name

# Stats the game stores as a fraction of 1, shared by both layouts. Checked in 16.19: Jhin's
# passive gives 0.3 x bonus attack speed as % AD and Senna's passive shows 1 x crit damage as
# a percent (175% from 1.75); Corki Q's recharge cut is 4 x crit chance seconds; Ambessa R's
# omnivamp is 0.5 x life steal. Total and base attack speed are attacks per second, so only
# bonus attack speed (formula 2) is a fraction.
FRACTION_STATS = {
    "crit chance", "crit damage", "cooldown reduction", "life steal", "omnivamp",
    "physical vamp", "% magic pen", "% bonus magic pen", "% armor pen", "% bonus armor pen",
    "tenacity",
}

# The layout from 10.21 to 11.10 (checked in 10.21, 10.22, 10.23, 10.25, 11.1 and 11.10).
# Pairing identical stat parts in 11.10 and 11.11 (and in 11.1 and 11.10) gives 0-3 unchanged and
# 4-8, 10, 11 one lower than layout A; Braum W's MR is 4 in every patch from 10.1 to 11.10. Codes
# from 12 up moved from patch to patch (Pyke R's lethality is 19 in 10.1, 20 in 10.10, 22 in
# 10.20, 23 in 10.21 and 10.25, 25 in 11.10), so they and the unpaired code 9 are left unnamed.
STATS_C = {code: STATS_A[code if code <= 3 else code + 1] for code in (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11)}
# The layout of 10.20 and earlier (checked in 10.1, 10.5, 10.10, 10.15 and 10.20). Pairing
# identical stat parts in 10.20 and 10.21 gives 1-8 unchanged and health (9) one lower than in
# layout C: Cho'Gath R's bonus health and Garen W's shield read 9 in each of those patches and 10
# from 10.21 to 11.10. Zac's health cost reads {9, 10} in 10.20, so 10 is current health. Code 5
# is used by no spell in these patches; it is named as in layout C, which agrees on every code
# around it. Codes from 11 up are left unnamed, as in layout C.
STATS_D = {code: STATS_C[code] for code in range(9)}
STATS_D.update({9: "health", 10: "current health"})
STAT_TABLES = {"A": STATS_A, "B": STATS_B, "C": STATS_C, "D": STATS_D}

# (champion folder, spell script name, calculation, {layout: stat codes in that layout}).
# Spells are found by script name because older files put them in a different folder
# (Characters/Braum/Spells/BraumW before Characters/Braum/Spells/BraumWAbility/BraumW).
STAT_ANCHORS = [
    ("akshan", "AkshanPassive", "ASModdedMS", {"A": [{3}], "B": [{4}]}),
    ("braum", "BraumW", "GrantedAllyMR", {"A": [{5}], "B": [{6}], "C": [{4}], "D": [{4}]}),
    ("alistar", "AlistarPassive", "BaseHeal", {"A": [{11}], "B": [{12}]}),
    ("zac", "ZacQ", "HealthCostTooltip", {"A": [{11, 12}], "B": [{12, 14}], "C": [{10, 11}], "D": [{9, 10}]}),
    ("pyke", "PykeR", "RDamage", {"A": [{2, 26}], "B": [{2, 29}], "C": [{2, n} for n in range(19, 26)],
                                  "D": [{2, n} for n in range(19, 26)]}),
    ("urgot", "UrgotPassive", "CastRange", {"A": [{28}], "B": [{31}]}),
    # Both are present, under these calculation names or their hashes, in every patch from 10.1.
    ("chogath", "Feast", "RDamage", {"A": [{11}], "B": [{12}], "C": [{10}], "D": [{9}]}),
    ("garen", "GarenW", "TotalShield", {"A": [{11}], "B": [{12}], "C": [{10}], "D": [{9}]}),
]
STAT_FORMULA = {0: "", 1: "base ", 2: "bonus "}
PQWER_SLOTS = ("P", "Q", "W", "E", "R")

UI_TOKENS = {
    "keyhotkey", "hotkey", "abilityresourcename", "extendedkeybind", "spelltags",
    "spellmodifierdescriptionappend", "levelupcount",
}
SPELL_STATS = {"cooldown", "cost", "basecost", "ammorechargetime", "maxammo", "castrange",
               "castrangedisplayoverride"}

# A token is anything between two @ signs that holds no markup. Names may contain spaces:
# data values such as 'movement speed' (Kennen E, 15.1) are declared that way.
TOKEN_RE = re.compile(r"@([^@<>]*)@")
TOKEN_CHARS = re.compile(r"^[A-Za-z0-9_.*\-: ]+$")
SCRIPT_VAR_RE = re.compile(r"^f\d+$", re.I)
EFFECT_RE = re.compile(r"^effect(\d+)amount$", re.I)
# Tokens such as @CharAbilityPower@ in tooltips from before about 12.x show the spell's
# mCoefficient (mCoefficient2 for a name ending in 2) times a stat. Checked against Data
# Dragon 10.1.1, whose spell 'vars' give the same coefficient and stat for 332 of the 333
# such tokens in 10.1 (the other is Corki Q, where the text says bonus AD and Data Dragon AP).
LEGACY_STAT_RE = re.compile(r"^Char(AbilityPower|TotalPhysical|BonusPhysical)(2?)$", re.I)
LEGACY_STAT_KEYS = {"abilitypower": (0, 0), "totalphysical": (2, 0), "bonusphysical": (2, 2)}
INCLUDE_RE = re.compile(r"\{\{\s*([^}]*?)\s*\}\}")


def fnv1a(text):
    """The 32-bit FNV-1a hash the game uses for bin names, as '{xxxxxxxx}'."""
    h = 0x811C9DC5
    for byte in text.lower().encode("utf-8"):
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return "{%08x}" % h


def clean(x):
    """Round away float32 noise (0.4000000059604645 -> 0.4)."""
    if isinstance(x, float):
        r = round(x, 6)
        return int(r) if r == int(r) and abs(r) < 1e15 else r
    return x


def fmt(x, decimals=DEFAULT_DECIMALS):
    s = "%.*f" % (max(0, min(decimals, 6)), x)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


class Unresolved(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------------------
# String tables

_M64 = (1 << 64) - 1
_P1, _P2, _P3 = 11400714785074694791, 14029467366897019727, 1609587929392839161
_P4, _P5 = 9650029242287828579, 2870177450012600261


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & _M64


def _round(acc, lane):
    return (_rotl((acc + lane * _P2) & _M64, 31) * _P1) & _M64


def xxh64(data, seed=0):
    """XXH64, the hash string tables use for their keys (standard library has none)."""
    n, i = len(data), 0
    if n >= 32:
        v = [(seed + _P1 + _P2) & _M64, (seed + _P2) & _M64, seed & _M64, (seed - _P1) & _M64]
        while i + 32 <= n:
            lanes = struct.unpack_from("<4Q", data, i)
            v = [_round(a, b) for a, b in zip(v, lanes)]
            i += 32
        h = (_rotl(v[0], 1) + _rotl(v[1], 7) + _rotl(v[2], 12) + _rotl(v[3], 18)) & _M64
        for a in v:
            h = ((h ^ _round(0, a)) * _P1 + _P4) & _M64
    else:
        h = (seed + _P5) & _M64
    h = (h + n) & _M64
    while i + 8 <= n:
        h ^= _round(0, struct.unpack_from("<Q", data, i)[0])
        h = (_rotl(h, 27) * _P1 + _P4) & _M64
        i += 8
    if i + 4 <= n:
        h ^= (struct.unpack_from("<I", data, i)[0] * _P1) & _M64
        h = (_rotl(h, 23) * _P2 + _P3) & _M64
        i += 4
    while i < n:
        h ^= (data[i] * _P5) & _M64
        h = (_rotl(h, 11) * _P1) & _M64
        i += 1
    h ^= h >> 33
    h = (h * _P2) & _M64
    h ^= h >> 29
    h = (h * _P3) & _M64
    return h ^ (h >> 32)


def rst_hash_bits(version):
    # Checked against CommunityDragon's decoded .txt.json, key by key: 40 bits in 11.1
    # (version 2), 39 bits in 11.10 (version 4) and 12.22 (version 5).
    return 40 if version < 4 else 39


def parse_rst(blob):
    """A binary string table (fontconfig_<locale>.txt and *.stringtable) -> (version, {hash: text})."""
    if blob[:3] != b"RST":
        raise ValueError("not a binary string table (no RST header)")
    version, o = blob[3], 4
    if version == 2:  # a font config block may follow the header
        has_config = blob[o]
        o += 1
        if has_config:
            n = struct.unpack_from("<I", blob, o)[0]
            o += 4 + n
    elif version not in (3, 4, 5):
        raise ValueError(f"string table version {version} not supported")
    count = struct.unpack_from("<I", blob, o)[0]
    o += 4
    packed = struct.unpack_from("<%dQ" % count, blob, o)
    o += 8 * count
    if version < 5:
        o += 1  # one flag byte before the text data
    data = blob[o:]
    bits = rst_hash_bits(version)
    mask = (1 << bits) - 1
    entries = {}
    for v in packed:
        off = v >> bits
        end = data.find(b"\0", off)
        raw = data[off:end if end >= 0 else len(data)]
        if raw[:1] == b"\xff":
            continue  # an encrypted entry (3 in 11.1, holding no tooltip text)
        entries[v & mask] = raw.decode("utf-8", "replace")
    return version, entries


class TextTable:
    """Look up text by key in either a decoded JSON table or a binary one."""

    def __init__(self, path, layout):
        self.path = path
        self.layout = layout
        if path.name.endswith(".json"):
            d = json.loads(path.read_text(encoding="utf-8"))
            self.version = int(d.get("version", 5))
            self.entries = {k.lower(): v for k, v in d["entries"].items()}
            self.readable = True
        else:
            self.version, by_hash = parse_rst(path.read_bytes())
            self.entries = by_hash
            self.readable = False
        self.mask = (1 << rst_hash_bits(self.version)) - 1
        self.found_by_hash = 0  # readable tables only: keys present only as a hash

    def key_hash(self, key):
        return xxh64(key.lower().encode("utf-8")) & self.mask

    def get(self, key):
        if self.readable:
            text = self.entries.get(key.lower())
            if text is None:
                text = self.entries.get("{%010x}" % self.key_hash(key))
                self.found_by_hash += text is not None
            return text
        return self.entries.get(self.key_hash(key))

    def readable_keys(self):
        return list(self.entries) if self.readable else None


# Paths relative to data/raw/<patch>/, the same as on raw.communitydragon.org/<patch>/. The inner
# en_us folder of the lol and main forms is the same for every locale; the outer one sets it.
STRINGTABLE_PATHS = {
    "lol": ["game/{loc}/data/menu/en_us/lol.stringtable.json", "game/{loc}/data/menu/en_us/lol.stringtable",
            "game/{loc}/data/menu/{loc}/lol.stringtable.json", "game/{loc}/data/menu/{loc}/lol.stringtable"],
    "main": ["game/{loc}/data/menu/en_us/main.stringtable.json", "game/{loc}/data/menu/en_us/main.stringtable",
             "game/{loc}/data/menu/{loc}/main.stringtable.json", "game/{loc}/data/menu/{loc}/main.stringtable"],
    "main_locale": ["game/data/menu/main_{loc}.stringtable.json", "game/data/menu/main_{loc}.stringtable"],
    "fontconfig": ["game/data/menu/fontconfig_{loc}.txt.json", "game/data/menu/fontconfig_{loc}.txt"],
}


def find_text_table(raw, manifest, locale):
    """(path, layout) of the locale's text file: the manifest's stringtable_path if that file
    exists, else the first known path found, trying the manifest's layout first."""
    layout = (manifest.get("stringtable_layout") or {}).get(locale)
    rel = (manifest.get("stringtable_path") or {}).get(locale)
    if rel and (raw / rel).is_file():
        name = layout if layout in STRINGTABLE_PATHS else next(
            (k for k, rels in STRINGTABLE_PATHS.items() if rel in [x.format(loc=locale) for x in rels]), layout)
        return raw / rel, name
    order = [layout] if layout in STRINGTABLE_PATHS else []
    order += [k for k in STRINGTABLE_PATHS if k not in order]
    for name in order:
        for rel in STRINGTABLE_PATHS[name]:
            p = raw / rel.format(loc=locale)
            if p.exists():
                return p, name
    return None, layout


# ---------------------------------------------------------------------------------------
# Champion files: field-name hashes and the binary form

# Every field and class name the script reads. Exports for 11.1 to 11.7 leave some field names
# as FNV-1a hashes, and the binary .bin form names nothing; these are renamed on load.
KNOWN_FIELDS = """
passiveToolTip passiveLuaName mCoefficient2
mSpell mScriptName ObjectName mBuff mCharacterName spells spellNames mCharacterPassiveSpell
mAbilities mRootSpell mChildSpells DataValues mDataValues name mName values mValues
mSpellCalculations mClientData mTooltipData mLocKeys mLists LevelUp levelCount elements
mEffectAmount value cooldownTime Cooldown mana manaValues mAmmoRechargeTime mMaxAmmo castRange
castRangeDisplayOverride keyName keySummary keyTooltip keyTooltipExtended
keyTooltipExtendedBelowLine keyTooltipSimple mFormulaParts mMultiplier mPrecision
mDisplayAsPercent DamageType ResultModifier mModifiedGameCalculation mOverrideSpellLevel
mDefaultGameCalculation mConditionalGameCalculation mConditionalCalculationRequirements
tooltipOnly mSimpleTooltipCalculationDisplay mExpandedTooltipCalculationDisplay mDataValue
mNumber mEffectIndex mSubparts mPart1 mPart2 mFloor mCeiling mCoefficient mStat mStatFormula
mSubpart mAbilityResource mBuffName buffName Coefficient mStartValue mEndValue
mScaleByStatProgressionMultiplier mScalePastDefaultMaxLevel mBreakpoints mLevel
mAdditionalBonusAtThisLevel mBonusPerLevelAtAndAfter mLevel1Value mInitialBonusPerLevel
mSpellCalculationKey SourceObject DataValue StartDataValue EndDataValue level mFormula mBaseP
mObjectName mFormat
""".split()
KNOWN_CLASSES = """
SpellObject CharacterRecord AbilityObject SpellDataResource SpellDataValue SpellEffectAmount
TooltipInstanceSpell TooltipInstanceList TooltipInstanceListElement SpellDataResourceClient
GameCalculation GameCalculationModified GameCalculationConditional
NamedDataValueCalculationPart NumberCalculationPart EffectValueCalculationPart
SumOfSubPartsCalculationPart ProductOfSubPartsCalculationPart ClampSubPartsCalculationPart
StatByCoefficientCalculationPart StatByNamedDataValueCalculationPart StatBySubPartCalculationPart
AbilityResourceByCoefficientCalculationPart BuffCounterByCoefficientCalculationPart
BuffCounterByNamedDataValueCalculationPart PercentageOfBuffNameElapsed
ByCharLevelInterpolationCalculationPart ByCharLevelBreakpointsCalculationPart
ByCharLevelFormulaCalculationPart CooldownMultiplierCalculationPart Breakpoint
HasBuffCastRequirement
""".split()
FIELD_BY_HASH = {fnv1a(n): n for n in KNOWN_FIELDS}
CLASS_BY_HASH = {fnv1a(n): n for n in KNOWN_CLASSES}


def unhash_names(obj):
    """Rename hashed field and class names the script knows, everywhere in obj."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "__type" and isinstance(v, str):
                out[k] = CLASS_BY_HASH.get(v, v)
            else:
                out[FIELD_BY_HASH.get(k, k)] = unhash_names(v)
        return out
    if isinstance(obj, list):
        return [unhash_names(v) for v in obj]
    return obj


# Value types in the binary form. Files before about 10.10 number the container types without
# the unordered list (0x81), so both numberings are tried and the one that reads the whole
# file with every length matching wins.
_COMPLEX_NEW = {0x80: "list", 0x81: "list", 0x82: "pointer", 0x83: "embed", 0x84: "link",
                0x85: "option", 0x86: "map", 0x87: "flag"}
_COMPLEX_OLD = {0x80: "list", 0x81: "pointer", 0x82: "embed", 0x83: "link", 0x84: "option",
                0x85: "map", 0x86: "flag"}
_SCALAR = {1: "<?", 2: "<b", 3: "<B", 4: "<h", 5: "<H", 6: "<i", 7: "<I", 8: "<q", 9: "<Q",
           10: "<f", 11: "<2f", 12: "<3f", 13: "<4f", 14: "<16f", 15: "<4B"}


class _BinReader:
    def __init__(self, blob, old_numbering):
        self.b = blob
        self.o = 0
        self.complex = _COMPLEX_OLD if old_numbering else _COMPLEX_NEW
        self.has_path_type = not old_numbering

    def read(self, f):
        v = struct.unpack_from(f, self.b, self.o)
        self.o += struct.calcsize(f)
        return v[0] if len(v) == 1 else list(v)

    def value(self, t):
        if t in _SCALAR:
            v = self.read(_SCALAR[t])
            return float(v) if t == 10 else v
        if t == 0:
            return None
        if t == 16:
            n = self.read("<H")
            s = self.b[self.o:self.o + n].decode("utf-8", "replace")
            self.o += n
            return s
        if t == 17:
            return "{%08x}" % self.read("<I")
        if t == 18 and self.has_path_type:
            return "{%016x}" % self.read("<Q")
        kind = self.complex.get(t)
        if kind == "link":
            return ("link", "{%08x}" % self.read("<I"))
        if kind == "flag":
            return bool(self.read("<B"))
        if kind == "list":
            et = self.read("<B")
            size = self.read("<I")
            end = self.o + size
            out = [self.value(et) for _ in range(self.read("<I"))]
            self.check(end)
            return out
        if kind in ("pointer", "embed"):
            h = self.read("<I")
            if h == 0:
                return None
            size = self.read("<I")
            end = self.o + size
            out = self.fields()
            self.check(end)
            out["__type"] = "{%08x}" % h
            return out
        if kind == "option":
            et = self.read("<B")
            return self.value(et) if self.read("<B") else None
        if kind == "map":
            kt, vt = self.read("<B"), self.read("<B")
            size = self.read("<I")
            end = self.o + size
            out = {}
            for _ in range(self.read("<I")):
                k = self.value(kt)
                out[str(k[1] if isinstance(k, tuple) else k)] = self.value(vt)
            self.check(end)
            return out
        raise ValueError(f"unknown value type {t}")

    def fields(self):
        out = {}
        for _ in range(self.read("<H")):
            h, t = self.read("<I"), self.read("<B")
            out["{%08x}" % h] = self.value(t)
        return out

    def check(self, end):
        if self.o != end:
            raise ValueError("length mismatch")


def parse_bin(blob):
    """A binary champion file (PROP) -> {'{path hash}': object}, names left as hashes."""
    err = None
    for old in (False, True):
        try:
            r = _BinReader(blob, old)
            if r.read("<4s") != b"PROP":
                raise ValueError("not a PROP file")
            version = r.read("<I")
            if version >= 2:
                for _ in range(r.read("<I")):
                    r.o += r.read("<H")
            types = [r.read("<I") for _ in range(r.read("<I"))]
            out = {}
            for t in types:
                size = r.read("<I")
                end = r.o + size
                h = r.read("<I")
                obj = r.fields()
                r.check(end)
                obj["__type"] = "{%08x}" % t
                out["{%08x}" % h] = obj
            if r.o != len(blob):
                raise ValueError("trailing bytes")
            return out
        except (ValueError, struct.error) as e:
            err = e
    raise ValueError(f"could not read binary champion file: {err}")


def merge_bin(export, binary):
    """Name the binary file's entries and links from the export's entry names."""
    names = {fnv1a(k): k for k in export if not k.startswith("{")}

    def fix(v):
        if isinstance(v, tuple):  # a link to another entry
            return names.get(v[1], v[1])
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v

    return {names.get(h, h): fix(obj) for h, obj in binary.items()}


def is_typed(data):
    return any(isinstance(o, dict) and "__type" in o for o in data.values())


def load_champion_data(json_path):
    """(data, source) for one champion; data is None when it cannot be read."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    source = "export"
    if not is_typed(data):
        bin_path = json_path.with_name(json_path.name[:-len(".json")])
        if not bin_path.exists():
            return None, "export has no class names and the .bin file is missing"
        data = merge_bin(data, parse_bin(bin_path.read_bytes()))
        source = "bin"
    return unhash_names(data), source


# ---------------------------------------------------------------------------------------
# A value that may scale with stats, buffs or the champion's level


class Expr:
    """const + sum(coef * term) + level[champion level]. Terms are symbolic keys."""

    def __init__(self, const=0.0, terms=None, level=None):
        self.const = const
        self.terms = dict(terms or {})
        self.level = level  # list of MAX_LEVEL values (levels 1..18) or None

    def is_const(self):
        return not self.terms and self.level is None

    def __add__(self, other):
        terms = dict(self.terms)
        for k, v in other.terms.items():
            terms[k] = terms.get(k, 0.0) + v
        if self.level is None:
            level = other.level
        elif other.level is None:
            level = self.level
        else:
            level = [a + b for a, b in zip(self.level, other.level)]
        return Expr(self.const + other.const, terms, level)

    def scale(self, k):
        return Expr(self.const * k, {t: v * k for t, v in self.terms.items()},
                    None if self.level is None else [v * k for v in self.level])

    def __mul__(self, other):
        if other.is_const():
            return self.scale(other.const)
        if self.is_const():
            return other.scale(self.const)
        raise Unresolved("nonlinear: product of two scaling values",
                         "both sides scale with a stat, buff or level")


def level_vector(fn):
    return Expr(level=[fn(lv) for lv in range(1, MAX_LEVEL + 1)])


def progression(level):
    past = max(level, 1) - 1
    return past * (0.7025 + 0.0175 * past)


def interpolated(start, end, level, by_progression):
    reached = progression(level) if by_progression else max(level, 1) - 1
    share = reached / (MAX_LEVEL - 1)
    return start * (1 - share) + end * share


def stepped(level1, initial, points, level):
    value, reached, rate = level1, 1, initial
    for p_level, bonus, per_level in points:
        if p_level > level:
            break
        value += (p_level - 1 - reached) * rate + bonus
        reached = p_level - 1
        rate = per_level
    if level > reached:
        value += (level - reached) * rate
    return value


# ---------------------------------------------------------------------------------------
# One spell's data


def g(obj, *names, default=None):
    """First present field among names (the export renamed several fields in 15.17)."""
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
    return default


def ranked(values, rank):
    if not isinstance(values, list) or not values:
        return None
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return float(nums[rank] if rank < len(nums) else nums[-1])


class Spell:
    def __init__(self, path, obj):
        self.path = path
        self.obj = obj
        self.m = obj.get("mSpell") or {}
        self.script = obj.get("mScriptName") or ""
        self.dvs = {}
        for v in g(self.m, "DataValues", "mDataValues", default=[]) or []:
            name = g(v, "name", "mName")
            if name is None:
                continue
            vals = g(v, "values", "mValues") or []
            self.dvs[name.lower()] = vals
            if not name.startswith("{"):
                self.dvs.setdefault(fnv1a(name), vals)
        self.calcs = {}
        for name, c in (self.m.get("mSpellCalculations") or {}).items():
            self.calcs[name.lower()] = c
            if not name.startswith("{"):
                self.calcs.setdefault(fnv1a(name), c)

    def lookup(self, table, name):
        low = name.lower()
        if low in table:
            return table[low]
        if not low.startswith("{"):
            return table.get(fnv1a(name))
        return None

    def has_name(self, name):
        return self.lookup(self.calcs, name) is not None or self.lookup(self.dvs, name) is not None

    def varies_by_rank(self):
        """Names of data values and effect amounts that differ between ranks 1 and 5."""
        out = []
        for v in g(self.m, "DataValues", "mDataValues", default=[]) or []:
            vals = g(v, "values", "mValues") or []
            nums = [x for x in vals[1:6] if isinstance(x, (int, float))] if isinstance(vals, list) else []
            if len(set(nums)) > 1:
                out.append(g(v, "name", "mName") or "?")
        for i, eff in enumerate(self.m.get("mEffectAmount") or [], 1):
            vals = (eff or {}).get("value") or []
            nums = [v for v in vals[1:6] if isinstance(v, (int, float))]
            if len(set(nums)) > 1:
                out.append(f"effect{i}amount")
        return out


def find_record(folder, data):
    """(key, CharacterRecord) for the champion's main record, or None. Its key is
    Characters/<Folder>/CharacterRecords/Root, or that path's FNV-1a hash where the export left
    entry keys unnamed (Senna in 10.1, Rell in 10.25). Failing both, the file's only
    CharacterRecord is used. Other records (URF, SLIME and the like) are mode variants."""
    records = [(k, o) for k, o in data.items() if isinstance(o, dict) and o.get("__type") == "CharacterRecord"]
    want = fnv1a(f"Characters/{folder}/CharacterRecords/Root")
    for k, o in records:
        if k.endswith("/Root") and k.lower() == f"characters/{folder.lower()}/characterrecords/root":
            return k, o
    for k, o in records:
        if k == want:
            return k, o
    roots = [(k, o) for k, o in records if k.endswith("/Root")]
    if len(roots) == 1:
        return roots[0]
    return records[0] if len(records) == 1 else None


class Champion:
    def __init__(self, folder, data):
        self.folder = folder
        self.data = data
        self.spells = {}
        self.spells_lc = {}
        self.by_script = {}
        for k, o in data.items():
            if isinstance(o, dict) and o.get("__type") == "SpellObject":
                s = Spell(k, o)
                self.spells[k] = s
                self.spells_lc[k.lower()] = s
                for key in (s.script, k.rsplit("/", 1)[-1], o.get("ObjectName") or ""):
                    if key:
                        self.by_script.setdefault(key.lower(), s)
        self.record = find_record(folder, data)
        self.name = folder
        self.passive = None
        self.slots = {}
        self.ability_of = {}
        if self.record:
            rk, rec = self.record
            self.name = rec.get("mCharacterName") or folder
            prefix = (rk.split("/CharacterRecords/")[0] if "/CharacterRecords/" in rk
                      else f"Characters/{folder}") + "/Spells/"
            spells = rec.get("spells") or [prefix + n for n in rec.get("spellNames") or []]
            for i, sp in enumerate(spells[:4]):
                self.slots[self.entry_path(sp)] = "QWER"[i]
            if rec.get("mCharacterPassiveSpell"):
                path = self.entry_path(rec["mCharacterPassiveSpell"])
                self.slots[path] = "P"
                self.passive = self.spells_lc.get(path)
            else:
                self.passive = self.unlinked_passive(rec)
                if self.passive is not None:
                    self.slots.setdefault(self.passive.path.lower(), "P")
            for ab_path in rec.get("mAbilities") or []:
                ab = data.get(ab_path)
                if ab is None and not ab_path.startswith("{"):
                    ab = data.get(fnv1a(ab_path))
                if not isinstance(ab, dict):
                    continue
                root = self.entry_path(ab["mRootSpell"]) if ab.get("mRootSpell") else None
                for child in [root] + list(ab.get("mChildSpells") or []):
                    if child:
                        self.ability_of.setdefault(self.entry_path(child), (ab_path, root))

    def entry_path(self, path):
        """The lower-case entry key the file uses for path. Some exports leave entry keys as the
        FNV-1a hash of the path (Senna's spells in 10.1 and 10.20, Rell's in 10.25) while the
        champion record names them in full."""
        low = path.lower()
        if low in self.spells_lc or low.startswith("{"):
            return low
        h = fnv1a(path)
        return h if h in self.spells_lc else low

    def unlinked_passive(self, rec):
        """The passive spell of a record with no mCharacterPassiveSpell (every champion in 10.1;
        the field was added champion by champion from about 10.10 until after 10.23), tried in
        this order:
          1. the spell named by passiveLuaName (AnniePassive in 10.1);
          2. the spell whose text keys include the record's passiveToolTip (Brand's record names
             Spell_BrandPassive_Summary and no passiveLuaName);
          3. the spell named <Champion>Passive or <Champion>P (YuumiP and CaitlynP in 10.1, whose
             records leave passiveLuaName empty);
          4. the only spell whose keyTooltip is Spell_<Champion>Passive_Tooltip or
             Spell_<Champion>P_Tooltip.
        A spell found by an earlier step wins even if it names no text (YasuoPassive in 10.1)."""
        lua = rec.get("passiveLuaName")
        if isinstance(lua, str) and lua.lower() in self.by_script:
            return self.by_script[lua.lower()]
        key = rec.get("passiveToolTip")
        if isinstance(key, str) and key:
            for sp in self.spells.values():
                if key in loc_keys_of(sp).values():
                    return sp
        names = {self.folder.lower(), str(rec.get("mCharacterName") or self.folder).lower()}
        for name in sorted(names):
            for suffix in ("passive", "p"):
                if name + suffix in self.by_script:
                    return self.by_script[name + suffix]
        wanted = {f"spell_{n}{s}_tooltip" for n in names for s in ("passive", "p")}
        found = [sp for sp in self.spells.values()
                 if str(loc_keys_of(sp).get("keyTooltip") or "").lower() in wanted]
        return found[0] if len(found) == 1 else None

    def slot(self, path):
        # Paths are compared without case: 15.1 Fiddlesticks mixes 'FiddleSticks' and 'Fiddlesticks'.
        path = path.lower()
        if path in self.slots:
            return self.slots[path]
        ab = self.ability_of.get(path)
        if ab and ab[1] in self.slots:
            return self.slots[ab[1]] + "-form"
        return "ability-child" if ab else "other"

    def siblings(self, path):
        ab = self.ability_of.get(path.lower())
        if not ab:
            return []
        return [p for p, a in self.ability_of.items() if a == ab and p != path.lower()]


def loc_keys_of(spell):
    return ((spell.m.get("mClientData") or {}).get("mTooltipData") or {}).get("mLocKeys") or {}


def level_count(spell):
    lists = (((spell.m.get("mClientData") or {}).get("mTooltipData") or {}).get("mLists") or {})
    lu = lists.get("LevelUp") or {}
    n = lu.get("levelCount")
    return int(n) if isinstance(n, (int, float)) and n >= 1 else None


def rank_info(ch, path, sp):
    """(ranks, rank_source, varying names) for one spell."""
    n = level_count(sp)
    if n is not None:
        return list(range(1, n + 1)), "LevelUp list", []
    ab = ch.ability_of.get(path.lower())
    root = ch.spells_lc.get(ab[1]) if ab and ab[1] else None
    n = level_count(root) if root else None
    if n is not None:
        return list(range(1, n + 1)), "ability root spell's LevelUp list", []
    varying = sp.varies_by_rank()
    if varying:
        return [1], "one rank, but data varies across indices 1 to 5", varying
    return [1], "none (one rank)", []


# ---------------------------------------------------------------------------------------
# Evaluating calculations


class Context:
    def __init__(self, champ, spell, stat_names):
        self.champ = champ
        self.spell = spell
        self.stat_names = stat_names
        self.part_types = Counter()

    def dv(self, name, rank, spell=None):
        sp = spell or self.spell
        vals = sp.lookup(sp.dvs, name)
        if vals is None:
            raise Unresolved("missing data value", f"{name} is not declared on this spell")
        if not vals:
            # The data value is declared with no numbers, which the file stores as an empty
            # list: 0 at every rank (Akali's passive declares no per-level growth this way).
            return 0.0
        v = ranked(vals, rank)
        if v is None:
            raise Unresolved("missing data value", f"{name} has no numbers")
        return v

    def part(self, p, rank, depth):
        if depth <= 0:
            raise Unresolved("reference loop or nesting too deep")
        if isinstance(p, (int, float)):
            return Expr(float(p))
        if not isinstance(p, dict):
            raise Unresolved("malformed part", repr(p)[:60])
        t = p.get("__type", "?")
        self.part_types[t] += 1
        # A field left out of a part holds the class default, which the export omits; such
        # defaults (mStat 0, mStatFormula 0, mNumber 0) are read as written.
        if t == "NamedDataValueCalculationPart":
            return Expr(self.dv(p.get("mDataValue", ""), rank))
        if t == "NumberCalculationPart":
            return Expr(float(p.get("mNumber", 0.0)))
        if t == "EffectValueCalculationPart":
            return Expr(self.effect(int(p.get("mEffectIndex", 0)), rank))
        if t == "SumOfSubPartsCalculationPart":
            total = Expr()
            for sp in p.get("mSubparts") or []:
                total = total + self.part(sp, rank, depth - 1)
            return total
        if t == "ProductOfSubPartsCalculationPart":
            if "mPart1" not in p or "mPart2" not in p:
                raise Unresolved("product part missing",
                                 "ProductOfSubPartsCalculationPart lacks mPart1 or mPart2")
            return self.part(p["mPart1"], rank, depth - 1) * self.part(p["mPart2"], rank, depth - 1)
        if t == "ClampSubPartsCalculationPart":
            total = Expr()
            for sp in p.get("mSubparts") or []:
                total = total + self.part(sp, rank, depth - 1)
            if not total.is_const():
                raise Unresolved("clamp of a scaling value", "ClampSubPartsCalculationPart")
            v = total.const
            if p.get("mFloor") is not None:
                v = max(v, float(p["mFloor"]))
            if p.get("mCeiling") is not None:
                v = min(v, float(p["mCeiling"]))
            return Expr(v)
        if t in ("StatByCoefficientCalculationPart", "StatByNamedDataValueCalculationPart",
                 "StatBySubPartCalculationPart"):
            if t == "StatByCoefficientCalculationPart":
                coef = float(p.get("mCoefficient", 0.0))
            elif t == "StatByNamedDataValueCalculationPart":
                coef = self.dv(p.get("mDataValue", ""), rank)
            else:
                if not p.get("mSubpart"):
                    raise Unresolved("stat part has no subpart", "StatBySubPartCalculationPart")
                sub = self.part(p["mSubpart"], rank, depth - 1)
                if not sub.is_const():
                    raise Unresolved("nonlinear: stat times a scaling value", t)
                coef = sub.const
            return Expr(terms={("stat", int(p.get("mStat", 0)), int(p.get("mStatFormula", 0))): coef})
        if t == "AbilityResourceByCoefficientCalculationPart":
            key = ("resource", int(p.get("mAbilityResource", 0)), int(p.get("mStatFormula", 0)))
            return Expr(terms={key: float(p.get("mCoefficient", 0.0))})
        if t in ("BuffCounterByCoefficientCalculationPart", "BuffCounterByNamedDataValueCalculationPart"):
            coef = (float(p.get("mCoefficient", 0.0)) if t.startswith("BuffCounterByCoef")
                    else self.dv(p.get("mDataValue", ""), rank))
            return Expr(terms={("buff", p.get("mBuffName", "?")): coef})
        if t == "PercentageOfBuffNameElapsed":
            return Expr(terms={("buff_elapsed", p.get("buffName", "?")): float(p.get("Coefficient", 0.0))})
        if t == "ByCharLevelInterpolationCalculationPart":
            s, e = float(p.get("mStartValue", 0.0)), float(p.get("mEndValue", 0.0))
            prog = bool(p.get("mScaleByStatProgressionMultiplier", False))
            return level_vector(lambda lv: interpolated(s, e, lv, prog))
        if t == "ByCharLevelBreakpointsCalculationPart":
            pts = [(int(b.get("mLevel", 0)), float(b.get("mAdditionalBonusAtThisLevel", 0.0)),
                    float(b.get("mBonusPerLevelAtAndAfter", 0.0))) for b in p.get("mBreakpoints") or []]
            l1, init = float(p.get("mLevel1Value", 0.0)), float(p.get("mInitialBonusPerLevel", 0.0))
            return level_vector(lambda lv: stepped(l1, init, pts, lv))
        if t == "ByCharLevelFormulaCalculationPart":
            vals = g(p, "values", "mValues", default=[]) or []
            if not vals:
                raise Unresolved("level formula has no values", "ByCharLevelFormulaCalculationPart")
            return level_vector(lambda lv: float(vals[lv] if lv < len(vals) else vals[-1]))
        # Part classes the export leaves unnamed. Fields per LeagueToolkit's level.rs.
        if t == "{4ce08984}":  # level 1 value and growth per level, all from data values, with breakpoints
            l1 = self.dv(p.get("{91d404a5}", ""), rank)
            init = self.dv(p.get("{bbd778a2}", ""), rank) if p.get("{bbd778a2}") else 0.0
            pts = []
            for b in p.get("{9823b29a}") or []:
                pts.append((int(b.get("level", 0)),
                            self.dv(b["{ae9b464d}"], rank) if b.get("{ae9b464d}") else 0.0,
                            self.dv(b["{b0d8b2ac}"], rank) if b.get("{b0d8b2ac}") else 0.0))
            return level_vector(lambda lv: stepped(l1, init, pts, lv))
        if t == "{b22609db}":  # data value at level 1 plus a data value per level
            l1 = self.dv(p.get("{91d404a5}", ""), rank)
            per = self.dv(p.get("{b2cd0eb0}", ""), rank)
            return level_vector(lambda lv: l1 + (lv - 1) * per)
        if t == "{ee18a47b}":  # interpolate StartDataValue to EndDataValue by level
            s = self.dv(p.get("StartDataValue", ""), rank)
            e = self.dv(p.get("EndDataValue", ""), rank)
            return level_vector(lambda lv: interpolated(s, e, lv, False))
        if t == "{f3cbe7b2}":  # the value of another calculation of this spell
            # Used as a raw number: Ambessa Q's minimum damage is its maximum times
            # Calc_Damage_1_Min_Ratio, a calculation of 0.5 that displays as 50%.
            key = p.get("mSpellCalculationKey", "")
            return self.calc_value(key, rank, depth - 1)[0]
        if t == "{9e9e2e5c}":  # DataValue read from the spell SourceObject
            src = self.champ.spells.get(p.get("SourceObject", ""))
            if not src:
                raise Unresolved("source spell not in champion file", str(p.get("SourceObject")))
            return Expr(self.dv(p.get("DataValue", ""), rank, src))
        raise Unresolved(f"part type unsupported: {t}")

    def effect(self, index, rank, spell=None):
        sp = spell or self.spell
        if index > MAX_EFFECT_INDEX:
            raise Unresolved("effect index above 10",
                             f"Effect{index}Amount (spells hold at most {MAX_EFFECT_INDEX} effect amounts)")
        eff = sp.m.get("mEffectAmount") or []
        if index < 1 or index > len(eff):
            raise Unresolved("missing effect amount", f"Effect{index}Amount")
        v = ranked((eff[index - 1] or {}).get("value"), rank)
        if v is None:
            raise Unresolved("missing effect amount", f"Effect{index}Amount is empty")
        return v

    def calc_value(self, key, rank, depth):
        """(Expr, percent, precision, info) for calculation `key` at `rank`."""
        if depth <= 0:
            raise Unresolved("reference loop or nesting too deep")
        c = self.spell.lookup(self.spell.calcs, key)
        if c is None:
            raise Unresolved("calculation reference not found", key)
        t = c.get("__type")
        info = {}
        if "DamageType" in c:
            info["damage_type_code"] = c["DamageType"]
        if t == "GameCalculation":
            if "ResultModifier" in c:
                raise Unresolved("ResultModifier unsupported", key)
            total = Expr()
            for p in c.get("mFormulaParts") or []:
                total = total + self.part(p, rank, depth - 1)
            if c.get("mMultiplier") is not None:
                total = total * self.part(c["mMultiplier"], rank, depth - 1)
            prec = c.get("mPrecision")
            return total, bool(c.get("mDisplayAsPercent", False)), (int(prec) if prec and prec > 0 else None), info
        if t == "GameCalculationModified":
            if "mOverrideSpellLevel" in c:
                raise Unresolved("mOverrideSpellLevel unsupported", key)
            base, pct, prec, binfo = self.calc_value(c.get("mModifiedGameCalculation", ""), rank, depth - 1)
            mult = self.part(c["mMultiplier"], rank, depth - 1) if c.get("mMultiplier") is not None else Expr(1.0)
            binfo.update(info)
            return base * mult, pct, prec, binfo
        if t == "GameCalculationConditional":
            default = c.get("mDefaultGameCalculation")
            cond = c.get("mConditionalGameCalculation")
            req = (c.get("mConditionalCalculationRequirements") or {}).get("__type", "?")
            chosen = default or cond
            if not chosen:
                raise Unresolved("conditional calculation names no calculation", key)
            e, pct, prec, binfo = self.calc_value(chosen, rank, depth - 1)
            binfo.update(info)
            binfo["conditional"] = {"shown": chosen, "when_default": bool(default),
                                    "alternative": cond if default else None, "requirement": req}
            return e, pct, prec, binfo
        raise Unresolved(f"calculation type unsupported: {t}", key)

    # -- labels -------------------------------------------------------------------------

    def term_label(self, key, coef, percent_calc):
        return term_label(key, coef, percent_calc, self.stat_names)


def term_label(key, coef, percent_calc, stat_names):
    """A reader's wording of one scaling term. This is the script's own wording, not the game's."""
    kind = key[0]
    fraction = False
    if kind == "stat":
        _, code, formula = key
        name = stat_names.get(code) if stat_names is not None else None
        stat = name if name else f"stat #{code}"
        fraction = stat in FRACTION_STATS or (stat == "attack speed" and formula == 2)
        if stat == "health" and formula == 0:
            stat = "max health"
        what = STAT_FORMULA.get(formula, f"formula{formula} ") + stat
    elif kind == "resource":
        _, res, formula = key
        what = STAT_FORMULA.get(formula, "") + ("max mana" if res == 0 else f"resource #{res}")
    elif kind == "buff":
        what = f"per stack of buff {key[1]}"
    else:
        what = f"of buff {key[1]} elapsed"
    if fraction:
        # The stat is a fraction of 1, so 100% of it is the value 1.
        return (f"+{fmt(coef * 100, 3)}% per 100% {what}" if percent_calc
                else f"+{fmt(coef, 3)} per 100% {what}")
    if percent_calc:
        return f"+{fmt(coef * 10000, 3)}% per 100 {what}" if kind in ("stat", "resource") \
            else f"+{fmt(coef * 100, 3)}% {what}"
    if kind in ("stat", "resource"):
        return f"+{fmt(coef * 100, 3)}% {what}"
    return f"+{fmt(coef, 3)} {what}"


def term_dict(key, coef, label, stat_names):
    d = {"kind": key[0], "coefficient": clean(coef), "label": label}
    if key[0] == "stat":
        d["stat_code"], d["stat_formula"] = key[1], key[2]
        d["stat"] = (stat_names or {}).get(key[1]) if stat_names is not None else None
    elif key[0] == "resource":
        d["resource"], d["stat_formula"] = key[1], key[2]
    else:
        d["buff"] = key[1]
    return d


# ---------------------------------------------------------------------------------------
# Placeholders


def parse_token(tok):
    """[spell.Script:]Name[.precision][*factor] -> dict, or None if not a value token."""
    if not tok or not TOKEN_CHARS.match(tok):
        return None
    value, factor = tok, 1.0
    if "*" in tok:
        value, f = tok.split("*", 1)
        try:
            factor = float(f)
        except ValueError:
            return None
    owner = None
    if ":" in value:
        o, value = value.split(":", 1)
        if not o.lower().startswith("spell."):
            return None
        owner = o[6:]
    precision = None
    if "." in value:
        name, digits = value.rsplit(".", 1)
        try:
            precision = int(digits)
        except ValueError:
            return None
        value = name
    return {"owner": owner, "name": value, "precision": precision, "factor": factor}


def split_rank(name):
    m = re.match(r"^(.*?[^\d])(\d+)$", name)
    return (m.group(1), int(m.group(2))) if m else None


def spell_stat(spell, low, rank):
    m = spell.m
    if low == "cooldown":
        v = ranked(m.get("cooldownTime"), rank)
        if v is None:
            v = ranked((m.get("Cooldown") or {}).get("values"), rank)
        if v is None:
            raise Unresolved("spell sets no cooldown", "class default is 10")
        return v
    if low in ("cost", "basecost"):
        at = max(rank - 1, 0)  # mana arrays start at rank 1
        v = ranked(m.get("mana"), at)
        if v is None:
            v = ranked((m.get("manaValues") or {}).get("values"), at)
        if v is None:
            raise Unresolved("spell sets no cost")
        return v
    if low == "ammorechargetime":
        v = ranked(m.get("mAmmoRechargeTime"), rank)
        if v is None:
            raise Unresolved("spell sets no ammo recharge time")
        return v
    if low == "maxammo":
        v = ranked(m.get("mMaxAmmo"), rank)
        if v is None:
            raise Unresolved("spell sets no max ammo")
        return v
    field = {"castrange": "castRange", "castrangedisplayoverride": "castRangeDisplayOverride"}[low]
    v = ranked(m.get(field), rank)
    if v is None:
        raise Unresolved(f"spell sets no {field}")
    return v


def legacy_stat(spell, name):
    """A legacy @Char...@ token as a symbolic scaling. Stat codes 0 (AP) and 2 (AD) are the
    same in every layout."""
    m = LEGACY_STAT_RE.match(name)
    field = "mCoefficient2" if m.group(2) else "mCoefficient"
    coef = spell.m.get(field)
    if not isinstance(coef, (int, float)):
        raise Unresolved("legacy stat token: spell has no coefficient", field)
    code, formula = LEGACY_STAT_KEYS[m.group(1).lower()]
    return Expr(terms={("stat", code, formula): float(coef)})


def resolve_placeholder(tok_text, champ, spell, ranks, stat_names):
    out = {"token": tok_text}
    tok = parse_token(tok_text)
    if tok is None:
        out.update(kind="not_a_value", status="ignored")
        return out
    name = tok["name"]
    low = name.lower()
    out["name"] = name
    if tok["owner"]:
        out["owner_spell"] = tok["owner"]
    if tok["precision"] is not None:
        out["precision"] = tok["precision"]
    if tok["factor"] != 1.0:
        out["factor"] = tok["factor"]

    if low in UI_TOKENS or re.search(r"\d+(Prefix|Postfix)$", name) or low.startswith("list"):
        out.update(kind="ui", status="ignored")
        return out

    target = spell
    if tok["owner"]:
        target = champ.by_script.get(tok["owner"].lower())
        if target is None:
            out.update(kind="reference", status="unresolved",
                       reason="referenced spell not in champion file", detail=tok["owner"])
            return out

    ctx = Context(champ, target, stat_names)
    factor = tok["factor"]
    per_rank = []
    kind = None
    percent = False
    precision = None
    info = {}
    try:
        for rank in ranks:
            if low in SPELL_STATS:
                kind = "spell_stat"
                e = Expr(spell_stat(target, low, rank))
            elif target.lookup(target.calcs, name) is not None:
                kind = "calculation"
                e, percent, precision, info = ctx.calc_value(name, rank, DEPTH)
            elif target.lookup(target.dvs, name) is not None:
                kind = "data_value"
                e = Expr(ctx.dv(name, rank))
            elif EFFECT_RE.match(name):
                kind = "effect_amount"
                e = Expr(ctx.effect(int(EFFECT_RE.match(name).group(1)), rank))
            elif SCRIPT_VAR_RE.match(name):
                kind = "script_variable"
                raise Unresolved("script variable (fN): set by the game script at run time")
            elif LEGACY_STAT_RE.match(name):
                kind = "legacy_stat_token"
                e = legacy_stat(target, name)
            else:
                sr = None
                if low.endswith("nl"):
                    base = name[:-2]
                    if target.has_name(base) or EFFECT_RE.match(base) or base.lower() in SPELL_STATS:
                        sr = (base, min(rank + 1, ranks[-1]))
                if sr is None:
                    sr = split_rank(name)
                    if sr and not (target.lookup(target.dvs, sr[0]) is not None or EFFECT_RE.match(sr[0])
                                   or sr[0].lower() in SPELL_STATS):
                        sr = None
                if sr is None:
                    kind = "unknown_name"
                    hint = [p.rsplit("/", 1)[-1] for p in champ.siblings(target.path)
                            if champ.spells_lc.get(p) and champ.spells_lc[p].has_name(name)]
                    if not hint:
                        hint = [s.path.rsplit("/", 1)[-1] for s in champ.spells.values()
                                if s is not target and s.has_name(name)][:3]
                    raise Unresolved("name not found in spell data",
                                     ("found in other spell(s): " + ", ".join(hint)) if hint else "")
                kind = "ranked_value"
                base, at = sr
                bl = base.lower()
                if bl in SPELL_STATS:
                    e = Expr(spell_stat(target, bl, at))
                elif EFFECT_RE.match(base):
                    e = Expr(ctx.effect(int(EFFECT_RE.match(base).group(1)), at))
                else:
                    e = Expr(ctx.dv(base, at))
            if percent:
                e = Expr(e.const * 100, e.terms, None if e.level is None else [v * 100 for v in e.level])
            per_rank.append(e.scale(factor) if factor != 1.0 else e)
    except Unresolved as u:
        out.update(kind=kind or "unknown", status="unresolved", reason=u.reason)
        if u.detail:
            out["detail"] = u.detail
        return out

    out["kind"] = kind
    out["status"] = "resolved"
    if percent:
        out["display_as_percent"] = True
    out.update({k: v for k, v in info.items()})
    decimals = tok["precision"] if tok["precision"] is not None and tok["precision"] >= 0 else \
        (precision if precision is not None else DEFAULT_DECIMALS)
    out["ranks"] = list(ranks)
    out["base"] = [clean(e.const) for e in per_rank]
    if any(e.level is not None for e in per_rank):
        out["level_range"] = [None if e.level is None else [clean(e.const + e.level[0]), clean(e.const + e.level[-1])]
                              for e in per_rank]
    keys = []
    for e in per_rank:
        for k in e.terms:
            if k not in keys:
                keys.append(k)
    if keys:
        out["scalings"] = []
        for k in keys:
            coefs = [e.terms.get(k, 0.0) for e in per_rank]
            label = ctx.term_label(k, coefs[0], percent) if len(set(map(clean, coefs))) == 1 else \
                " / ".join(ctx.term_label(k, c, percent) for c in coefs)
            d = term_dict(k, coefs[0], label, stat_names)
            d["coefficient"] = [clean(c) for c in coefs]
            out["scalings"].append(d)
    disp = []
    suffix = "%" if percent else ""
    for e in per_rank:
        if e.level is not None:
            s = f"{fmt(e.const + e.level[0], decimals)}{suffix} to {fmt(e.const + e.level[-1], decimals)}{suffix} (by level)"
        else:
            s = fmt(e.const, decimals) + suffix
        if e.terms:
            s += " (" + " ".join(ctx.term_label(k, v, percent) for k, v in e.terms.items()) + ")"
        disp.append(s)
    out["display"] = disp
    return out


# ---------------------------------------------------------------------------------------
# Numbers typed into the text

MASK_RE = re.compile(r"<[^>]*>|@[^@<>]*@|%i:[^%\s]*%|\{\{[^}]*\}\}|&[a-zA-Z]+;|&#\d+;")
CONTEXT_DROP_RE = re.compile(r"<[^>]*>?|%i:[^%\s]*%|&[a-zA-Z]+;|&#\d+;")
NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(\s?%|st|nd|rd|th|x)?(?![\w])")


def typed_numbers(text):
    masked = list(text)
    for m in MASK_RE.finditer(text):
        for i in range(m.start(), m.end()):
            masked[i] = " "
    masked = "".join(masked)
    plain = re.sub(r"\s+", " ", masked)
    out = []
    for m in NUMBER_RE.finditer(masked):
        # Context keeps placeholders (as @Name@) and drops markup, so a reader sees the sentence.
        left = re.sub(r"\s+", " ", CONTEXT_DROP_RE.sub(" ", text[max(0, m.start() - 60):m.start()])).strip()
        right = re.sub(r"\s+", " ", CONTEXT_DROP_RE.sub(" ", text[m.end():m.end() + 60])).strip()
        out.append({"value": clean(float(m.group(1))), "text": m.group(0), "start": m.start(),
                    "end": m.end(), "context": f"{left} [{m.group(0)}] {right}".strip()})
    return out, plain.strip()


def tokens_in(text):
    """(token matches, @ signs left unpaired). A stray @ would shift every later pairing."""
    matches = list(TOKEN_RE.finditer(text))
    return matches, text.count("@") - 2 * len(matches)


# ---------------------------------------------------------------------------------------
# A patch


def detect_stat_layout(champs):
    """(layout, stat names, votes). Each anchor votes for every layout its stat codes fit
    ('C/D' when they fit both), and the layout is the one that every vote allows. Anchors whose
    calculation names no stat do not vote; one whose codes fit no layout votes '?'."""
    votes = []
    allowed = set(STAT_TABLES)
    for folder, script, calc, expected in STAT_ANCHORS:
        ch = champs.get(folder)
        sp = ch.by_script.get(script.lower()) if ch else None
        c = sp.lookup(sp.calcs, calc) if sp else None
        if c is None:
            continue
        codes = set(int(x) for x in re.findall(r'"mStat": (\d+)', json.dumps(c)))
        if not codes:
            continue
        fits = sorted(lay for lay, sets in expected.items() if codes in sets)
        votes.append("/".join(fits) or "?")
        allowed &= set(fits)
    if votes and len(allowed) == 1:
        layout = allowed.pop()
        return layout, STAT_TABLES[layout], votes
    return "unknown", None, votes


def text_fields(loc_keys):
    """The keyTooltip* fields of one mLocKeys, known ones first."""
    extra = sorted(k for k in loc_keys if k.startswith("keyTooltip") and k not in TEXT_FIELDS)
    return [k for k in TEXT_FIELDS if k in loc_keys] + extra


def text_jobs(ch):
    """[(spell path, Spell, slot, [(text field, key)])] for one champion, one entry per spell.

    In some early patches a passive spell names no keyTooltip (NasusPassive in 10.1), or no
    passive spell is found at all (Bard in 10.1). Only then is the champion record's
    passiveToolTip read (game_character_passiveDescription_Nasus): the short summary shown in
    champion select, not the in-game tooltip. Its field is named passiveToolTip, and it joins
    the passive spell's entry when that spell has one.
    """
    jobs = []
    passive_has_text = False
    for path, sp in ch.spells.items():
        loc_keys = loc_keys_of(sp)
        fields = text_fields(loc_keys)
        if fields:
            slot = ch.slot(path)
            jobs.append((path, sp, slot, [(f, loc_keys[f]) for f in fields]))
            passive_has_text = passive_has_text or (slot == "P" and "keyTooltip" in fields)
    rec = ch.record[1] if ch.record else {}
    key = rec.get("passiveToolTip")
    if isinstance(key, str) and key and not passive_has_text:
        sp = ch.passive
        if sp is None:
            sp = Spell(f"Characters/{ch.folder}/(passive with no spell)", {})
        for path, _, _, fields in jobs:
            if path == sp.path:
                fields.append(("passiveToolTip", key))
                break
        else:
            jobs.append((sp.path, sp, "P", [("passiveToolTip", key)]))
    return jobs


def output_paths(out_root, patch, locale):
    return out_root / f"{patch}.{locale}.jsonl", out_root / f"{patch}.{locale}.summary.json"


class PatchFailed(Exception):
    """A patch that cannot be resolved at all (no manifest, or no readable text file)."""


def duplicate_targets(jobs):
    """{(hashed spell path, lower-case text key): spell path it duplicates} for one champion.

    A spell whose entry key the export left as a hash sometimes names the same text as another
    spell (Aurora's AuroraRMissile, '{36b6a65c}' in 15.16, reuses Spell_AuroraR_Tooltip). The
    text belongs to the only spell naming it in slot P, Q, W, E or R (also when every spell
    naming it is stored under a hash, as for Samira in 10.20 and Rell in 10.25), or failing that
    to the only spell whose script name the key carries (Spell_<Script>_Tooltip...). The other
    hashed spells are marked as its duplicates. A key with no such owner is left unmarked.
    The key-name rule at work: in 12.8 ZedW2 ('{e0c2427d}', W-form) and ZedR2 (R-form) share
    Spell_ZedW2_Tooltip, and ZedW2 owns it by its script name, so ZedW2 is not marked. Spells
    under readable paths are never marked."""
    owners = {}
    for path, sp, slot, fields in jobs:
        script = (getattr(sp, "script", "") or "").lower()
        for _, key in fields:
            if isinstance(key, str) and key:
                owners.setdefault(key.lower(), []).append((path, slot, script))
    out = {}
    for key, users in owners.items():
        if len({p for p, _, _ in users}) < 2:
            continue
        pqwer = list(dict.fromkeys(p for p, slot, _ in users if slot in PQWER_SLOTS))
        named_in_key = list(dict.fromkeys(p for p, _, script in users
                                          if script and key.startswith(f"spell_{script}_tooltip")))
        if len(pqwer) == 1:
            owner = pqwer[0]
        elif len(named_in_key) == 1:
            owner = named_in_key[0]
        else:
            continue
        for p, _, _ in users:
            if p.startswith("{") and p != owner:
                out[(p, key)] = owner
    return out


def run_patch(patch, raw_root, out_root, locale):
    raw = raw_root / patch
    manifest_path = raw / "manifest.json"
    if not manifest_path.exists():
        raise PatchFailed(f"No data for patch {patch} under {raw}. "
                          f"Run: python3 scripts/fetch_cdragon.py --patches {patch}")
    manifest = json.loads(manifest_path.read_text())
    st_path, st_layout = find_text_table(raw, manifest, locale)
    if not st_path:
        raise PatchFailed(f"No {locale} string table for {patch} (layout {st_layout}).")
    try:
        table = TextTable(st_path, st_layout)
    except (ValueError, KeyError, struct.error) as e:  # a truncated or malformed file
        raise PatchFailed(f"Could not read {st_path.relative_to(raw)}: {type(e).__name__}: {e}") from e
    build = manifest.get("cdragon_version")

    champ_files = sorted(raw.glob("game/data/characters/*/*.bin.json"))
    champs = {}
    sources = Counter()
    unreadable = {}
    jade_folders = []
    for f in champ_files:
        folder = f.parent.name
        if folder.startswith("jade_"):
            jade_folders.append(folder)
            continue
        data, source = load_champion_data(f)
        if data is None:
            unreadable[folder] = source
            continue
        sources[source] += 1
        champs[folder] = Champion(folder, data)
    layout, stat_names, votes = detect_stat_layout(champs)

    out_root.mkdir(parents=True, exist_ok=True)
    out_path, summary_path = output_paths(out_root, patch, locale)
    tmp = out_path.with_suffix(".jsonl.tmp")

    c = Counter()
    by_field = {}
    reasons = Counter()
    reasons_pqwer = Counter()
    by_kind = Counter()
    part_types = Counter()
    rank_sources = Counter()
    linked_keys = set()
    missing_keys = []
    jade_keys = []
    unpaired = []
    one_rank_varying = []
    examples = {}
    with tmp.open("w", encoding="utf-8") as fh:
        for folder, ch in champs.items():
            jobs = text_jobs(ch)
            dup_of = duplicate_targets(jobs)
            for path, sp, slot, keyed_fields in jobs:
                c["spells_with_tooltip_key"] += 1
                pqwer = slot in PQWER_SLOTS
                ranks, rank_source, varying = rank_info(ch, path, sp)
                spell_counted = False
                for field, key in keyed_fields:
                    if not isinstance(key, str) or not key:
                        continue
                    fc = by_field.setdefault(field, Counter())
                    if JADE_KEY_RE.search(key):
                        jade_keys.append(key)
                        continue
                    text = table.get(key)
                    if text is None:
                        fc["key_missing_from_table"] += 1
                        missing_keys.append(f"{field}: {key}")
                        continue
                    linked_keys.add(key.lower())
                    duplicate = dup_of.get((path, key.lower()))
                    c["records"] += 1
                    if duplicate:
                        c["records_marked_duplicate"] += 1
                    fc["records"] += 1
                    checked = not duplicate and field != "passiveToolTip"
                    if checked:
                        c["checked_records"] += 1
                        fc["checked_records"] += 1
                    if not spell_counted:
                        spell_counted = True
                        rank_sources[rank_source] += 1
                        if varying:
                            one_rank_varying.append(f"{path} ({', '.join(varying[:4])})")
                    matches, stray = tokens_in(text)
                    if stray:
                        c["records_with_unpaired_at"] += 1
                        unpaired.append(f"{path} {field}: {stray} unpaired @")
                    phs = []
                    for m in matches:
                        r = resolve_placeholder(m.group(1), ch, sp, ranks, stat_names)
                        r["start"], r["end"] = m.start(), m.end()
                        phs.append(r)
                        if r["status"] == "ignored":
                            c["placeholders_ignored_ui"] += 1
                            continue
                        c["placeholders"] += 1
                        fc["placeholders"] += 1
                        if duplicate:
                            c["placeholders_in_duplicates"] += 1
                            c["placeholders_resolved_in_duplicates"] += r["status"] == "resolved"
                        by_kind[(r["kind"], r["status"])] += 1
                        if pqwer:
                            c["placeholders_pqwer_slots"] += 1
                        if r["status"] == "resolved":
                            c["placeholders_resolved"] += 1
                            fc["placeholders_resolved"] += 1
                            if pqwer:
                                c["placeholders_resolved_pqwer_slots"] += 1
                            if r.get("scalings") or r.get("level_range"):
                                c["resolved_with_symbolic_part"] += 1
                            for term in r.get("scalings") or []:
                                if term["kind"] == "stat":
                                    c["stat_scalings"] += 1
                                    c["stat_scalings_unnamed"] += term["stat"] is None
                        else:
                            reasons[r["reason"]] += 1
                            if pqwer:
                                reasons_pqwer[r["reason"]] += 1
                            examples.setdefault(r["reason"], f"{path} @{r['token']}@ {r.get('detail', '')}".strip())
                    c["tokens_found"] += len(matches)
                    nums, plain = typed_numbers(text)
                    c["typed_numbers"] += len(nums)
                    fc["typed_numbers"] += len(nums)
                    if nums:
                        c["records_with_typed_numbers"] += 1
                    if checked:
                        c["checked_typed_numbers"] += len(nums)
                        fc["checked_typed_numbers"] += len(nums)
                        if nums:
                            c["checked_records_with_typed_numbers"] += 1
                            fc["checked_records_with_typed_numbers"] += 1
                    if phs and all(p["status"] != "unresolved" for p in phs) and not stray:
                        c["records_fully_resolved"] += 1
                    if not [p for p in phs if p["status"] != "ignored"]:
                        c["records_without_placeholders"] += 1
                    includes = INCLUDE_RE.findall(text)
                    if includes:
                        c["records_with_includes"] += 1
                    rec = {
                        "patch": patch, "locale": locale, "cdragon_version": build,
                        "champion": ch.name, "champion_folder": folder,
                        "spell_path": path, "script_name": sp.script or None, "slot": slot,
                        "text_field": field, "loc_key": key,
                        "ranks": ranks, "rank_source": rank_source,
                        "raw_text": text, "plain_text": plain,
                        "placeholders": phs, "typed_numbers": nums,
                    }
                    if duplicate:
                        rec["duplicate_of"] = duplicate
                    if varying:
                        rec["varies_by_rank"] = varying
                    if includes:
                        rec["includes"] = includes
                    if field == "passiveToolTip":
                        rec["text_note"] = ("champion summary text from the champion record (the passive "
                                            "description shown in champion select), not an in-game tooltip")
                    if stray:
                        rec["unpaired_at_signs"] = stray
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # count part types used by calculations of every spell, for the summary
            for sp in ch.spells.values():
                for calc in (sp.m.get("mSpellCalculations") or {}).values():
                    for t in re.findall(r'"__type": "([^"]+)"', json.dumps(calc)):
                        part_types[t] += 1
    tmp.replace(out_path)

    readable = table.readable_keys()
    if readable is not None:
        st_keys = [k for k in readable if re.match(r"^spell_.*_tooltip$", k) and not JADE_KEY_RE.search(k)]
        unlinked = sorted(set(st_keys) - linked_keys)
        st_stats = {
            "stringtable_spell_tooltip_keys": len(st_keys),
            "stringtable_spell_tooltip_keys_linked": len(set(st_keys) & linked_keys),
            "stringtable_spell_tooltip_keys_unlinked": len(unlinked),
            "linked_keys_outside_spell_tooltip_pattern": len(linked_keys - set(st_keys)),
        }
    else:
        unlinked = None  # a binary table stores hashes only, so unlinked keys cannot be named
        st_stats = {"stringtable_spell_tooltip_keys": None}

    def ratio(a, b):
        return round(a / b, 4) if b else None

    summary = {
        "patch": patch,
        "locale": locale,
        "cdragon_version": build,
        "manifest_failures": manifest.get("failures") or [],
        "string_table": str(st_path.relative_to(raw)),
        "string_table_layout": st_layout,
        "stat_layout": layout,
        "stat_layout_anchor_votes": votes,
        "champions": len(champs),
        "champion_file_sources": dict(sources),
        "champions_unreadable": unreadable,
        **st_stats,
        "unique_linked_keys": len(linked_keys),
        "keys_found_only_by_hash": table.found_by_hash if table.readable else None,
        "counts": dict(c),
        # The records a checker reads: no duplicate_of and not passiveToolTip summary text.
        "checked_records": {"all": c["checked_records"],
                            "keyTooltip": by_field.get("keyTooltip", Counter())["checked_records"]},
        "placeholder_coverage": ratio(c["placeholders_resolved"], c["placeholders"]),
        "placeholder_coverage_pqwer_slots": ratio(c["placeholders_resolved_pqwer_slots"],
                                                  c["placeholders_pqwer_slots"]),
        "placeholder_coverage_without_duplicates": ratio(
            c["placeholders_resolved"] - c["placeholders_resolved_in_duplicates"],
            c["placeholders"] - c["placeholders_in_duplicates"]),
        "by_text_field": {f: {**dict(fc), "coverage": ratio(fc["placeholders_resolved"], fc["placeholders"])}
                          for f, fc in by_field.items()},
        "rank_sources": dict(rank_sources),
        "one_rank_but_data_varies": one_rank_varying,
        "token_check": {"tokens_found": c["tokens_found"],
                        "records_with_unpaired_at": c["records_with_unpaired_at"],
                        "unpaired": unpaired},
        "by_kind": {f"{k}/{s}": v for (k, s), v in sorted(by_kind.items(), key=lambda x: -x[1])},
        "unresolved_reasons": dict(reasons.most_common()),
        "unresolved_reasons_pqwer_slots": dict(reasons_pqwer.most_common()),
        "unresolved_examples": examples,
        "calculation_part_types": dict(part_types.most_common()),
        "jade_keys_skipped": len(jade_keys),
        "jade_folders_skipped": len(jade_folders),
        "tooltip_keys_missing_from_table": missing_keys,
        "unlinked_spell_tooltip_keys": unlinked,
    }
    summary_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    return summary, out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patches", nargs="*", help="patch folders under data/raw (default: all)")
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--locale", default="en_us")
    args = ap.parse_args()
    patches = args.patches or sorted(p.name for p in args.raw_dir.iterdir() if (p / "manifest.json").exists())
    failed = []
    for patch in patches:
        try:
            s, path = run_patch(patch, args.raw_dir, args.out_dir, args.locale)
        except Exception as e:  # noqa: BLE001
            # One patch that cannot be read must not stop the others.
            print(f"{patch} {args.locale}: FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            failed.append(patch)
            continue
        cnt = s["counts"]
        cov = s["placeholder_coverage"]
        print(f"{patch} {args.locale}: {cnt.get('records', 0)} texts from {cnt.get('spells_with_tooltip_key', 0)} spells "
              f"({s['string_table_layout']} table); placeholders {cnt.get('placeholders_resolved', 0)}/"
              f"{cnt.get('placeholders', 0)} resolved ({cov:.1%}); stat layout {s['stat_layout']}"
              if cov is not None else f"{patch}: no placeholders found")
        for field, fc in s["by_text_field"].items():
            fcov = fc["coverage"]
            print(f"    {field}: {fc.get('records', 0)} texts, {fc.get('placeholders_resolved', 0)}/"
                  f"{fc.get('placeholders', 0)} resolved" + (f" ({fcov:.1%})" if fcov is not None else ""))
        for reason, n in list(s["unresolved_reasons"].items())[:8]:
            print(f"    {n:5d}  {reason}")
        if s["champions_unreadable"]:
            print(f"  {len(s['champions_unreadable'])} champion files could not be read; see the summary")
        if s["manifest_failures"]:
            print(f"  the fetch manifest lists {len(s['manifest_failures'])} failed downloads; see the summary")
        if cnt.get("records_marked_duplicate"):
            print(f"  {cnt['records_marked_duplicate']} texts under hashed spell paths are marked duplicate_of another spell")
        print(f"  wrote {path}")
    if failed:
        sys.exit(f"{len(failed)} of {len(patches)} patches failed: {' '.join(failed)}")


if __name__ == "__main__":
    main()
