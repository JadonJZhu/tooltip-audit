#!/usr/bin/env python3
"""Work out the numbers each champion ability tooltip shows, from the game data.

Reads what fetch_cdragon.py saved under data/raw/<patch>/ and writes, per patch and language:
  data/resolved/<patch>.<locale>.jsonl          one record per (spell, tooltip text field) pair
  data/resolved/<patch>.<locale>.spells.jsonl   the gameplay side: one line per spell (see below)
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
paths. A spell sometimes names the same text as the spell the text belongs to (MalzaharWCancel
reuses Spell_MalzaharW_Tooltip in 15.1, and Aurora's R missile, '{36b6a65c}' in 15.16, reuses
the R tooltip); its records carry duplicate_of with that spell's path, so they can be dropped,
and the summary counts them (see duplicate_targets for the rule). The summary's checked_records counts the records left
once duplicate_of and passiveToolTip records are dropped, overall and per text field.

Each record and summary carries the build (cdragon_version) from the fetch manifest, and the
summary copies the manifest's list of failed downloads.

The gameplay side. A record shows the text and the value behind each placeholder; the spells
file shows what the text is checked against. It has one line per spell, keyed by key
('<champion folder>:<spell path>'), for every spell with a record, every spell grouped with one
in the same ability (see spell_groups), and every spell a record or a calculation refers to
(@spell.EliseSpiderE:Effect6Amount@, or a part reading another spell's data value). A line
gives the spell's data values and effect amounts per rank, its coefficient fields (mCoefficient,
mCoefficient2), cooldown and cost, every calculation as written with its value per rank (with
the name of each data value it gives only as a hash, where a known name has that hash), its
level-up list with each row's label text, its value and that value times the row's multiplier
(the number the game shows), and the keys of its group's other spells (group) and of the
spells its calculations read (refers_to). Each record names its line in
spell_context, and the spells its own placeholders read in referenced_spells. A record of
extended text (keyTooltipExtended or keyTooltipExtendedBelowLine) whose spell sets
EnableExtendedTooltip false carries extended_text_hidden_in_game, since the game does not show
that text (39 spells in 16.19 set it, 4 of them with extended text); such records still count
as checked.

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
moved from patch to patch until 11.11; and three stats were inserted, one in 15.7 and two in
15.16. That gives five layouts: D (oldest), C, A, E (15.7 to 15.15) and B. The script tells them
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
# The layout from 15.7 to 15.15, between A and B: one of B's three new stats came in 15.7 and the
# other two in 15.16. Pairing identical stat parts in 15.6 and 15.7 (1,442 parts) gives 0-2
# unchanged and every code from 3 up one higher than layout A; pairing 15.15 and 15.16 (1,486
# parts) gives 0-12 unchanged, 13 to 14 and 14 and later two higher, which is layout B. Code 3 is
# new and unnamed, as in layout B.
STATS_E = {0: "AP", 1: "armor", 2: "AD", 3: None}
STATS_E.update({code + 1: name for code, name in STATS_A.items() if code >= 3})
STAT_TABLES = {"A": STATS_A, "B": STATS_B, "C": STATS_C, "D": STATS_D, "E": STATS_E}

# (champion folder, spell script name, calculation, {layout: stat codes in that layout}).
# Spells are found by script name because older files put them in a different folder
# (Characters/Braum/Spells/BraumW before Characters/Braum/Spells/BraumWAbility/BraumW).
# Layouts B and E agree below 13, so only Zac, Pyke and Urgot tell them apart.
STAT_ANCHORS = [
    ("akshan", "AkshanPassive", "ASModdedMS", {"A": [{3}], "B": [{4}], "E": [{4}]}),
    ("braum", "BraumW", "GrantedAllyMR", {"A": [{5}], "B": [{6}], "C": [{4}], "D": [{4}], "E": [{6}]}),
    ("alistar", "AlistarPassive", "BaseHeal", {"A": [{11}], "B": [{12}], "E": [{12}]}),
    ("zac", "ZacQ", "HealthCostTooltip", {"A": [{11, 12}], "B": [{12, 14}], "C": [{10, 11}], "D": [{9, 10}],
                                          "E": [{12, 13}]}),
    ("pyke", "PykeR", "RDamage", {"A": [{2, 26}], "B": [{2, 29}], "C": [{2, n} for n in range(19, 26)],
                                  "D": [{2, n} for n in range(19, 26)], "E": [{2, 27}]}),
    ("urgot", "UrgotPassive", "CastRange", {"A": [{28}], "B": [{31}], "E": [{29}]}),
    # Both are present, under these calculation names or their hashes, in every patch from 10.1.
    ("chogath", "Feast", "RDamage", {"A": [{11}], "B": [{12}], "C": [{10}], "D": [{9}], "E": [{12}]}),
    ("garen", "GarenW", "TotalShield", {"A": [{11}], "B": [{12}], "C": [{10}], "D": [{9}], "E": [{12}]}),
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
        # Readable tables only: keys present only as a hash. Tooltip keys count in found_by_hash,
        # other lookups (level-up labels) in others_found_by_hash.
        self.found_by_hash = 0
        self.others_found_by_hash = 0

    def key_hash(self, key):
        return xxh64(key.lower().encode("utf-8")) & self.mask

    def get(self, key, tooltip_key=True):
        if self.readable:
            text = self.entries.get(key.lower())
            if text is None:
                text = self.entries.get("{%010x}" % self.key_hash(key))
                if tooltip_key:
                    self.found_by_hash += text is not None
                else:
                    self.others_found_by_hash += text is not None
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
mObjectName mFormat Elements type typeIndex nameOverride multiplier Style EnableExtendedTooltip
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


def stat_words(code, formula, stat_names):
    """(reader's name of a stat code and formula, whether the game stores it as a fraction)."""
    name = stat_names.get(code) if stat_names is not None else None
    stat = name if name else f"stat #{code}"
    fraction = stat in FRACTION_STATS or (stat == "attack speed" and formula == 2)
    if stat == "health" and formula == 0:
        stat = "max health"
    return STAT_FORMULA.get(formula, f"formula{formula} ") + stat, fraction


def resource_words(res, formula):
    return STAT_FORMULA.get(formula, "") + ("max mana" if res == 0 else f"resource #{res}")


def term_label(key, coef, percent_calc, stat_names):
    """A reader's wording of one scaling term. This is the script's own wording, not the game's."""
    kind = key[0]
    fraction = False
    if kind == "stat":
        what, fraction = stat_words(key[1], key[2], stat_names)
    elif kind == "resource":
        what = resource_words(key[1], key[2])
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
    describe_values(out, ranks, per_rank, percent, decimals, ctx)
    return out


def describe_values(out, ranks, per_rank, percent, decimals, ctx):
    """Add ranks, base, level_range, scalings and display for per-rank values to out."""
    stat_names = ctx.stat_names
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
# Spell context: the gameplay side each record is checked against

# Calculation fields that name another calculation of the same spell, and fields that name a
# data value. Their values are also used to put names to calculations stored under a hash.
CALC_REF_FIELDS = ("mModifiedGameCalculation", "mDefaultGameCalculation", "mConditionalGameCalculation",
                   "mSpellCalculationKey")
NAME_FIELDS = CALC_REF_FIELDS + ("mDataValue", "DataValue", "StartDataValue", "EndDataValue")
STAT_PART_TYPES = ("StatByCoefficientCalculationPart", "StatByNamedDataValueCalculationPart",
                   "StatBySubPartCalculationPart")
# Part fields that name a data value, and the field the script adds beside one stored as a hash.
DATA_VALUE_NAME_FIELDS = {"mDataValue": "data_value_name", "DataValue": "data_value_name",
                          "StartDataValue": "start_data_value_name", "EndDataValue": "end_data_value_name"}
SPELL_STAT_NAMES = ("Cooldown", "Cost", "AmmoRechargeTime", "MaxAmmo", "CastRange")
EXTENDED_FIELDS = ("keyTooltipExtended", "keyTooltipExtendedBelowLine")


def spell_key(folder, path):
    """The id of one spell in the spells file. A path alone is not unique: a hashed path such as
    '{36b6a65c}' could appear in two champions' files."""
    return f"{folder}:{path}"


def script_of(spell):
    return (spell.script or spell.path.rsplit("/", 1)[-1]).lower()


def spell_name(spell):
    """A spell's script name as written, or the last part of its path."""
    return spell.script or spell.path.rsplit("/", 1)[-1]


def name_continues(name, seed_len):
    """Whether name, which begins with a slot spell's name seed_len long, ends there or goes on
    with a new word (an uppercase letter, a digit or an underscore): SionWDetonate and
    RellR_Damage go on from SionW and RellR, but GarenRunCycleManager does not go on from GarenR."""
    return len(name) == seed_len or name[seed_len].isupper() or name[seed_len].isdigit() or name[seed_len] == "_"


# Basic and critical attacks name each other (AatroxBasicAttack3's mAlternateName is
# AatroxBasicAttack2), so they take no part in linking.
ATTACK_RE = re.compile(r"basicattack|critattack", re.I)
# Script-name prefixes of spells that belong to a game mode, not to the champion's own kit:
# NightmareBot (Doom Bots, NightmareBotLuxQSplit in Lux's file), Odyssey (OdysseyAugments_SonaE
# in Sona's file) and Strawberry_ (Swarm, whose champions have folders of their own). These are
# the prefixes shared by spells of three or more champions in the saved patches 10.11 to 16.19.
# Such a spell joins no group by any rule and takes no part in linking; an AbilityObject that
# names one still groups it, as the game does.
GAME_MODE_PREFIXES = ("nightmarebot", "odyssey", "strawberry_")


def is_game_mode(spell):
    return spell_name(spell).lower().startswith(GAME_MODE_PREFIXES)


LINKED = "names or is named by a spell of the group"


def spell_links(ch, skip):
    """{lower-case path: set of lower-case paths}: two spells are linked when a string anywhere
    in one spell's entry names the other, by script name, path, ObjectName or the hash of its
    path (AatroxQ2's mClientData names Characters/Aatrox/Spells/AatroxQ in a field the export
    leaves hashed). Text keys, a spell's own name and mAlternateName are not read: mAlternateName
    often holds a name copied from another spell rather than a link (VladimirEMissile's is
    VladimirTransfusionHeal, his Q, in 11.7). Spells in skip take no part."""
    by_name = {}
    for p, sp in ch.spells_lc.items():
        for n in (sp.script, p.rsplit("/", 1)[-1], sp.obj.get("ObjectName") or "", p, fnv1a(p)):
            if n:
                by_name.setdefault(n.lower(), p)

    def strings(obj, key=None):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k not in ("mScriptName", "mLocKeys", "mAlternateName", "__type"):
                    yield from strings(v, k)
        elif isinstance(obj, list):
            for v in obj:
                yield from strings(v, key)
        elif isinstance(obj, str):
            yield obj

    links = {}
    for p, sp in ch.spells_lc.items():
        if p in skip:
            continue
        for v in strings(sp.obj):
            t = by_name.get(v.lower())
            if t and t != p and t not in skip:
                links.setdefault(p, set()).add(t)
                links.setdefault(t, set()).add(p)
    return links


def spell_groups(ch, later=None):
    """{lower-case spell path: (group id, source, seed path, [lower-case member paths], joined_by)}.

    A spell named by an AbilityObject (its mRootSpell or one of its mChildSpells) is grouped
    with that object's other spells; this is the game's own grouping (source 'AbilityObject').
    Champions gained AbilityObjects between 11.1 and 12.6 (Corki in 11.23, Orianna in 12.6), and
    before that most have none (Sion in 10.12 has one for R only), so each P, Q, W, E or R spell
    no AbilityObject names starts a group (source 'slot spell'; the seed path is that spell, and
    None for an AbilityObject group). A spell no AbilityObject names joins one, as joined_by
    records, in this order:
      1. 'script-name prefix': the slot spell's script name begins its own and the next letter
         starts a new word (uppercase, a digit or '_'), the longest such name winning.
         SionWDetonate, SionWPassive and SionWSoundExplosion join SionW; GarenRunCycleManager
         does not join GarenR (nor, by this rule, does AkaliEb join AkaliE).
      2. 'AbilityObject in <patch>': later maps a lower-case script name to (the lower-case
         script name of the root spell of the AbilityObject naming it, the patch), from the
         first later patch whose AbilityObjects have that slot spell as a root (see
         later_ability_groups); the spell joins the slot spell with that root's script name.
         Corki's GGSpray is linked to GGun by nothing in 11.7, but 11.23 puts it in GGun's
         ability, and 12.6 puts OrianaRedact in the ability of OrianaRedactCommand, her E.
      3. LINKED: spells still in no group that are linked to each other (spell_links), taken
         together, join the one group their links reach; a set whose links reach two groups
         joins neither.
    Basic and critical attacks join only by rule 1, and game-mode spells (GAME_MODE_PREFIXES)
    by none, nor do they start a group. A spell matching none is in no group, and so is a slot
    spell nothing joins. Groups made by AbilityObjects are never changed."""
    members = {}
    group_of = {}
    joined = {}
    for p in ch.spells_lc:
        ab = ch.ability_of.get(p)
        if ab:
            members.setdefault(ab[0], ("AbilityObject", None, []))[2].append(p)
            group_of[p] = ab[0]
            joined[p] = "AbilityObject"
    in_objects = set(group_of)
    seeds = slot_seeds(ch)

    def join(p, seed, how):
        gid = f"script name {ch.spells_lc[seed].script or spell_name(ch.spells_lc[seed])}"
        members.setdefault(gid, ("slot spell", seed, []))[2].append(p)
        group_of[p] = gid
        joined[p] = how

    game_mode = {p for p, sp in ch.spells_lc.items() if p not in in_objects and is_game_mode(sp)}
    seeds = [(n, seed) for n, seed in seeds if seed not in game_mode]
    for _, seed in seeds:
        if seed not in group_of:
            join(seed, seed, "slot spell")
    for p, sp in ch.spells_lc.items():
        if p in group_of or p in game_mode:
            continue
        name = spell_name(sp)
        for seed_name, seed in seeds:
            if seed_name and name.lower().startswith(seed_name.lower()) and name_continues(name, len(seed_name)):
                join(p, seed, "script-name prefix")
                break
    if later:
        seed_by_name = {}
        for seed_name, seed in seeds:
            seed_by_name.setdefault(seed_name.lower(), seed)
        for p, sp in ch.spells_lc.items():
            root, where = later.get(spell_name(sp).lower(), (None, None))
            if (p not in group_of and p not in game_mode and root in seed_by_name
                    and not ATTACK_RE.search(spell_name(sp))):
                join(p, seed_by_name[root], f"AbilityObject in {where}")
    skip = in_objects | game_mode | {p for p, sp in ch.spells_lc.items() if ATTACK_RE.search(spell_name(sp))}
    links = spell_links(ch, skip)
    # Spells in no group, linked to each other, form a set; the set joins the one group its
    # members' links reach. Grouped spells end a set, so two groups never merge through one.
    seen = set()
    for start in links:
        if start in seen or start in group_of:
            continue
        comp, todo, gids = [], [start], set()
        seen.add(start)
        while todo:
            p = todo.pop()
            comp.append(p)
            for q in links.get(p, ()):
                if q in group_of:
                    gids.add(group_of[q])
                elif q not in seen:
                    seen.add(q)
                    todo.append(q)
        if len(gids) == 1:
            seed = members[gids.pop()][1]
            for p in sorted(comp):
                join(p, seed, LINKED)
    return {p: (gid, members[gid][0], members[gid][1], members[gid][2], joined[p])
            for p, gid in group_of.items() if len(members[gid][2]) > 1}


def patch_key(name):
    return tuple(int(x) for x in re.findall(r"\d+", name))


_ABILITY_MAPS = {}
_PATCH_LISTS = {}


def ability_map(raw_root, patch, folder):
    """(complete, {lower-case root script name: [lower-case member script names]}) for one
    champion's AbilityObjects in one patch; complete when every P, Q, W, E and R spell is in one.
    Files with no AbilityObject (all exports before 11.1 name no classes) are not parsed.
    Cached for the run."""
    key = (str(raw_root), patch, folder)
    if key not in _ABILITY_MAPS:
        result = (False, {})
        f = raw_root / patch / "game/data/characters" / folder / f"{folder}.bin.json"
        if f.exists():
            text = f.read_text(encoding="utf-8")
            if '"AbilityObject"' in text or fnv1a("AbilityObject") in text:
                data = load_champion_data(f)[0]
                ch = Champion(folder, data) if data is not None else None
                if ch is not None and ch.ability_of:
                    roots = {}
                    for path, (_, root) in ch.ability_of.items():
                        sp, rs = ch.spells_lc.get(path), ch.spells_lc.get(root) if root else None
                        if sp is not None and rs is not None:
                            roots.setdefault(spell_name(rs).lower(), []).append(spell_name(sp).lower())
                    complete = all(p in ch.ability_of for p, slot in ch.slots.items()
                                   if slot in PQWER_SLOTS and p in ch.spells_lc)
                    result = (complete, roots)
        _ABILITY_MAPS[key] = result
    return _ABILITY_MAPS[key]


def later_ability_groups(raw_root, patch, folder, seed_names):
    """{lower-case script name: (lower-case root script name, patch)}, for spell_groups' rule 2.
    For each slot spell name in seed_names, the first later patch under raw_root in which an
    AbilityObject has a root spell of that script name gives that object's members. The search
    stops at the first patch in which every slot spell of the champion is in an AbilityObject
    (11.23 for Corki, 12.6 for Orianna), since a name not found by then is not coming back."""
    root = str(raw_root)
    if root not in _PATCH_LISTS:
        _PATCH_LISTS[root] = sorted((p.name for p in raw_root.iterdir() if (p / "manifest.json").exists()),
                                    key=patch_key) if raw_root.is_dir() else []
    out = {}
    todo = {n.lower() for n in seed_names}
    for later in _PATCH_LISTS[root]:
        if not todo:
            break
        if patch_key(later) <= patch_key(patch):
            continue
        complete, roots = ability_map(raw_root, later, folder)
        for name in sorted(todo & set(roots)):
            for member in roots[name]:
                out.setdefault(member, (name, later))
            todo.discard(name)
        if complete:
            break
    return out


def slot_seeds(ch):
    """[(script name, lower-case path)] of the P, Q, W, E and R spells no AbilityObject names,
    longest name first."""
    return sorted(((spell_name(ch.spells_lc[p]), p) for p, slot in ch.slots.items()
                   if slot in PQWER_SLOTS and p in ch.spells_lc and p not in ch.ability_of),
                  key=lambda x: -len(x[0]))


def raw_entry(obj):
    """A bin object as written, floats rounded, so a reader sees the game's own field names."""
    if isinstance(obj, dict):
        return {k: raw_entry(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [raw_entry(v) for v in obj]
    return clean(obj)


def part_entry(p, stat_names, dv_name=None):
    """One calculation part as written, plus 'stat' (the stat it reads, with the class defaults
    the export leaves out filled in), 'effect' (the EffectNAmount it reads) and, where a data
    value is named only by its hash ({"mDataValue": "{03da00f9}"} in 10.20), the name whose hash
    it is, in 'data_value_name' (or 'start_data_value_name' and 'end_data_value_name'). dv_name
    gives that name for (hash, part), or None when no name the script knows has that hash; the
    field is then left out."""
    if not isinstance(p, dict):
        return raw_entry(p)
    out = {}
    for k, v in p.items():
        if isinstance(v, dict) and "__type" in v:
            out[k] = part_entry(v, stat_names, dv_name)
        elif isinstance(v, list) and any(isinstance(x, dict) and "__type" in x for x in v):
            out[k] = [part_entry(x, stat_names, dv_name) for x in v]
        else:
            out[k] = raw_entry(v)
        if (k in DATA_VALUE_NAME_FIELDS and dv_name is not None and isinstance(v, str)
                and v.startswith("{") and (name := dv_name(v, p)) is not None):
            out[DATA_VALUE_NAME_FIELDS[k]] = name
    t = p.get("__type")
    if t in STAT_PART_TYPES:
        out["stat"] = stat_words(int(p.get("mStat", 0)), int(p.get("mStatFormula", 0)), stat_names)[0]
    elif t == "AbilityResourceByCoefficientCalculationPart":
        out["stat"] = resource_words(int(p.get("mAbilityResource", 0)), int(p.get("mStatFormula", 0)))
    elif t == "EffectValueCalculationPart":
        out["effect"] = f"Effect{int(p.get('mEffectIndex', 0))}Amount"
    return out


def names_in(obj, out):
    """Collect the strings obj gives in NAME_FIELDS (calculation and data value names)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in NAME_FIELDS and isinstance(v, str):
                out.add(v)
            else:
                names_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            names_in(v, out)
    return out


def calc_refs(ch, spell, name, depth=DEPTH):
    """Lower-case paths of the other spells a calculation reads (SourceObject), following the
    calculations it names."""
    found = set()

    def walk(obj, depth):
        if depth <= 0:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "SourceObject" and isinstance(v, str):
                    found.add(ch.entry_path(v))
                elif k in CALC_REF_FIELDS and isinstance(v, str):
                    walk(spell.lookup(spell.calcs, v), depth - 1)
                else:
                    walk(v, depth)
        elif isinstance(obj, list):
            for v in obj:
                walk(v, depth)

    walk(spell.lookup(spell.calcs, name), depth)
    found.discard(spell.path.lower())
    return found


def readable_dv_names(sp):
    """{hash: name} for the data values a spell declares under a readable name."""
    return {fnv1a(n): n for v in g(sp.m, "DataValues", "mDataValues", default=[]) or []
            if isinstance(n := g(v, "name", "mName"), str) and not n.startswith("{")}


def data_value_namer(ch, sp, known):
    """dv_name for part_entry: the name whose hash a part's data value is, looked up first among
    the data values of the spell the part reads (its SourceObject, else sp), then in known (every
    other name the script has seen in this champion and then in the patch)."""
    own = readable_dv_names(sp)

    def name(h, part):
        h = h.lower()
        src = part.get("SourceObject")
        if isinstance(src, str) and (other := ch.spells_lc.get(ch.entry_path(src))) is not None:
            found = readable_dv_names(other).get(h)
            if found:
                return found
        return own.get(h) or known.get(h)
    return name


def calc_result(ctx, name, ranks):
    """A calculation's value per rank, worked out as for a placeholder naming it."""
    per_rank = []
    percent, precision = False, None
    try:
        for rank in ranks:
            e, percent, precision, _ = ctx.calc_value(name, rank, DEPTH)
            if percent:
                e = Expr(e.const * 100, e.terms, None if e.level is None else [v * 100 for v in e.level])
            per_rank.append(e)
    except Unresolved as u:
        out = {"status": "unresolved", "reason": u.reason}
        if u.detail:
            out["detail"] = u.detail
        return out
    out = {"status": "resolved"}
    describe_values(out, ranks, per_rank, percent, precision if precision is not None else DEFAULT_DECIMALS, ctx)
    return out


def context_ranks(ch, path, sp, group):
    """(ranks, rank_source) for the spells file. As for records, except that a spell with no
    rank count of its own in a slot spell's group (see spell_groups) takes that spell's LevelUp count,
    so SionWDetonate's values in 10.12 are shown for SionW's 5 ranks, and a spell still left with
    one rank whose data varies is shown at indices 1 to 5 (Sona E in 10.22 has a LevelUp list
    with no levelCount, and its Effect4Amount is 10% to 14% over those indices). Records keep
    their own ranks."""
    ranks, source, _ = rank_info(ch, path, sp)
    one_rank = ("none (one rank)", "one rank, but data varies across indices 1 to 5")
    if group and group[2] and source in one_rank:
        n = level_count(ch.spells_lc[group[2]])
        if n is not None:
            return list(range(1, n + 1)), "slot spell's LevelUp list (its group)"
    if source == one_rank[1]:
        return [1, 2, 3, 4, 5], "no rank count, but data varies, so indices 1 to 5 are shown"
    return ranks, source


def values_by_rank(values, ranks):
    if not isinstance(values, list) or not values:
        return None
    return [None if (v := ranked(values, r)) is None else clean(v) for r in ranks]


def spell_context(ch, path, sp, keys, groups, stat_names, table, hash_names):
    """The gameplay side of one spell, one line of the spells file. Names are as in the bin;
    fields the script adds next to the game's own are lower-case words ('stat', 'effect',
    'data_value_name', 'known_name', 'reads', 'label', 'value', 'value_times_multiplier',
    'result', 'joined_by'). hash_names is {hash: name} for every name the script knows."""
    low = path.lower()
    group = groups.get(low)
    ranks, rank_source = context_ranks(ch, path, sp, group)
    ctx = Context(ch, sp, stat_names)
    m = sp.m
    out = {"key": keys[low], "spell_path": path, "script_name": sp.script or None, "slot": ch.slot(path),
           "ranks": ranks, "rank_source": rank_source}
    out["coefficients"] = {k: clean(v) for k, v in m.items()
                           if "coefficient" in k.lower() and isinstance(v, (int, float)) and not isinstance(v, bool)}
    # A data value declared with no numbers is null here; placeholders read it as 0.
    dvs = {}
    for v in g(m, "DataValues", "mDataValues", default=[]) or []:
        name = g(v, "name", "mName")
        if name is not None:
            dvs[name] = values_by_rank(g(v, "values", "mValues") or [], ranks)
    out["data_values"] = dvs
    out["effect_amounts"] = {f"Effect{i}Amount": vals for i, eff in enumerate(m.get("mEffectAmount") or [], 1)
                             if (vals := values_by_rank((eff or {}).get("value"), ranks)) is not None}
    stats = {}
    for name in SPELL_STAT_NAMES:
        try:
            stats[name] = [clean(spell_stat(sp, name.lower(), r)) for r in ranks]
        except Unresolved:
            pass
    out["spell_stats"] = stats
    calcs = {}
    refs = set()
    namer = data_value_namer(ch, sp, hash_names)
    for name, c in (m.get("mSpellCalculations") or {}).items():
        entry = {}
        if name.startswith("{") and name in hash_names:
            entry["known_name"] = hash_names[name]
        entry.update(part_entry(c, stat_names, namer) if isinstance(c, dict) else {"value": raw_entry(c)})
        entry["result"] = calc_result(ctx, name, ranks)
        calcs[name] = entry
        refs |= calc_refs(ch, sp, name)
    out["calculations"] = calcs
    td = (m.get("mClientData") or {}).get("mTooltipData") or {}
    lu = (td.get("mLists") or {}).get("LevelUp") or {}
    rows = []
    for el in g(lu, "Elements", "elements", default=[]) or []:
        if not isinstance(el, dict):
            continue
        row = {k: raw_entry(v) for k, v in el.items() if k != "__type"}
        t = el.get("type")
        if isinstance(t, str):
            reads = t.replace("%d", str(int(el.get("typeIndex", 0)))) if "%d" in t else t
            row["reads"] = reads
            res = resolve_placeholder(reads, ch, sp, ranks, stat_names)
            row["value"] = ({"display": res["display"]} if res["status"] == "resolved"
                            else {"status": res["status"], "reason": res.get("reason")})
            # 'value' is the raw number the row reads. The game shows it times the row's
            # multiplier (Sona E's movement speed 0.1 times 100 shows as 10).
            mult = el.get("multiplier")
            if res["status"] == "resolved" and isinstance(mult, (int, float)) and not isinstance(mult, bool):
                shown = resolve_placeholder(f"{reads}*{float(mult)!r}", ch, sp, ranks, stat_names)
                if shown["status"] == "resolved":
                    row["value_times_multiplier"] = {"display": shown["display"]}
        label = table.get(el["nameOverride"], tooltip_key=False) if isinstance(el.get("nameOverride"), str) else None
        if label is not None:
            row["label"] = label
        rows.append(row)
    out["level_up"] = {"levelCount": lu.get("levelCount"), "rows": rows} if lu else None
    if "EnableExtendedTooltip" in td:
        out["EnableExtendedTooltip"] = td["EnableExtendedTooltip"]
    out["group"] = None
    if group:
        out["group"] = {"id": group[0], "source": group[1], "joined_by": group[4],
                        "spells": [keys[p] for p in group[3] if p != low and p in keys]}
    out["refers_to"] = sorted(keys[p] for p in refs if p in keys)
    return out


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


def spells_path(out_root, patch, locale):
    return out_root / f"{patch}.{locale}.spells.jsonl"


class PatchFailed(Exception):
    """A patch that cannot be resolved at all (no manifest, or no readable text file)."""


def duplicate_targets(jobs):
    """{(spell path, lower-case text key): spell path it duplicates} for one champion.

    Two or more spells of a champion sometimes name the same text: MalzaharW and MalzaharWCancel
    share Spell_MalzaharW_Tooltip in 15.1, YorickE and NightmareBotYorickE share
    Spell_YorickE_Tooltip in 11.22, and Aurora's AuroraRMissile ('{36b6a65c}' in 15.16, stored
    under a hash) reuses Spell_AuroraR_Tooltip. The text belongs to the only spell naming it in
    slot P, Q, W, E or R (also when every spell naming it is stored under a hash, as for Samira
    in 10.20 and Rell in 10.25), or failing that to the only spell whose script name the key
    carries (Spell_<Script>_Tooltip...). Every other spell naming it is marked as its duplicate,
    so the text is checked once. A key with no such owner is left unmarked. The key-name rule
    at work: in 12.8 ZedW2 ('{e0c2427d}', W-form) and ZedR2 (R-form) share Spell_ZedW2_Tooltip,
    ZedW2 owns it by its script name, and ZedR2 is marked."""
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
            if p != owner:
                out[(p, key)] = owner
    return out


class PatchSource:
    """What one patch and language are resolved from: the fetch manifest, the text table, every
    champion's data and the patch-wide facts the champions share (the stat layout and the names
    known by hash). load_patch builds it from data/raw; resolve_champion reads it."""

    def __init__(self, patch, raw_root, locale, manifest, table, st_path, st_layout, champs,
                 sources=None, unreadable=None, jade_folders=None):
        self.patch = patch
        self.raw_root = raw_root
        self.locale = locale
        self.manifest = manifest
        self.table = table
        self.st_path = st_path
        self.st_layout = st_layout
        self.build = manifest.get("cdragon_version")
        self.champs = champs
        self.sources = sources if sources is not None else Counter()
        self.unreadable = unreadable if unreadable is not None else {}
        self.jade_folders = jade_folders if jade_folders is not None else []
        self.layout, self.stat_names, self.votes = detect_stat_layout(champs)
        # Every readable data value and calculation name in the patch, by hash: the last place a
        # hashed name in the spells file is looked up.
        self.patch_names = {}
        for ch in champs.values():
            for sp in ch.spells.values():
                self.patch_names.update(readable_dv_names(sp))
                self.patch_names.update({fnv1a(n): n for n in (sp.m.get("mSpellCalculations") or {})
                                         if not n.startswith("{")})


def load_patch(patch, raw_root, locale):
    """The PatchSource for one patch and language under raw_root (data/raw)."""
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
    return PatchSource(patch, raw_root, locale, manifest, table, st_path, st_layout, champs,
                       sources, unreadable, jade_folders)


class Tally:
    """The counts and lists the summary is built from, added to by resolve_champion."""

    def __init__(self):
        self.c = Counter()
        self.by_field = {}
        self.reasons = Counter()
        self.reasons_pqwer = Counter()
        self.by_kind = Counter()
        self.part_types = Counter()
        self.rank_sources = Counter()
        self.linked_keys = set()
        self.missing_keys = []
        self.jade_keys = []
        self.unpaired = []
        self.one_rank_varying = []
        self.examples = {}
        self.joined_by = Counter()


def resolve_champion(src, folder, ch, table=None, tally=None):
    """(records, spell lines) for one champion of src, in the order run_patch writes them. ch is
    a Champion, which may be built from a changed copy of the champion's data; table, when given,
    replaces src.table (any object with TextTable's get). tally, when given, is added to."""
    table = src.table if table is None else table
    t = Tally() if tally is None else tally
    c, by_field = t.c, t.by_field
    patch, locale, build, stat_names = src.patch, src.locale, src.build, src.stat_names
    records, lines = [], []
    jobs = text_jobs(ch)
    dup_of = duplicate_targets(jobs)
    seed_names = [n for n, _ in slot_seeds(ch)]
    groups = spell_groups(ch, later_ability_groups(src.raw_root, patch, folder, seed_names) if seed_names else None)
    keys = {p: spell_key(folder, s.path) for p, s in ch.spells_lc.items()}
    spells_by_low = dict(ch.spells_lc)
    for path, sp, _, _ in jobs:  # a passive with no spell gets a key of its own
        keys.setdefault(path.lower(), spell_key(folder, path))
        spells_by_low.setdefault(path.lower(), sp)
    context_of = []  # lower-case paths whose context is written, text spells first
    names = set()
    for path, sp, slot, keyed_fields in jobs:
        c["spells_with_tooltip_key"] += 1
        pqwer = slot in PQWER_SLOTS
        ranks, rank_source, varying = rank_info(ch, path, sp)
        spell_counted = False
        low = path.lower()
        context_of.append(low)
        group = groups.get(low)
        context_of += group[3] if group else []
        tooltip_data = (sp.m.get("mClientData") or {}).get("mTooltipData") or {}
        extended_hidden = tooltip_data.get("EnableExtendedTooltip") is False
        for field, key in keyed_fields:
            if not isinstance(key, str) or not key:
                continue
            fc = by_field.setdefault(field, Counter())
            if JADE_KEY_RE.search(key):
                t.jade_keys.append(key)
                continue
            text = table.get(key)
            if text is None:
                fc["key_missing_from_table"] += 1
                t.missing_keys.append(f"{field}: {key}")
                continue
            t.linked_keys.add(key.lower())
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
                t.rank_sources[rank_source] += 1
                if varying:
                    t.one_rank_varying.append(f"{path} ({', '.join(varying[:4])})")
            matches, stray = tokens_in(text)
            if stray:
                c["records_with_unpaired_at"] += 1
                t.unpaired.append(f"{path} {field}: {stray} unpaired @")
            phs = []
            referenced = set()
            for m in matches:
                r = resolve_placeholder(m.group(1), ch, sp, ranks, stat_names)
                r["start"], r["end"] = m.start(), m.end()
                phs.append(r)
                if r.get("name"):
                    names.add(r["name"])
                target = ch.by_script.get(r["owner_spell"].lower()) if r.get("owner_spell") else sp
                if target is not None and target is not sp:
                    referenced.add(target.path.lower())
                if target is not None and r.get("kind") == "calculation":
                    referenced |= calc_refs(ch, target, r["name"])
                if r["status"] == "ignored":
                    c["placeholders_ignored_ui"] += 1
                    continue
                c["placeholders"] += 1
                fc["placeholders"] += 1
                if duplicate:
                    c["placeholders_in_duplicates"] += 1
                    c["placeholders_resolved_in_duplicates"] += r["status"] == "resolved"
                t.by_kind[(r["kind"], r["status"])] += 1
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
                    t.reasons[r["reason"]] += 1
                    if pqwer:
                        t.reasons_pqwer[r["reason"]] += 1
                    t.examples.setdefault(r["reason"], f"{path} @{r['token']}@ {r.get('detail', '')}".strip())
            referenced.discard(low)
            context_of += sorted(referenced)
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
            rec["spell_context"] = keys[low]
            if referenced:
                rec["referenced_spells"] = sorted(keys[p] for p in referenced if p in keys)
            if extended_hidden and field in EXTENDED_FIELDS:
                # TooltipData's EnableExtendedTooltip is false: the game does not show this text.
                rec["extended_text_hidden_in_game"] = True
                c["records_extended_text_hidden"] += 1
            if varying:
                rec["varies_by_rank"] = varying
            if includes:
                rec["includes"] = includes
            if field == "passiveToolTip":
                rec["text_note"] = ("champion summary text from the champion record (the passive "
                                    "description shown in champion select), not an in-game tooltip")
            if stray:
                rec["unpaired_at_signs"] = stray
            records.append(rec)
    # The spells file: each text spell, the spells grouped with it and the spells its
    # records or calculations refer to, each written once.
    text_spells = {path.lower() for path, _, _, _ in jobs}
    for low in list(context_of):
        sp = ch.spells_lc.get(low) if low in text_spells else None
        for name in (sp.calcs if sp else {}):
            context_of += sorted(calc_refs(ch, sp, name))
    for sp in ch.spells.values():
        names_in(sp.m.get("mSpellCalculations"), names)
    hash_names = dict(src.patch_names)
    hash_names.update({fnv1a(n): n for n in names if not n.startswith("{")})
    for sp in ch.spells.values():
        hash_names.update(readable_dv_names(sp))
    for low in dict.fromkeys(context_of):
        if low not in spells_by_low:
            continue
        sp = spells_by_low[low]
        line = {"patch": patch, "locale": locale, "cdragon_version": build, "champion_folder": folder,
                "has_text": low in text_spells,
                **spell_context(ch, sp.path, sp, keys, groups, stat_names, table, hash_names)}
        c["spell_contexts"] += 1
        c["spell_contexts_without_text"] += low not in text_spells
        if line["group"]:
            c["spell_contexts_in_ability_object_group" if line["group"]["source"] == "AbilityObject"
              else "spell_contexts_in_slot_spell_group"] += 1
            t.joined_by[line["group"]["joined_by"]] += 1
        lines.append(line)
    # count part types used by calculations of every spell, for the summary
    for sp in ch.spells.values():
        for calc in (sp.m.get("mSpellCalculations") or {}).values():
            for pt in re.findall(r'"__type": "([^"]+)"', json.dumps(calc)):
                t.part_types[pt] += 1
    return records, lines


def run_patch(patch, raw_root, out_root, locale):
    src = load_patch(patch, raw_root, locale)
    raw = raw_root / patch
    manifest, table, st_path, st_layout, build = src.manifest, src.table, src.st_path, src.st_layout, src.build
    champs, sources, unreadable, jade_folders = src.champs, src.sources, src.unreadable, src.jade_folders
    layout, votes = src.layout, src.votes

    out_root.mkdir(parents=True, exist_ok=True)
    out_path, summary_path = output_paths(out_root, patch, locale)
    tmp = out_path.with_suffix(".jsonl.tmp")
    sp_path = spells_path(out_root, patch, locale)
    sp_tmp = sp_path.with_suffix(".jsonl.tmp")

    t = Tally()
    c, by_field, reasons, reasons_pqwer, by_kind, part_types = (t.c, t.by_field, t.reasons, t.reasons_pqwer,
                                                                t.by_kind, t.part_types)
    rank_sources, linked_keys, missing_keys, jade_keys = t.rank_sources, t.linked_keys, t.missing_keys, t.jade_keys
    unpaired, one_rank_varying, examples, joined_by = t.unpaired, t.one_rank_varying, t.examples, t.joined_by
    with tmp.open("w", encoding="utf-8") as fh, sp_tmp.open("w", encoding="utf-8") as sfh:
        for folder, ch in champs.items():
            records, lines = resolve_champion(src, folder, ch, tally=t)
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            for line in lines:
                sfh.write(json.dumps(line, ensure_ascii=False) + "\n")
    tmp.replace(out_path)
    sp_tmp.replace(sp_path)

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
        "spells_file": sp_path.name,
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
        "level_up_labels_found_only_by_hash": table.others_found_by_hash if table.readable else None,
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
        # How each spell line's spell joined its group (see spell_groups).
        "spell_contexts_joined_by": dict(joined_by.most_common()),
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
    # Lower-cased as fetch_cdragon.py does, so zh_CN finds the zh_cn folder fetch saved.
    ap.add_argument("--locale", default="en_us", type=str.lower)
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
            print(f"  {cnt['records_marked_duplicate']} texts are marked duplicate_of another spell that names the same text")
        print(f"  wrote {path}")
    if failed:
        sys.exit(f"{len(failed)} of {len(patches)} patches failed: {' '.join(failed)}")


if __name__ == "__main__":
    main()
