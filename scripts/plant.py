#!/usr/bin/env python3
"""Plant tooltip-calculation errors in a live patch's English tooltips by fixed rules.

A planted error makes a value that a placeholder of the record's text shows disagree with an
anchor: the same value shown elsewhere in the input. The changed value is one only that text's
shown values read. It is not always a value the game marks tooltip-only, since many shown
calculations are also used in play. Each error is made in its own copy of the champion's data or
of one tooltip's text. That champion is then resolved again by resolve_tooltips.py's own code
(resolve_champion) and the record's input is built again by inputs.py, so every value the input
shows is worked out by the same code as for the real data. Records come from the checked set.

No calculation, data value or section is added or renamed. drop_term removes one part of a
calculation's formula, and other_value renames one placeholder of the text; the other rules
only change numbers. A place in a record (a site) is used only when both of these hold:

  1. The field changed is read only by what the record's text shows: by a calculation a
     placeholder of the text shows, or by a calculation read only by such calculations (through
     its formula, or as the calculation it modifies, or its default or conditional one). No
     level-up row, other calculation or other spell reads it.
  2. In the original input the field agrees with an independent anchor elsewhere in the input,
     which the change leaves as it was, so the error shows as a disagreement, as real tooltip
     bugs do. An anchor is one of: a coefficient field of the spell or of another spell of its
     ability; a level-up row that reads a different field; a value of the same name, or the same
     per-rank values, in another spell of the ability; a matching part of another calculation;
     a number typed into the text. A value that is the same at every rank anchors only through a
     coefficient field, a value of the same name in another spell, a calculation part of a
     calculation with a related name, or (for a hit count) a typed number followed by a word such
     as "times", since a lone constant matches too much by chance. other_value's anchors are
     its own, listed under its rule below.

The rules (PLAN.md, "Planted errors"):

  stat_ratio   a stat ratio in a shown calculation, times a factor in RATIO_FACTORS: the
               coefficient itself, or the data value it reads
  base_values  the per-rank values of a data value a shown calculation or placeholder reads,
               times a factor in BASE_FACTORS, only a factor that keeps the list on its own step
               in GRID_STEPS (multiples of 5 stay multiples of 5)
  other_value  the first occurrence of one placeholder renamed to another calculation or data
               value of the same spell (a text edit). The target shows a value within a factor of
               0.25 to 4 of the original at every rank, never zero, with the same percent display
               and the same kinds of stat scaling, and has a readable name. Its name holds words
               of the same kinds of quantity (QUANTITY_WORDS) as the original's, or neither has
               any. The anchor is where the input still shows the original value: another
               placeholder showing it (only another occurrence of the same placeholder for a
               value that is the same at every rank), or, when the two show the same stat
               scalings, a value of the same name in another spell of the ability, or (for a
               value that differs by rank) a level-up row. A coefficient field or a typed number
               never anchors it, since it matches a constant by chance
  drop_term    one term (a base value or a stat ratio) left out of a shown calculation with two or
               more, only where the left-out value is anchored elsewhere and the result is not 0
               with no scaling. The kind of term (base value or stat ratio) is drawn first,
               uniformly among the kinds the record has, then the term
  multiplier   a multiplier in a shown calculation (its own, or a side of a product), never one
               in UNIT_MULTIPLIERS: a whole number plus a step in MULTIPLIER_STEPS, kept at 1 or
               more, any other number times a factor in MULTIPLIER_FACTORS

A factor is applied to every entry of a list at one precision: the fewest decimals, starting at
the list's own, at which the factor applies exactly, so the stated factor is what was applied and
rank order holds.

Each planted error passes the self-check in check() or is not written (and is counted). The
errors are split as equally as the count allows among the rules, and a rule that runs out of
eligible records gives the rest of its share equally to the others; the manifest records each
such move. --max-share caps each rule at that share of its eligible abilities (rounded
down), and the rest of its share moves to the others the same way. At most one error goes on an ability (a champion's ability group in the resolver's
spells file, or the spell when it has none), and at most one on each tooltip text within a
champion (spells with the same raw text). --exclude-manifest leaves out every ability that holds
an error of an existing manifest, so a test set never shares an ability with the development set. All random choices come from one random.Random(seed):
rules take turns drawing, each draw takes a record uniformly from the rule's eligible records not
yet drawn, then a site and a change size, uniformly.

Writes data/planted/<set>.jsonl, one planted error per line: id, rule, record_id,
original_input_id, change, answer (what the tooltip now shows and the anchor it disagrees with,
for the catch judge, naming every placeholder that now shows a different value) and input (the
planted input). Also writes a manifest (by default
data/planted/<set>.manifest.json; --manifest-out puts it elsewhere) that holds no tooltip text,
only names and numbers: the seed, patch, CommunityDragon build, counts, share cap, the code it was made by
(the project's git commit and the sha256 of plant.py, inputs.py and resolve_tooltips.py), and for
each error its record, ability, rule, change and the sha256 of its planted and original inputs (of
inputs.dumps), and the abilities left out. --verify <manifest> makes the set again from data/raw and checks every hash.

Examples (run from the project root):
  python3 scripts/plant.py --patch 16.18 --set dev --seed 1003 --counts tooltip_calc=125 --max-share 0.5
  python3 scripts/plant.py --verify data/planted/dev.manifest.json
"""

import argparse
import copy
import hashlib
import json
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inputs as I  # noqa: E402
import resolve_tooltips as R  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS.parent
DEFAULT_RAW = PROJECT_ROOT / "data" / "raw"
DEFAULT_OUT = PROJECT_ROOT / "data" / "planted"
ENGLISH = "en_us"
KIND = "tooltip_calc"
RULES = ("stat_ratio", "base_values", "other_value", "drop_term", "multiplier")
CODE_FILES = ("plant.py", "inputs.py", "resolve_tooltips.py")

# Sizes of the changes. Each is tried in a random order until one passes the self-check.
RATIO_FACTORS = (0.5, 0.75, 1.5, 2.0)
BASE_FACTORS = (0.75, 0.8, 1.2, 1.25)
MULTIPLIER_STEPS = (1, -1)
MULTIPLIER_FACTORS = (0.5, 1.5, 2.0)
# Multipliers that convert units (a fraction shown as a percent, milliseconds) or do nothing.
UNIT_MULTIPLIERS = (0, 1, 100, 0.01, 1000, 0.001, -1)
OTHER_VALUE_RANGE = (0.25, 4.0)
# Steps a list of base values sits on, coarsest first. base_values keeps a changed list on its
# original's step, so multiples of 5 stay multiples of 5.
GRID_STEPS = (5, 1, 0.5, 0.1, 0.05, 0.01, 0.005, 0.001, 0.0005, 0.0001)
# Name pieces that mark a calculation or data value as junk or not in use.
JUNK_WORDS = {"ignore", "unused", "deprecated", "dummy", "debug", "test", "placeholder", "temp", "old",
              "tbd", "todo", "hack", "fix", "copy", "replaced"}
# Words too common in names to tie two values together.
GENERIC_WORDS = {"calc", "tooltip", "total", "damage", "base", "value", "amount", "final", "bonus", "per", "max", "min"}
# Kinds of quantity, by the words of a name. other_value points a placeholder only at a value
# whose name holds words of the same kinds, so the slip reads as one. "per" marks a rate.
QUANTITY_WORDS = {
    "time": {"duration", "time", "delay", "window", "seconds", "sec", "timer", "decay", "lockout", "linger"},
    "amount": {"damage", "dmg", "heal", "healing", "regen", "restore", "shield"},
    "speed": {"speed", "ms", "as", "haste"}, "slow": {"slow"},
    "ratio": {"ratio", "scaling", "coef", "coefficient", "ap", "ad", "percent", "pct"},
    "count": {"count", "stacks", "stack", "charges", "ammo", "hits", "bolts", "waves", "targets", "number",
              "tick", "ticks"},
    "rate": {"per"},
    "distance": {"range", "radius", "distance", "width", "length"},
    "resist": {"armor", "mr", "resist", "resistance", "reduction"},
    "cooldown": {"cooldown", "cd", "refund"}, "health": {"health", "hp"}, "mana": {"mana"}, "level": {"level"},
}
# Words after a typed number that make it a count of hits, so it can anchor a multiplier.
COUNT_WORDS = {"times", "more", "hits", "bolts", "waves", "attacks", "strikes", "missiles", "shots", "ticks",
               "pulses", "instances", "daggers", "blades", "feathers", "arrows"}
STAT_PARTS = ("StatByCoefficientCalculationPart", "StatByNamedDataValueCalculationPart")


class Skip(Exception):
    """A change that cannot carry the planted error."""


# ---------------------------------------------------------------------------------------
# Small helpers


def num(x):
    return R.clean(float(x))


def decimals(x):
    """Digits after the point of a game number, float32 noise left out (0.85000002 -> 2)."""
    s = repr(num(x))
    return 0 if "." not in s or s.endswith(".0") else len(s.split(".")[1])


def rounded(x, places):
    v = round(x, places)
    return int(v) if v == int(v) else v


def precision(values, places_min=0):
    """The decimals a list is written to: its own, at least places_min, and at least 2 for a list
    of fractions below 1 (shown as whole percents)."""
    nums = [num(v) for v in values if isinstance(v, (int, float))]
    fractions = nums and all(abs(v) < 1 for v in nums)
    return max([decimals(v) for v in nums] + [places_min, 2 if fractions else 0])


def scaled(values, factor, places_min=0):
    """values times factor, or None unless every product is exact at the list's own precision.
    So a whole number stays whole, the stated factor is what was applied, and rank order holds."""
    places = precision(values, places_min)
    nums = [num(v) for v in values if isinstance(v, (int, float))]
    if not all(abs(round(v * factor, places) - v * factor) < 1e-9 for v in nums):
        return None
    return [rounded(num(v) * factor, places) if isinstance(v, (int, float)) else v for v in values]


def changeable(values, factors, places_min=0):
    return any(scaled(values, f, places_min) not in (None, values) for f in factors)


def grid(values):
    """The coarsest step in GRID_STEPS that every value is a multiple of (5 for 50/75/100)."""
    nums = [num(v) for v in values if isinstance(v, (int, float))]
    return next((g for g in GRID_STEPS if all(abs(v / g - round(v / g)) < 1e-6 for v in nums)), None)


def base_factors(values):
    """The BASE_FACTORS whose changed list stays on the original list's grid."""
    g = grid(values)
    out = []
    for f in BASE_FACTORS:
        new = scaled(values, f)
        if new not in (None, values) and g is not None and all(abs(num(v) / g - round(num(v) / g)) < 1e-6 for v in new if isinstance(v, (int, float))):
            out.append(f)
    return out


def close(a, b):
    return a is not None and b is not None and abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def same(xs, ys):
    return len(xs) == len(ys) and all(close(a, b) for a, b in zip(xs, ys))


def varies(xs):
    return len({round(x, 9) for x in xs if x is not None}) > 1


def numbers_text(values):
    vals = [num(v) for v in values]
    return str(vals[0]) if not varies(vals) else "/".join(str(v) for v in vals)


def sha(inp):
    return hashlib.sha256(I.dumps(inp).encode("utf-8")).hexdigest()


def get_at(obj, path):
    for k in path:
        obj = obj[k]
    return obj


def walk_parts(parts, path):
    """(path, part) for each formula part, going into sums."""
    for i, p in enumerate(parts or []):
        yield path + [i], p
        if isinstance(p, dict) and p.get("__type") == "SumOfSubPartsCalculationPart":
            yield from walk_parts(p.get("mSubparts"), path + [i, "mSubparts"])


def all_parts(obj):
    """Every dict below obj (a calculation), the calculation itself left out."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k != "result":
                if isinstance(v, dict):
                    yield v
                yield from all_parts(v)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict):
                yield v
            yield from all_parts(v)


def calc_key(m, name):
    for k in m.get("mSpellCalculations") or {}:
        if k.lower() == name.lower():
            return k
    return None


def dv_entry(m, name):
    for k in ("DataValues", "mDataValues"):
        for v in m.get(k) or []:
            if str(R.g(v, "name", "mName") or "").lower() == str(name).lower():
                return v
    return None


def dv_values(v):
    return R.g(v, "values", "mValues") or []


def set_dv_values(v, values):
    v["values" if "values" in v else "mValues"] = values


def at_ranks(values, ranks):
    return [R.ranked(values, r) for r in ranks]


def shape(obj, path=()):
    """Every key path of obj, with each list's length: the self-check that a change is in place."""
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(path + (k,))
            out |= shape(v, path + (k,))
    elif isinstance(obj, list):
        out.add(path + (f"len={len(obj)}",))
        for i, v in enumerate(obj):
            out |= shape(v, path + (i,))
    return out


def words(name):
    return [w.lower() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", name or "")]


def quantities(name):
    ws = set(words(name))
    return {q for q, qw in QUANTITY_WORDS.items() if ws & qw}


def related(a, b):
    """Whether two names share a word that is not too common to count."""
    return bool((set(words(a)) & set(words(b))) - GENERIC_WORDS - {w for w in words(a) if len(w) < 3})


def readable(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) or "__" in name:
        return False
    return not any(w in JUNK_WORDS for w in words(name))


def rename_tokens(text, phs, new_name):
    """text with each placeholder in phs renamed, keeping its precision and factor."""
    for ph in sorted(phs, key=lambda p: -p["start"]):
        tok = ph["token"]
        text = text[:ph["start"]] + "@" + new_name + tok[len(ph["name"]):] + "@" + text[ph["end"]:]
    return text


class TextOverride:
    """A text table with some entries replaced."""

    def __init__(self, base, overrides):
        self.base = base
        self.overrides = {k.lower(): v for k, v in overrides.items()}

    def get(self, key, tooltip_key=True):
        if key.lower() in self.overrides:
            return self.overrides[key.lower()]
        return self.base.get(key, tooltip_key=tooltip_key)


# ---------------------------------------------------------------------------------------
# The patch: every champion resolved once, as the real inputs are


class Patch:
    def __init__(self, src):
        self.src = src
        self.base = {folder: R.resolve_champion(src, folder, ch) for folder, ch in src.champs.items()}
        self._inputs = {}

    @classmethod
    def load(cls, patch, raw_root):
        return cls(R.load_patch(patch, raw_root, ENGLISH))

    def lines_of(self, folder):
        return {ln["key"]: ln for ln in self.base[folder][1]}

    def records(self):
        for folder, (recs, _) in self.base.items():
            for rec in recs:
                if I.is_checked(rec) and rec["spell_path"] in self.src.champs[folder].spells:
                    yield folder, rec

    def original_input(self, folder, rec):
        key = I.record_id(rec)
        if key not in self._inputs:
            self._inputs[key] = I.build_input(rec, self.lines_of(folder))
        return self._inputs[key]


class Ctx:
    """One record with what the sites and anchors need: its raw spell, its spell lines and the
    calculations its text shows."""

    def __init__(self, p, folder, rec, lines=None):
        self.p, self.folder, self.rec = p, folder, rec
        self.ranks = rec["ranks"]
        self.sp = p.src.champs[folder].spells[rec["spell_path"]]
        self.lines = p.lines_of(folder) if lines is None else lines
        self.key = rec["spell_context"]
        self.line = self.lines.get(self.key) or {}
        own = [ph for ph in rec.get("placeholders") or [] if not ph.get("owner_spell")
               and ph.get("status") == "resolved"]
        self.placeholders = own
        self.shown = {ph["name"].lower() for ph in own if ph.get("kind") == "calculation"}
        others = list((self.line.get("group") or {}).get("spells") or []) + list(rec.get("referenced_spells") or []) \
            + list(self.line.get("refers_to") or [])
        self.others = [k for k in dict.fromkeys(others) if k != self.key and k in self.lines]
        self.calcs = self.line.get("calculations") or {}
        self._refs = {n.lower(): self.names_read(c) for n, c in self.calcs.items()}

    @staticmethod
    def names_read(calc):
        """Lower-case names calc reads, its own top-level fields included (a calculation it
        modifies, or its default and conditional calculations)."""
        out = set()
        for part in [calc, *all_parts(calc)] if isinstance(calc, dict) else all_parts(calc):
            for k, v in part.items():
                if isinstance(v, str) and (k in R.NAME_FIELDS or k.endswith("data_value_name")):
                    out.add(v.lower())
        return out

    def readers(self, name):
        """Lower-case names of the own spell's calculations that read name."""
        low, h = name.lower(), R.fnv1a(name)
        return {c for c, refs in self._refs.items() if c != low and (low in refs or h in refs)}

    def tooltip_side(self, calc, seen=()):
        """A calculation the text shows, or one read only by such calculations."""
        calc = calc.lower()
        if calc in self.shown:
            return True
        rs = self.readers(calc) - set(seen)
        return bool(rs) and all(self.tooltip_side(r, seen + (calc,)) for r in rs)

    def read_elsewhere(self, name):
        """Whether a level-up row or another spell reads name."""
        rows = (self.line.get("level_up") or {}).get("rows") or []
        if any(str(r.get("reads") or "").lower() == name.lower() for r in rows):
            return True
        for k, ln in self.lines.items():
            if k != self.key and self.key in (ln.get("refers_to") or []):
                if any(name.lower() in self.names_read(c) for c in (ln.get("calculations") or {}).values()):
                    return True
        return False

    def field_ok(self, name, calc=None):
        """Rule 1 for a data value name (calc None) or a field inside calculation calc."""
        if calc is not None:
            return self.tooltip_side(calc) and all(self.tooltip_side(r) for r in self.readers(calc)) \
                and not self.read_elsewhere(calc)
        rs = self.readers(name)
        return bool(rs) and all(self.tooltip_side(r) for r in rs) and not self.read_elsewhere(name) \
            or (not rs and name.lower() in {ph["name"].lower() for ph in self.placeholders}
                and not self.read_elsewhere(name))

    def line_values(self, ln, values):
        """A spell line's list at the record's ranks, or None."""
        if not isinstance(values, list):
            return None
        pos = {r: i for i, r in enumerate(ln.get("ranks") or [])}
        if len(values) != len(pos) or any(r not in pos for r in self.ranks):
            return None
        out = [values[pos[r]] for r in self.ranks]
        return out if all(isinstance(v, (int, float)) for v in out) else None

    def raw_dv(self, name):
        return dv_entry(self.sp.m, name)


# ---------------------------------------------------------------------------------------
# Anchors


def spell_name(ln):
    return ln.get("script_name") or ln["spell_path"].rsplit("/", 1)[-1]


def row_values(cx, ln, row):
    out = []
    for field in ("value", "value_times_multiplier"):
        disp = (row.get(field) or {}).get("display")
        try:
            vals = [float(x) for x in disp] if disp else None
        except (TypeError, ValueError):
            vals = None
        if vals is not None:
            out.append(cx.line_values(ln, vals))
    return [v for v in out if v]


def typed_after(text, end):
    m = re.match(r"\s*([A-Za-z]+)", re.sub(r"<[^>]*>", " ", text[end:end + 40]))
    return m.group(1).lower() if m else None


def anchors(cx, values, kind, name=None, changed=(), calc=None, stat=None):
    """The independent anchors in the original input that agree with values (the field's values
    at the record's ranks). kind is 'ratio', 'value' or 'multiplier'; name is the field's own
    data value name (for a value of the same name in another spell); changed holds lower-case
    names whose readers would change with the field, so they are no anchor; calc is the
    calculation the change is in, whose own parts are no anchor; stat is a ratio's stat."""
    if not values or any(v is None for v in values):
        return []
    const = not varies(values)
    out = []
    lines = [(cx.key, cx.line)] + [(k, cx.lines[k]) for k in cx.others]
    for k, ln in lines:
        own = k == cx.key
        who = spell_name(ln)
        if kind == "ratio":
            for cname, v in (ln.get("coefficients") or {}).items():
                if const and close(float(v), values[0]):
                    out.append({"type": "coefficient", "spell": who, "name": cname, "values": values})
        for row in (ln.get("level_up") or {}).get("rows") or []:
            reads = str(row.get("reads") or "")
            if reads.lower() in changed or const:
                continue
            if any(same(vals, values) for vals in row_values(cx, ln, row)):
                out.append({"type": "level_up", "spell": who, "name": reads, "label": row.get("label"),
                            "values": values})
        if not own:
            for section in ("data_values", "effect_amounts"):
                for dname, vals in (ln.get(section) or {}).items():
                    vals = cx.line_values(ln, vals)
                    named = name is not None and dname.lower() == name.lower()
                    if vals and same(vals, values) and (named or not const):
                        out.append({"type": "same_name" if named else "same_values", "spell": who, "name": dname,
                                    "values": values})
        for cname, c in (ln.get("calculations") or {}).items():
            if own and (cname.lower() == (calc or "").lower() or cname.lower() in changed):
                continue
            for part in all_parts(c):
                t = part.get("__type")
                dvn = part.get("mDataValue")
                if dvn and own and dvn.lower() in changed:
                    continue
                dvv = cx.line_values(ln, (ln.get("data_values") or {}).get(dvn)) if dvn else None
                hit = False
                if kind == "ratio" and t in STAT_PARTS and part.get("stat") == stat:
                    hit = (const and close(float(part.get("mCoefficient", 0) or 0), values[0])
                           if t == STAT_PARTS[0] else bool(dvv) and same(dvv, values))
                elif kind == "value" and t == "NamedDataValueCalculationPart" and dvv:
                    hit = same(dvv, values) and (not const or (name is not None and dvn.lower() == name.lower()))
                elif kind == "multiplier" and t == "NumberCalculationPart" and const:
                    n = num(part.get("mNumber", 0))
                    hit = n not in UNIT_MULTIPLIERS and close(n, values[0]) and c.get("mMultiplier") is part
                elif kind == "multiplier" and t == "NamedDataValueCalculationPart" and dvv:
                    hit = same(dvv, values) and c.get("mMultiplier") is part
                if hit and (not const or related(cname, calc or name or "") or (dvn and name and dvn.lower() == name.lower())):
                    out.append({"type": "calculation", "spell": who, "name": cname, "values": values})
                    break
    if const and kind == "multiplier" and float(values[0]).is_integer() and values[0] >= 2:
        for n in cx.rec.get("typed_numbers") or []:
            if close(n["value"], values[0]) and re.fullmatch(r"\d+", n["text"].strip()) \
                    and typed_after(cx.rec["raw_text"], n["end"]) in COUNT_WORDS:
                out.append({"type": "typed_number", "start": n["start"], "values": values})
    return out


def anchor_words(a):
    vals = numbers_text(a["values"])
    if a["type"] == "coefficient":
        return f"the coefficient {a['name']} of {a['spell']} ({vals})"
    if a["type"] == "level_up":
        label = f" \"{a['label']}\"" if a.get("label") else ""
        return f"the level-up row{label} of {a['spell']}, which reads {a['name']} ({vals})"
    if a["type"] in ("same_name", "same_values"):
        return f"{a['name']} of {a['spell']}, another spell of the ability ({vals})"
    if a["type"] == "calculation":
        return f"the calculation {a['name']} of {a['spell']}, which uses the same value ({vals})"
    if a["type"] == "typed_number":
        return f"the number {vals} typed into the text"
    if a["type"] == "placeholder":
        shown = a["display"][0] if len(set(a["display"])) == 1 else "/".join(a["display"])
        return f"@{a['name']}@, which still shows {shown} in the text"
    return f"{a['name']} ({vals})"


def same_anchor(a, b):
    return {k: v for k, v in a.items() if k != "values"} == {k: v for k, v in b.items() if k != "values"}


# ---------------------------------------------------------------------------------------
# Sites: where each rule can make its change in a record (eligibility)


def shown_calcs(cx):
    """(placeholder, raw calculation key, raw calculation) for each own-spell calculation the
    text shows, once each, where rule 1 holds for the calculation's own fields."""
    seen = set()
    for ph in cx.placeholders:
        if ph.get("kind") != "calculation":
            continue
        key = calc_key(cx.sp.m, ph["name"])
        if key is None or key.lower() in seen:
            continue
        seen.add(key.lower())
        c = cx.sp.m["mSpellCalculations"][key]
        if isinstance(c, dict) and cx.field_ok(key, calc=key):
            yield ph, key, c


def line_part(cx, key, path):
    try:
        return get_at(cx.calcs[key], path)
    except (KeyError, IndexError, TypeError):
        return {}


def changed_by(cx, name):
    """Lower-case names that change with data value name: it and the calculations reading it."""
    out, todo = {name.lower()}, [name]
    while todo:
        for r in cx.readers(todo.pop()):
            if r not in out:
                out.add(r)
                todo.append(r)
    return out


def dv_site(cx, dvname, kind, **kw):
    """(values, anchors) for a data value the change goes into, or None."""
    dv = cx.raw_dv(dvname)
    if dv is None or not cx.field_ok(dvname):
        return None
    vals = at_ranks(dv_values(dv), cx.ranks)
    if any(v is None for v in vals) or all(v == 0 for v in vals) or not (
            changeable(dv_values(dv), RATIO_FACTORS, 2) if kind == "ratio" else base_factors(dv_values(dv))):
        return None
    found = anchors(cx, vals, kind, name=dvname, changed=changed_by(cx, dvname), **kw)
    return (vals, found) if found else None


def sites_stat_ratio(cx):
    out = []
    for ph, key, c in shown_calcs(cx):
        for path, part in walk_parts(c.get("mFormulaParts"), ["mFormulaParts"]):
            t = part.get("__type") if isinstance(part, dict) else None
            stat = line_part(cx, key, path).get("stat")
            if t == STAT_PARTS[0] and float(part.get("mCoefficient", 0) or 0) != 0 and changeable(
                    [num(part["mCoefficient"])], RATIO_FACTORS, 2):
                coef = num(part["mCoefficient"])
                found = anchors(cx, [coef] * len(cx.ranks), "ratio", changed={key.lower()} | changed_by(cx, key),
                                calc=key, stat=stat)
                if found:
                    out.append({"kind": "ratio", "token": ph["name"], "calc": key, "part": path, "stat": stat,
                                "anchors": found})
            elif t == STAT_PARTS[1]:
                dvn = part.get("mDataValue", "")
                got = dv_site(cx, dvn, "ratio", calc=key, stat=stat)
                if got:
                    found = got[1]
                    out.append({"kind": "ratio", "token": ph["name"], "calc": key, "part": path, "dv": dvn,
                                "stat": stat, "anchors": found})
    return out


def sites_base_values(cx):
    out, seen = [], set()
    targets = []
    for ph, key, c in shown_calcs(cx):
        for path, part in walk_parts(c.get("mFormulaParts"), ["mFormulaParts"]):
            if isinstance(part, dict) and part.get("__type") == "NamedDataValueCalculationPart":
                targets.append((ph["name"], part.get("mDataValue", "")))
    targets += [(ph["name"], ph["name"]) for ph in cx.placeholders if ph.get("kind") == "data_value"]
    for token, dvn in targets:
        if dvn.lower() in seen:
            continue
        seen.add(dvn.lower())
        got = dv_site(cx, dvn, "value")
        if got:
            out.append({"kind": "value", "token": token, "dv": dvn, "anchors": got[1]})
    return out


def comparable(ph, res):
    """Whether res (the resolved target of a renamed placeholder) passes other_value's tests."""
    if res.get("status") != "resolved" or res.get("kind") != ph.get("kind") or res.get("display") == ph.get("display"):
        return False
    if bool(res.get("display_as_percent")) != bool(ph.get("display_as_percent")):
        return False
    if bool(res.get("level_range")) != bool(ph.get("level_range")):
        return False
    a, b = ph.get("base") or [], res.get("base") or []
    if len(a) != len(b) or not a or any(not isinstance(x, (int, float)) for x in a + b) or varies(a) != varies(b):
        return False
    lo, hi = OTHER_VALUE_RANGE
    if any(y == 0 for y in b) or not any(x != 0 for x in a):
        return False
    if any(x != 0 and not lo <= y / x <= hi for x, y in zip(a, b)):
        return False
    sa = {s.get("stat") or s.get("label"): s.get("coefficient") for s in ph.get("scalings") or []}
    sb = {s.get("stat") or s.get("label"): s.get("coefficient") for s in res.get("scalings") or []}
    if set(sa) != set(sb):
        return False
    for st in sa:
        ca, cb = sa[st], sb[st]
        ca, cb = (ca if isinstance(ca, list) else [ca]), (cb if isinstance(cb, list) else [cb])
        if any(not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or x == 0 or not lo <= y / x <= hi
               for x, y in zip(ca, cb)):
            return False
    return True


def original_anchors(cx, ph, res):
    """Where the input still shows the original value of placeholder ph after its first
    occurrence is pointed at res: another placeholder showing the same value (for a value that is
    the same at every rank, only another occurrence of ph itself); or, when the two show the same
    stat scalings (so the base is what differs), a value of the same name in another spell of the
    ability, or a level-up row (anchors() gives one only for a value that differs by rank). No
    coefficient field or typed number: a coefficient is one number and a typed number matched
    only a constant, so both matched by chance (a coefficient of 1, the 5 of "per 5 seconds")."""
    out = [{"type": "placeholder", "name": q["name"], "values": ph["base"], "display": q["display"]}
           for q in cx.placeholders if q["start"] != ph["start"] and q.get("display") == ph.get("display")
           and (q["name"].lower() == ph["name"].lower() or varies(ph["base"]))][:1]
    if [s.get("label") for s in ph.get("scalings") or []] != [s.get("label") for s in res.get("scalings") or []]:
        return out
    vals = ph["base"]
    out += [a for a in anchors(cx, vals, "value", name=ph["name"]) if a["type"] in ("level_up", "same_name")]
    return out


def sites_other_value(cx):
    ch = cx.p.src.champs[cx.folder]
    used = {ph["name"].lower() for ph in cx.rec.get("placeholders") or [] if ph.get("name")}
    out, done = [], set()
    for ph in cx.placeholders:
        kind = ph.get("kind")
        if kind not in ("calculation", "data_value") or ph["name"].lower() in done:
            continue
        done.add(ph["name"].lower())
        names = (list(cx.sp.m.get("mSpellCalculations") or {}) if kind == "calculation"
                 else [R.g(v, "name", "mName") for v in cx.sp.m.get("DataValues") or cx.sp.m.get("mDataValues") or []])
        for name in names:
            if not readable(name) or name.lower() in used or quantities(name) != quantities(ph["name"]):
                continue
            res = R.resolve_placeholder(name + ph["token"][len(ph["name"]):], ch, cx.sp, cx.ranks, cx.p.src.stat_names)
            if comparable(ph, res):
                found = original_anchors(cx, ph, res)
                if found:
                    out.append({"kind": "value", "token": ph["name"], "target": name, "anchors": found})
    return out


def sites_drop_term(cx):
    out = []
    for ph, key, c in shown_calcs(cx):
        parts = c.get("mFormulaParts") or []
        if c.get("__type") != "GameCalculation" or len(parts) < 2:
            continue
        for i, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            t = part.get("__type")
            site = {"kind": "ratio" if t in STAT_PARTS else "value", "token": ph["name"], "calc": key,
                    "part": ["mFormulaParts", i], "stat": line_part(cx, key, ["mFormulaParts", i]).get("stat")}
            found = []
            if t == STAT_PARTS[0]:
                found = anchors(cx, [num(part.get("mCoefficient", 0) or 0)] * len(cx.ranks), "ratio",
                                changed={key.lower()}, calc=key, stat=site["stat"])
            elif t in (STAT_PARTS[1], "NamedDataValueCalculationPart"):
                site["dv"] = part.get("mDataValue", "")
                dv = cx.raw_dv(site["dv"])
                vals = at_ranks(dv_values(dv), cx.ranks) if dv else None
                if vals and None not in vals and not all(v == 0 for v in vals):
                    found = anchors(cx, vals, site["kind"], name=site["dv"], changed={key.lower()}, calc=key,
                                    stat=site["stat"])
            if found:
                out.append({**site, "anchors": found})
    return out


def sites_multiplier(cx):
    out = []
    for ph, key, c in shown_calcs(cx):
        places = []
        if c.get("__type") in ("GameCalculation", "GameCalculationModified") and "mMultiplier" in c:
            places.append(["mMultiplier"])
        if c.get("__type") == "GameCalculation":
            for path, part in walk_parts(c.get("mFormulaParts"), ["mFormulaParts"]):
                if isinstance(part, dict) and part.get("__type") == "ProductOfSubPartsCalculationPart":
                    places += [path + [side] for side in ("mPart1", "mPart2")]
        for path in places:
            part = get_at(c, path)
            t = part.get("__type") if isinstance(part, dict) else None
            if t == "NumberCalculationPart":
                n = num(part.get("mNumber", 0))
                if n in UNIT_MULTIPLIERS or n < 0 or not (float(n).is_integer() or changeable([n], MULTIPLIER_FACTORS, 2)):
                    continue
                found = anchors(cx, [n] * len(cx.ranks), "multiplier", changed={key.lower()} | changed_by(cx, key),
                                calc=key)
                if found:
                    out.append({"kind": "multiplier", "token": ph["name"], "calc": key, "part": path,
                                "anchors": found})
            elif t == "NamedDataValueCalculationPart":
                dvn = part.get("mDataValue", "")
                dv = cx.raw_dv(dvn)
                vals = at_ranks(dv_values(dv), cx.ranks) if dv else None
                if not vals or any(v is None or v <= 0 or num(v) in UNIT_MULTIPLIERS for v in vals):
                    continue
                if not all(float(v).is_integer() for v in vals) and not changeable(dv_values(dv), MULTIPLIER_FACTORS, 2):
                    continue
                if cx.field_ok(dvn):
                    found = anchors(cx, vals, "multiplier", name=dvn, changed=changed_by(cx, dvn), calc=key)
                    if found:
                        out.append({"kind": "multiplier", "token": ph["name"], "calc": key, "part": path, "dv": dvn,
                                    "anchors": found})
    return out


SITES = {"stat_ratio": sites_stat_ratio, "base_values": sites_base_values, "other_value": sites_other_value,
         "drop_term": sites_drop_term, "multiplier": sites_multiplier}


# ---------------------------------------------------------------------------------------
# Changes. Each yields a plan: the changed data (or None) and text, and the change made (names
# and numbers only).


def data_copy(cx):
    data = copy.deepcopy(cx.p.src.champs[cx.folder].data)
    return data, data[cx.rec["spell_path"]]["mSpell"]


def plan_scaled_dv(cx, site, factors, rng, places_min=0, **extra):
    for f in rng.sample(factors, len(factors)):
        data, m = data_copy(cx)
        dv = dv_entry(m, site["dv"])
        old = dv_values(dv)
        new = scaled(old, f, places_min)
        if new is None or new == old:
            continue
        set_dv_values(dv, new)
        yield {"data": data, "text": cx.rec["raw_text"], "change": {
            **extra, "data_value": site["dv"], "factor": f,
            "from": [num(x) for x in at_ranks(old, cx.ranks)], "to": [num(x) for x in at_ranks(new, cx.ranks)]}}


def plan_stat_ratio(cx, site, rng):
    where = {"calc": site["calc"], "part": site["part"], "stat": site["stat"]}
    if "dv" in site:
        yield from plan_scaled_dv(cx, site, RATIO_FACTORS, rng, 2, **where)
        return
    for f in rng.sample(RATIO_FACTORS, len(RATIO_FACTORS)):
        data, m = data_copy(cx)
        part = get_at(m["mSpellCalculations"][site["calc"]], site["part"])
        old = num(part["mCoefficient"])
        new = scaled([old], f, 2)
        if new is None:
            continue
        part["mCoefficient"] = new[0]
        yield {"data": data, "text": cx.rec["raw_text"],
               "change": {**where, "factor": f, "from": old, "to": new[0]}}


def plan_base_values(cx, site, rng):
    yield from plan_scaled_dv(cx, site, base_factors(dv_values(cx.raw_dv(site["dv"]))), rng)


def plan_other_value(cx, site, rng):
    first = [ph for ph in cx.placeholders if ph["name"].lower() == site["token"].lower()][:1]
    yield {"data": None, "text": rename_tokens(cx.rec["raw_text"], first, site["target"]), "renamed": True,
           "change": {"placeholder": site["token"], "points_at": site["target"], "start": first[0]["start"]}}


def plan_drop_term(cx, site, rng):
    data, m = data_copy(cx)
    parts = m["mSpellCalculations"][site["calc"]]["mFormulaParts"]
    i = site["part"][1]
    del parts[i]
    yield {"data": data, "text": cx.rec["raw_text"], "dropped": site["part"],
           "change": {"calc": site["calc"], "dropped_part": i}}


def plan_multiplier(cx, site, rng):
    where = {"calc": site["calc"], "part": site["part"]}
    m0 = cx.sp.m
    if "dv" in site:
        vals = [v for v in dv_values(dv_entry(m0, site["dv"])) if isinstance(v, (int, float))]
        if all(float(v).is_integer() for v in at_ranks(vals, cx.ranks)):
            for s in rng.sample(MULTIPLIER_STEPS, len(MULTIPLIER_STEPS)):
                data, m = data_copy(cx)
                dv = dv_entry(m, site["dv"])
                old = dv_values(dv)
                new = [int(num(v)) + s if isinstance(v, (int, float)) and v != 0 else v for v in old]
                if any(v < 1 for v in at_ranks(new, cx.ranks)):
                    continue
                set_dv_values(dv, new)
                yield {"data": data, "text": cx.rec["raw_text"], "change": {
                    **where, "data_value": site["dv"], "step": s,
                    "from": [num(x) for x in at_ranks(old, cx.ranks)], "to": [num(x) for x in at_ranks(new, cx.ranks)]}}
        else:
            yield from plan_scaled_dv(cx, site, MULTIPLIER_FACTORS, rng, 2, **where)
        return
    n = num(get_at(m0["mSpellCalculations"][site["calc"]], site["part"])["mNumber"])
    if float(n).is_integer():
        options = [("step", s, int(n) + s) for s in MULTIPLIER_STEPS if int(n) + s >= 1]
    else:
        options = [("factor", f, (scaled([n], f, 2) or [None])[0]) for f in MULTIPLIER_FACTORS]
    for how, size, new in rng.sample(options, len(options)):
        if new is None or new <= 0 or new in UNIT_MULTIPLIERS:
            continue
        data, m = data_copy(cx)
        get_at(m["mSpellCalculations"][site["calc"]], site["part"])["mNumber"] = new
        yield {"data": data, "text": cx.rec["raw_text"], "change": {**where, how: size, "from": n, "to": new}}


PLANS = {"stat_ratio": plan_stat_ratio, "base_values": plan_base_values, "other_value": plan_other_value,
         "drop_term": plan_drop_term, "multiplier": plan_multiplier}


# ---------------------------------------------------------------------------------------
# Making one planted error, and its self-check


def plant_one(p, folder, rec, plan):
    """(planted input, planted record, planted lines): the champion resolved again from the
    changed copy of its data and text, and the record's input built again."""
    src = p.src
    ch = R.Champion(folder, plan["data"]) if plan["data"] is not None else src.champs[folder]
    table = TextOverride(src.table, {rec["loc_key"]: plan["text"]})
    recs, lines = R.resolve_champion(src, folder, ch, table=table)
    new_rec = next((r for r in recs if I.is_checked(r) and r["spell_path"] == rec["spell_path"]
                    and r["text_field"] == rec["text_field"]), None)
    lines = {ln["key"]: ln for ln in lines}
    if new_rec is None:
        return None, None, lines
    return I.build_input(new_rec, lines), new_rec, lines


def by_name(phs, name):
    return [ph for ph in phs or [] if not ph.get("owner_spell") and (ph.get("name") or "").lower() == name.lower()]


def expected_shape(cx, plan):
    """The key paths the changed data must have: the original's, or for a left-out term the
    original's with that one formula list a part shorter."""
    data = cx.p.src.champs[cx.folder].data
    if plan.get("dropped"):
        data = copy.deepcopy(data)
        del data[cx.rec["spell_path"]]["mSpell"]["mSpellCalculations"][plan["change"]["calc"]]["mFormulaParts"][
            plan["change"]["dropped_part"]]
    return shape(data)


def check(cx, site, plan, new_rec, new_lines, inp, orig):
    """The self-check: what must hold for a planted error to be written. Returns failures."""
    fails = []
    if new_rec is None:
        return ["the planted record is missing after resolving again"]
    if new_rec["raw_text"] != plan["text"]:
        fails.append("the planted text is not the text the change made")
    if inp == orig or inp["id"] != orig["id"]:
        fails.append("the planted input does not differ from the original")
    if plan["data"] is not None and shape(plan["data"]) != expected_shape(cx, plan):
        fails.append("the change added, removed or renamed something")
    if plan["data"] is None and new_lines != cx.lines:
        fails.append("a text change changed the game data")
    # Nothing outside the record's own spell line changes, and in it no level-up row.
    for k, ln in cx.lines.items():
        if k != cx.key and new_lines.get(k) != ln:
            fails.append(f"spell line {k} changed")
    if (new_lines.get(cx.key) or {}).get("level_up") != cx.line.get("level_up"):
        fails.append("a level-up row changed")
    # The placeholder now shows a different value, never below 0 where it was not.
    name = plan["change"].get("points_at") or site["token"]
    new_ph = by_name(new_rec.get("placeholders"), name)
    old_ph = by_name(cx.rec.get("placeholders"), site["token"])
    if not new_ph or new_ph[0].get("status") != "resolved" or new_ph[0].get("display") == old_ph[0].get("display"):
        fails.append("the placeholder shows the same value as before, or none")
    else:
        nb, ob = new_ph[0].get("base") or [], old_ph[0].get("base") or []
        if any(isinstance(x, (int, float)) and x < 0 for x in nb) and not any(
                isinstance(x, (int, float)) and x < 0 for x in ob):
            fails.append("the planted value turned negative")
        if plan.get("dropped") and all(x == 0 for x in nb) and not new_ph[0].get("scalings"):
            fails.append("the left-out term leaves a value of 0")
    # The anchor is still there, as it was.
    new_cx = Ctx(cx.p, cx.folder, cx.rec, lines=new_lines)
    a = site["anchors"][0]
    if plan.get("renamed"):
        # The game data is unchanged (checked above), so only text anchors can be gone.
        if a["type"] == "placeholder" and not any(q.get("display") == a["display"] for q in by_name(
                new_rec.get("placeholders"), a["name"]) if q.get("status") == "resolved"):
            fails.append("the anchor is gone from the planted input")
        if a["type"] == "typed_number" and not any(close(float(t["value"]), a["values"][0])
                                                   for t in new_rec.get("typed_numbers") or []):
            fails.append("the anchor is gone from the planted input")
    elif not any(same_anchor(a, b) for b in anchors(new_cx, a["values"], site["kind"], name=site.get("dv"),
                                                    changed=set(), calc=site.get("calc"), stat=site.get("stat"))):
        fails.append("the anchor is gone from the planted input")
    return fails


def attempt(p, rule, folder, rec, sites, rng, failures):
    """The planted error for one drawn record, or None (failures counts why)."""
    cx = Ctx(p, folder, rec)
    orig = p.original_input(folder, rec)
    if rule == "drop_term":
        # The kind of term first (base value or stat ratio), uniformly among the record's kinds.
        kinds = sorted({s["kind"] for s in sites})
        order = [s for k in rng.sample(kinds, len(kinds)) for s in rng.sample(
            [s for s in sites if s["kind"] == k], sum(s["kind"] == k for s in sites))]
    else:
        order = rng.sample(sites, len(sites))
    for site in order:
        for plan in PLANS[rule](cx, site, rng):
            inp, new_rec, lines = plant_one(p, folder, rec, plan)
            fails = check(cx, site, plan, new_rec, lines, inp, orig)
            if fails:
                failures[fails[0]] += 1
                continue
            change = {**plan["change"], "anchor": {k: v for k, v in site["anchors"][0].items()
                                                   if k not in ("label", "display")}}
            return {"kind": KIND, "rule": rule, "locale": ENGLISH, "record_id": I.record_id(rec),
                    "original_input_id": orig["id"], "change": change,
                    "answer": answer(rule, cx, site, plan, new_rec, inp, orig), "input": inp,
                    "_sha": sha(inp), "_orig_sha": sha(orig)}
    failures["no change at any site passed the self-check"] += 1
    return None


# ---------------------------------------------------------------------------------------
# Answers: what a catch must name


def scaling_change(old_ph, new_ph):
    """How the stat scalings a placeholder shows changed, in the tooltip's own words."""
    def by_stat(ph):
        return {(sc.get("kind"), sc.get("stat"), sc.get("stat_formula")): sc.get("label")
                for sc in ph.get("scalings") or [] if sc.get("label")}
    old, new = by_stat(old_ph), by_stat(new_ph)
    out = [f"{old[k]} left out" if k not in new else f"{old[k]} became {new[k]}" for k in old if old[k] != new.get(k)]
    return ", ".join(out + [f"{new[k]} added" for k in new if k not in old])


def multiplier_note(cx, calc):
    """A sentence on the calculation's own multiplier, which the shown value includes."""
    part = (cx.calcs.get(calc) or {}).get("mMultiplier")
    if not isinstance(part, dict):
        return ""
    if part.get("__type") == "NumberCalculationPart":
        m = str(num(part.get("mNumber", 0)))
    elif part.get("mDataValue"):
        vals = cx.line_values(cx.line, (cx.line.get("data_values") or {}).get(part["mDataValue"]))
        m = f"{part['mDataValue']} ({numbers_text(vals)})" if vals else part["mDataValue"]
    else:
        return ""
    return f" The calculation {calc} multiplies its terms by {m}, and the values shown include it."


def answer(rule, cx, site, plan, new_rec, inp, orig):
    rec = cx.rec
    where = f"{rec['champion']} {rec['slot']} ({rec['text_field']})"
    ch = plan["change"]
    a = site["anchors"][0]
    name = ch.get("points_at") or site["token"]

    def base_name(token):
        return token.split("*")[0].split(".")[0]

    def shown(entries, nm):
        return next((e.get("value") for t, e in (entries or {}).items() if base_name(t).lower() == nm.lower()), None)

    new_ph, old_ph = by_name(new_rec["placeholders"], name)[0], by_name(rec["placeholders"], site["token"])[0]
    # Every placeholder of the text that now shows a different value, in text order.
    now, before = inp.get("placeholders") or {}, orig.get("placeholders") or {}
    changed = [t for t in now if t not in before or now[t].get("value") != before[t].get("value")]
    names = list(dict.fromkeys(base_name(t) for t in changed)) or [name]
    head = f"In {where}, " + "; ".join(
        f"@{n}@ shows {shown(now, n)} where the real tooltip shows "
        f"{shown(before, n) if shown(before, n) is not None else shown(before, site['token'])}" for n in names) + "."
    named = " or ".join(f"@{n}@" for n in names)
    catch = (f" A catch names {named} or the value it shows as wrong." if len(names) == 1
             else f" A catch names {named} or a value one of them shows as wrong.")
    note = multiplier_note(cx, ch["calc"]) if ch.get("calc") and rule != "multiplier" else ""

    def nums(x):
        return numbers_text(x if isinstance(x, list) else [x])
    if rule == "other_value":
        return (f"{head} The placeholder names {name}, another value of the same spell, where the real text names "
                f"{site['token']}, whose value the input still shows in {anchor_words(a)}.{catch}")
    if rule == "stat_ratio":
        field = f"the data value {ch['data_value']}" if ch.get("data_value") else f"the {ch['stat']} coefficient"
        return (f"{head} Its {ch['stat']} ratio, {field} of the calculation {ch['calc']}, was changed from "
                f"{nums(ch['from'])} to {nums(ch['to'])} ({scaling_change(old_ph, new_ph)}), and now disagrees with "
                f"{anchor_words(a)}.{note}{catch}")
    if rule == "base_values":
        return (f"{head} The data value {ch['data_value']} it reads was changed from {nums(ch['from'])} to "
                f"{nums(ch['to'])} (times {ch['factor']}), and now disagrees with {anchor_words(a)}.{catch}")
    if rule == "drop_term":
        ob, nb = old_ph.get("base") or [], new_ph.get("base") or []
        term = scaling_change(old_ph, new_ph) or f"a base of {numbers_text([x - y for x, y in zip(ob, nb)])} left out"
        return (f"{head} The calculation {ch['calc']} leaves out one term ({term}), whose value the input still "
                f"holds in {anchor_words(a)}.{note}{catch}")
    if rule == "multiplier":
        dv = f", the data value {ch['data_value']}," if ch.get("data_value") else ""
        return (f"{head} A multiplier of the calculation {ch['calc']}{dv} was changed from {nums(ch['from'])} to "
                f"{nums(ch['to'])}, and now disagrees with {anchor_words(a)}.{catch}")
    raise ValueError(rule)


# ---------------------------------------------------------------------------------------
# Drawing the set


def split(n, k):
    return [n // k + (1 if i < n % k else 0) for i in range(k)]


def eligible(p, rule):
    """[(folder, record, sites)] of the records a rule can be applied to, in a fixed order."""
    out = []
    for folder, rec in p.records():
        sites = SITES[rule](Ctx(p, folder, rec))
        if sites:
            out.append((folder, rec, sites))
    return sorted(out, key=lambda x: I.record_id(x[1]))


def ability_of(p, folder, rec):
    """[champion folder, ability]: the ability group of the resolver's spells file, or the spell
    itself when it has no group."""
    group = (p.lines_of(folder).get(rec["spell_context"]) or {}).get("group")
    return [folder, group["id"] if group else rec["spell_path"]]


def manifest_abilities(path):
    """The abilities of a manifest's errors, as tuples."""
    return {tuple(e["ability"]) for e in json.loads(Path(path).read_text(encoding="utf-8"))["errors"]}


def draw(p, count, seed, exclude=(), max_share=None):
    """(errors, report) for count errors split among the rules, none on an ability in exclude, and
    with max_share, no rule on more than that share of its eligible abilities."""
    rng = random.Random(seed)
    exclude = {tuple(a) for a in exclude}
    pools = {r: [x for x in eligible(p, r) if tuple(ability_of(p, x[0], x[1])) not in exclude] for r in RULES}
    abilities = {r: len({tuple(ability_of(p, f, rec)) for f, rec, _ in pools[r]}) for r in RULES}
    cap = {r: int(max_share * abilities[r]) if max_share is not None else count for r in RULES}
    need = dict(zip(RULES, split(count, len(RULES))))
    report = {"eligible_records": {r: len(pools[r]) for r in RULES},
              "eligible_spells": {r: len({(f, rec["spell_path"]) for f, rec, _ in pools[r]}) for r in RULES},
              "eligible_abilities": abilities, "cap": cap,
              "requested": dict(need), "reallocated": [], "failures": {r: Counter() for r in RULES}}
    done = Counter()
    used_abilities, used_texts = set(), set()
    errors = []
    while True:
        progressed = False
        for rule in RULES:
            pool = pools[rule]
            while done[rule] < min(need[rule], cap[rule]) and pool:
                folder, rec, sites = pool.pop(rng.randrange(len(pool)))
                ability = tuple(ability_of(p, folder, rec))
                if ability in used_abilities or (folder, rec["raw_text"]) in used_texts:
                    continue
                err = attempt(p, rule, folder, rec, sites, rng, report["failures"][rule])
                if err is not None:
                    err["_ability"] = list(ability)
                    used_abilities.add(ability)
                    used_texts.add((folder, rec["raw_text"]))
                    errors.append(err)
                    done[rule] += 1
                    progressed = True
                    break
        # A rule with no records left, or at its cap, gives the rest of its share equally to the
        # others that have records left and are below their caps.
        moved = False
        for rule in RULES:
            short = need[rule] - done[rule]
            others = [r for r in RULES if r != rule and pools[r] and done[r] < cap[r]]
            if short <= 0 or (pools[rule] and done[rule] < cap[rule]) or not others:
                continue
            need[rule] = done[rule]
            gift = dict(zip(others, split(short, len(others))))
            for r, n in gift.items():
                need[r] += n
            report["reallocated"].append({"from": rule, "count": short, "to": {r: n for r, n in gift.items() if n},
                                          "why": "cap" if done[rule] >= cap[rule] else "no records left"})
            moved = True
        if not progressed and not moved:
            break
    rng.shuffle(errors)
    report.update(planted={r: done[r] for r in RULES}, target=need)
    return errors, report


def code_info():
    try:
        commit = subprocess.run(["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {"git_commit": commit, "sha256": {f"scripts/{f}": hashlib.sha256((SCRIPTS / f).read_bytes()).hexdigest()
                                             for f in CODE_FILES}}


def manifest_of(errors, report, p, set_name, seed, count, exclude=(), max_share=None):
    entries = [{"id": f"{set_name}-{i:03d}", "rule": e["rule"], "record_id": e["record_id"], "ability": e["_ability"],
                "change": e["change"], "sha256": e["_sha"], "original_sha256": e["_orig_sha"]}
               for i, e in enumerate(errors, 1)]
    return {"set": set_name, "patch": p.src.patch, "cdragon_version": p.src.build, "seed": seed, "kind": KIND,
            "count_requested": count, "count": len(errors), "max_share": max_share,
            "excluded_abilities": sorted(list(a) for a in {tuple(a) for a in exclude}), "made_by": "scripts/plant.py", "code": code_info(),
            "counts": dict(Counter(e["rule"] for e in errors)), "eligible_records": report["eligible_records"],
            "eligible_spells": report["eligible_spells"], "eligible_abilities": report["eligible_abilities"],
            "cap": report["cap"], "reallocated": report["reallocated"],
            "not_written": {r: dict(c) for r, c in report["failures"].items() if c}, "errors": entries}


def write(errors, manifest, jsonl, manifest_path):
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    with jsonl.open("w", encoding="utf-8") as fh:
        for entry, e in zip(manifest["errors"], errors):
            row = {"id": entry["id"], **{k: v for k, v in e.items() if not k.startswith("_")}}
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def verify(manifest_path, raw_dir):
    """Failures, if the set made again from raw_dir does not match the manifest's hashes."""
    want = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    p = Patch.load(want["patch"], raw_dir)
    fails = []
    if p.src.build != want["cdragon_version"]:
        fails.append(f"build {p.src.build} is not the manifest's {want['cdragon_version']}")
    code = code_info()["sha256"]
    for f, h in want["code"]["sha256"].items():
        if code.get(f) != h:
            fails.append(f"{f} differs from the code the set was made by (hashes may differ)")
    exclude = want.get("excluded_abilities") or []
    share = want.get("max_share")
    errors, report = draw(p, want["count_requested"], want["seed"], exclude, share)
    got = manifest_of(errors, report, p, want["set"], want["seed"], want["count_requested"], exclude, share)
    if len(got["errors"]) != len(want["errors"]):
        fails.append(f"{len(got['errors'])} errors made again, the manifest has {len(want['errors'])}")
    for a, b in zip(want["errors"], got["errors"]):
        for k in ("record_id", "rule", "sha256", "original_sha256"):
            if a[k] != b[k]:
                fails.append(f"{a['id']}: {k} differs")
    return fails, len(want["errors"])


def parse_counts(s):
    out = {}
    for item in s.split(","):
        k, v = item.split("=")
        out[k.strip()] = int(v)
    if set(out) != {KIND}:
        raise argparse.ArgumentTypeError(f"only {KIND}=N is planted")
    return out[KIND]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch")
    ap.add_argument("--set", help="name of the set, such as dev")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--counts", type=parse_counts, help=f"{KIND}=N")
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest-out", type=Path, help="where to write the manifest (default: next to the set)")
    ap.add_argument("--exclude-manifest", type=Path, action="append", default=[], metavar="MANIFEST",
                    help="plant on no ability that holds an error of this manifest (may be given more than once)")
    ap.add_argument("--max-share", type=float, metavar="SHARE",
                    help="plant each rule on at most this share of its eligible abilities, such as 0.5")
    ap.add_argument("--verify", type=Path, metavar="MANIFEST", help="make the set again and check its hashes")
    args = ap.parse_args(argv)
    try:
        if args.verify:
            fails, n = verify(args.verify, args.raw_dir)
            for f in fails:
                print(f"  {f}")
            print(f"{args.verify}: {n} errors, {'all hashes match' if not fails else f'{len(fails)} problems'}")
            if fails:
                sys.exit(1)
            return
        if None in (args.patch, args.set, args.seed, args.counts):
            ap.error("--patch, --set, --seed and --counts are needed to plant")
        p = Patch.load(args.patch, args.raw_dir)
    except R.PatchFailed as e:
        sys.exit(str(e))
    exclude = set().union(*(manifest_abilities(m) for m in args.exclude_manifest))
    errors, report = draw(p, args.counts, args.seed, exclude, args.max_share)
    manifest = manifest_of(errors, report, p, args.set, args.seed, args.counts, exclude, args.max_share)
    jsonl = args.out_dir / f"{args.set}.jsonl"
    manifest_path = args.manifest_out or args.out_dir / f"{args.set}.manifest.json"
    write(errors, manifest, jsonl, manifest_path)
    print(f"{args.patch} {args.set}: {len(errors)} planted errors (seed {args.seed})")
    for r in RULES:
        print(f"  {r}: {report['planted'][r]} of {report['target'][r]} planted, {report['eligible_records'][r]} "
              f"eligible records ({report['eligible_spells'][r]} spells, {report['eligible_abilities'][r]} abilities, "
              f"cap {report['cap'][r]}), "
              f"{sum(report['failures'][r].values())} changes failed the self-check")
    for move in report["reallocated"]:
        print(f"  {move['from']} gave {move['count']} to {move['to']} ({move['why']})")
    print(f"  wrote {jsonl} and {manifest_path}")


if __name__ == "__main__":
    main()
