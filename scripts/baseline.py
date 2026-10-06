#!/usr/bin/env python3
"""The baseline: a plain script with two checks, run on the same inputs the model reads.

It reads inputs in the format inputs.py writes, from data/inputs/<patch>.<locale>.jsonl or from
a planted set (data/planted/<set>.jsonl, where each line holds its input under "input"), and
writes one flag per line. It is deterministic: no randomness and no model. It checks English
text only (PLAN.md, "Baseline"), so an input whose locale is not en_us gets no flags; the count
of those is printed.

Each flag holds:
  id          the input's id ('<patch>:<locale>:<champion_folder>:<spell_path>:<text_field>')
  planted_id  the planted error's id, when the input came from a planted set
  text_field, locale
  names       the value or claim the flag names, in words ('@NetDamageTooltip@ shows ...',
              'the typed number 3 in "3 seconds"')
  check       typed_number or tooltip_calc
  rule        which rule raised it (below); several are joined by '+'
  detail      a short reason
  placeholder the name of the placeholder the flag is about (tooltip_calc), when there is one
  value_name  the name of the calculation or data value the flag is about (tooltip_calc)
  start, end  the typed number's offsets into the input's text (typed_number)

Check 1, typed numbers (rule typed_number). Each number the input's typed_numbers lists is
compared with every number in the input, and flagged when it matches none of them. The numbers
in the input are: every number in the data values, effect amounts, per-rank stats and
coefficients of the record's own spell, of the other spells of its ability and of the spells
it refers to (every rank of a per-rank list); every number written in a calculation (its parts
and multipliers, not its precision); and every number in a worked-out value (a calculation's
value, a placeholder's shown value, a level-up row's shown value). The record's ranks are not
values. A number x matches the typed number t when, for a scale s of 1, 100 or 1/100 (a
fraction typed as a percent and back), t equals |x| times s, or rounds to it at t's own number
of decimals while staying within 2% of it ('33%' for 0.333). Seconds against milliseconds is
not a scale here: in 16.18 the 8 typed numbers that would match only at 1000 or 1/1000 all do so
by chance (such as a cast range of 10000 against '10% Health'; checked 2026-10-06), and no data
value was found holding a time in milliseconds.

Check 2, tooltip calculations (check tooltip_calc). Each value the text shows is compared with
the gameplay value it stands for. A shown value is a placeholder that names a calculation or a
data value, read from the record's own spell or from the spell a @spell.X:Name@ token names.
A tooltip-side value is a calculation the game marks tooltip-only, or a data value whose name
carries a tooltip affix (the game has no tooltip-only flag for data values). A gameplay value is
a calculation not marked tooltip-only, or a data value without a tooltip affix. The rules:

  name      A tooltip-side value against the gameplay value of the same name once the tooltip
            affixes are taken off (Tooltip, TooltipOnly, ForTooltip, TT or Display, at either
            end), in the same spell or another spell of its ability. A gameplay calculation the
            text also shows counts, with the value its placeholder shows. Calculations are compared by their worked-out values, data values rank
            by rank at a scale of 1, 100 or 1/100. The data values a shown tooltip-only calculation
            reads are compared the same way. Flagged when they differ.
  ratio     A shown tooltip-only calculation's AP ratio against the coefficient fields
            (mCoefficient, mCoefficient2) of its spell and the other spells of its ability,
            leaving out fields of 0 and 1 (their defaults). The fields name no stat, so only AP
            is checked against them. Its AD or bonus AD ratio against the same stat's ratios in
            the gameplay calculations of those spells. Flagged when there is something to compare
            with and the ratio equals none of it. Ratios of 0 and 1 (100%) are not checked, nor is
            a calculation shown as a percent (its ratio is a percent per 100 of the stat).
  copy      A shown tooltip-only calculation against a gameplay calculation of the same spell
            or ability whose formula has the same parts (the same stats, the same data values
            once affixes are off, the same shape), when the two are linked: the tooltip one reads
            a data value, or their names match once affixes are off or one holds the other. Flagged when the numbers differ (data values
            compared by their values) and so do the worked-out values, or when the gameplay one
            has the same parts plus one more top-level term (a term left out of the copy).
  stale     A value shown from a spell of the ability that is not the ability's own P, Q, W, E
            or R spell, against the value of the same name in that slot spell. Flagged when they
            differ.

A value can't be compared when either side is unresolved; such a pair is skipped, and the run
prints how many were, by rule. Each shown value is flagged at most once per input; when several
rules flag it, the flag lists them all.

The development measure (--dev-report, on a planted set only) counts a planted error as caught
when a flag is on its record and names what was changed: for a typed number, a flag at the
planted number's offset; otherwise a flag on a placeholder that shows the error. Changes are
made in place, so that is the changed calculation, the value a placeholder was pointed at, or
a shown calculation that reads the changed data value. This is a stand-in for
development only. The real catch judging is done by the judge model (PLAN.md, "Keeping the test
honest").

Examples (run from the project root):
  python3 scripts/baseline.py data/inputs/16.18.en_us.jsonl
  python3 scripts/baseline.py data/planted/dev.jsonl --dev-report
"""

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "data" / "baseline"
ENGLISH = "en_us"
SLOTS = ("P", "Q", "W", "E", "R")
SCALES = (1, 100, 0.01)
ROUNDING_SLACK = 0.02
AD_STATS = ("AD", "bonus AD")
COEF_FIELDS = ("mCoefficient", "mCoefficient2")
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
AFFIX_RE = re.compile(r"(?i)^(?:tooltiponly|fortooltip|tooltip|display|tt)_?|_?(?:tooltiponly|fortooltip|tooltip|display|tt)$")
# Fields of a calculation that are not values: how many decimals it shows, and labels.
NOT_VALUES = {"precision", "percent", "tooltip_only", "value", "known_name", "damage_type", "stat", "type"}
SECTIONS = ("spell", "ability", "referenced")


# ---------------------------------------------------------------- shared helpers

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def locale_of(inp):
    parts = (inp.get("id") or "").split(":")
    return parts[1] if len(parts) > 1 else None


def token_name(token):
    """The name a token reads: 'spell.AhriQ:TotalDamage*100' gives 'TotalDamage'."""
    name = token.split(":")[-1] if token.lower().startswith("spell.") else token
    return name.split("*")[0]


def base_name(name):
    """A name with its tooltip affixes taken off, lowercased, and whether it had one."""
    n, had = name, False
    while True:
        m = AFFIX_RE.search(n)
        if not m or len(n) == len(m.group(0)):
            break
        n = n[:m.start()] + n[m.end():]
        had = True
    return n.lower(), had


def per_rank(v):
    if isinstance(v, list):
        return [x for x in v]
    return [v]


def spells_of(inp):
    """Every spell section of the input: (section kind, spell section)."""
    out = [("spell", inp.get("spell") or {})]
    for kind in ("ability", "referenced"):
        out += [(kind, s) for s in inp.get(kind) or []]
    return out


def find_spell(inp, script):
    low = (script or "").lower()
    for _, s in spells_of(inp):
        if (s.get("spell") or "").lower() == low:
            return s
    return None


# ---------------------------------------------------------------- check 1: typed numbers

def numbers_in(o, out):
    """Every number inside a value: lists, formulas and worked-out value strings."""
    if is_number(o):
        out.add(abs(float(o)))
    elif isinstance(o, str):
        for m in NUM_RE.finditer(o):
            out.add(abs(float(m.group(0))))
    elif isinstance(o, list):
        for x in o:
            numbers_in(x, out)
    elif isinstance(o, dict):
        for k, v in o.items():
            if k in NOT_VALUES and k != "value":
                continue
            if k in ("dv", "DataValue", "StartDataValue", "EndDataValue", "modifies", "default",
                     "if_condition", "SpellCalculationKey", "effect"):
                continue  # names, not values
            numbers_in(v, out)


def input_numbers(inp):
    nums = set()
    for _, s in spells_of(inp):
        for field in ("data_values", "effects", "stats", "coefficients", "calculations"):
            numbers_in(s.get(field) or {}, nums)
        for row in s.get("level_up") or []:
            if len(row) > 2:
                numbers_in(row[2], nums)
    for ph in (inp.get("placeholders") or {}).values():
        numbers_in(ph.get("value"), nums)
        numbers_in(ph.get("formula"), nums)
    return nums


def decimals(text):
    m = re.search(r"\.(\d+)", text)
    return len(m.group(1)) if m else 0


def matches(t, places, x):
    for s in SCALES:
        y = x * s
        if abs(y - t) < 1e-9:
            return True
        if round(y, places) == t and abs(y - t) <= ROUNDING_SLACK * abs(t):
            return True
    return False


def check_typed_numbers(inp):
    flags = []
    tn = inp.get("typed_numbers") or []
    if not tn:
        return flags
    nums = input_numbers(inp)
    text = inp.get("text") or ""
    for n in tn:
        t = n.get("value")
        if not is_number(t):
            continue
        raw = n.get("text") or str(t)
        places = decimals(raw)
        if any(matches(abs(float(t)), places, x) for x in nums):
            continue
        s, e = n.get("start"), n.get("end")
        around = text[max(0, s - 20):e + 20] if isinstance(s, int) and isinstance(e, int) else raw
        flags.append({"names": f"the typed number {raw} in \"{around.strip()}\"", "check": "typed_number",
                      "rule": "typed_number", "detail": "matches no value in the input at any rank or scale",
                      "start": s, "end": e})
    return flags


# ---------------------------------------------------------------- check 2: tooltip calculations

class Values:
    """The calculations and data values of the input, by spell, with what the text shows."""

    def __init__(self, inp):
        self.inp = inp
        self.spells = []      # (kind, section)
        self.calcs = {}       # spell name -> {calc name: formula}
        self.dvs = {}         # spell name -> {data value name: per-rank list}
        self.slot = {}        # spell name -> slot
        for kind, s in spells_of(inp):
            name = s.get("spell")
            self.spells.append((kind, s))
            self.slot[name] = s.get("slot")
            self.calcs[name] = {k: c for k, c in (s.get("calculations") or {}).items() if isinstance(c, dict)}
            self.dvs[name] = dict(s.get("data_values") or {})
        own = (inp.get("spell") or {}).get("spell")
        self.own = own
        self.group = [own] + [s.get("spell") for s in inp.get("ability") or []]
        self.shown = []       # (token, name, kind, spell, formula or None, shown value)
        for tok, ph in (inp.get("placeholders") or {}).items():
            kind = ph.get("kind")
            if kind not in ("calculation", "data_value"):
                continue
            sp = own
            if ph.get("of"):
                s = find_spell(inp, ph["of"])
                sp = s.get("spell") if s else None
            if sp is None:
                continue
            f = ph.get("formula") if kind == "calculation" else None
            if isinstance(f, dict) and f.get("value") is None and ph.get("value") is not None \
                    and ph.get("factor") is None and "*" not in tok:
                f = dict(f, value=ph["value"])  # a shown calculation's value sits on its placeholder
            if kind == "calculation" and isinstance(f, dict):
                # A shown calculation is left out of its spell's calculations, so it is added here
                # and a shown gameplay calculation is compared like any other.
                self.calcs.setdefault(sp, {}).setdefault(token_name(tok), f)
            self.shown.append((tok, token_name(tok), kind, sp, f, ph.get("value")))

    def calc_value(self, f, shown=None):
        if isinstance(f, dict) and f.get("value") is not None:
            return f["value"]
        return shown

    def dv(self, sp, name):
        low = name.lower()
        for k, v in (self.dvs.get(sp) or {}).items():
            if k.lower() == low:
                return k, v
        return None, None

    def calc(self, sp, name):
        low = name.lower()
        for k, v in (self.calcs.get(sp) or {}).items():
            if k.lower() == low:
                return k, v
        return None, None


def resolved(v):
    return v is not None and not (isinstance(v, str) and v.startswith("unresolved"))


def same_ranks(a, b):
    a, b = per_rank(a), per_rank(b)
    if len(a) == 1 and len(b) > 1:
        a = a * len(b)
    if len(b) == 1 and len(a) > 1:
        b = b * len(a)
    if len(a) != len(b) or not all(is_number(x) for x in a + b):
        return None  # can't compare
    for s in SCALES:
        if all(abs(x * s - y) <= 1e-6 * max(1, abs(y)) for x, y in zip(a, b)):
            return True
    return False


def dv_names(f, out):
    if isinstance(f, dict):
        for k, v in f.items():
            if k in ("dv", "DataValue", "StartDataValue", "EndDataValue") and isinstance(v, str):
                out.append(v)
            else:
                dv_names(v, out)
    elif isinstance(f, list):
        for x in f:
            dv_names(x, out)
    return out


def stat_parts(f, out):
    """(stat, coefficient) of every stat ratio with a written coefficient in a formula."""
    if isinstance(f, dict):
        if "stat" in f and is_number(f.get("coef")):
            out.append((f["stat"], f["coef"]))
        for k, v in f.items():
            if k != "stat":
                stat_parts(v, out)
    elif isinstance(f, list):
        for x in f:
            stat_parts(x, out)
    return out


def shape(f):
    """A formula's parts with numbers blanked and data value names without affixes."""
    if is_number(f):
        return "#"
    if isinstance(f, list):
        return [shape(x) for x in f]
    if isinstance(f, dict):
        out = {}
        for k, v in f.items():
            if k in ("tooltip_only", "value", "known_name", "precision"):
                continue
            if k in ("dv", "DataValue", "StartDataValue", "EndDataValue") and isinstance(v, str):
                out[k] = base_name(v)[0]
            else:
                out[k] = shape(v)
        return out
    return f


def filled_numbers(f, vals, sp):
    """A formula with each data value replaced by its per-rank values, for comparing numbers."""
    if isinstance(f, list):
        return [filled_numbers(x, vals, sp) for x in f]
    if isinstance(f, dict):
        out = {}
        for k, v in f.items():
            if k in ("tooltip_only", "value", "known_name", "precision"):
                continue
            if k in ("dv", "DataValue", "StartDataValue", "EndDataValue") and isinstance(v, str):
                _, got = vals.dv(sp, v)
                out[k] = per_rank(got) if got is not None else v
            else:
                out[k] = filled_numbers(v, vals, sp)
        return out
    return f


def top_parts(f):
    parts = f.get("parts") if isinstance(f, dict) else None
    return parts if isinstance(parts, list) else None


def name_link(a, b):
    """Whether two names are linked: the same once affixes are off, or one inside the other."""
    a, b = base_name(a)[0], base_name(b)[0]
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))


def near(x, y):
    return abs(x - y) <= 1e-6


def check_tooltip_calcs(inp, skipped=None):
    """The tooltip_calc flags of one input. skipped, a Counter, gets one count per rule for each
    pair the rule matched but could not compare because a side is unresolved."""
    vals = Values(inp)
    found = {}  # placeholder token -> flag
    skipped = skipped if skipped is not None else Counter()

    def flag(tok, name, rule, names, detail, value_name=None):
        f = found.get(tok)
        if f is None:
            found[tok] = {"names": names, "check": "tooltip_calc", "rule": rule, "detail": detail,
                          "placeholder": name, "value_name": value_name or name}
        elif rule not in f["rule"].split("+"):
            f["rule"] += "+" + rule
            f["detail"] += "; " + detail

    def differ(rule, mine, theirs):
        """True when two worked-out values differ; a pair with an unresolved side is counted."""
        if not (resolved(mine) and resolved(theirs)):
            skipped[rule] += 1
            return False
        return mine != theirs

    def ranks_differ(rule, mine, theirs):
        same = same_ranks(mine, theirs)
        if same is None:
            skipped[rule] += 1
        return same is False

    for tok, name, kind, sp, formula, shown in vals.shown:
        here = [sp] + [g for g in vals.group if g != sp] if sp in vals.group else [sp]
        tooltip_calc = kind == "calculation" and isinstance(formula, dict) and bool(formula.get("tooltip_only"))
        b, had = base_name(name)
        shown_txt = f"@{tok}@ shows {shown}"

        # name: a tooltip-side value against the gameplay value of the same base name.
        if kind == "calculation" and (tooltip_calc or had) and isinstance(formula, dict):
            mine = vals.calc_value(formula, shown)
            for g in here:
                for k, c in (vals.calcs.get(g) or {}).items():
                    if k.lower() == name.lower() or c.get("tooltip_only") or base_name(k)[0] != b or base_name(k)[1]:
                        continue
                    theirs = c.get("value")
                    if differ("name", mine, theirs):
                        flag(tok, name, "name", shown_txt,
                             f"{name} is {mine} but the gameplay calculation {k} is {theirs}", k)
        if kind == "data_value" and had:
            _, mine = vals.dv(sp, name)
            for g in here:
                for k, v in (vals.dvs.get(g) or {}).items():
                    if k.lower() == name.lower() or base_name(k)[1] or base_name(k)[0] != b:
                        continue
                    if mine is not None and ranks_differ("name", mine, v):
                        flag(tok, name, "name", shown_txt,
                             f"{name} is {mine} but the gameplay data value {k} is {v}", k)
        if tooltip_calc:
            for d in dv_names(formula, []):
                db, dhad = base_name(d)
                if not dhad:
                    continue
                _, mine = vals.dv(sp, d)
                for g in here:
                    for k, v in (vals.dvs.get(g) or {}).items():
                        if base_name(k)[1] or base_name(k)[0] != db:
                            continue
                        if mine is not None and ranks_differ("name", mine, v):
                            flag(tok, name, "name", shown_txt,
                                 f"{name} reads {d} = {mine} but the gameplay data value {k} is {v}", d)

        # ratio: a shown tooltip-only calculation's AP ratio against the coefficient fields, and
        # its AD or bonus AD ratio against the same stat's ratios in the gameplay calculations.
        if tooltip_calc and not formula.get("percent"):
            coefs = []
            for g in here:
                sec = next((s for _, s in vals.spells if s.get("spell") == g), {})
                coefs += [c for k, c in (sec.get("coefficients") or {}).items() if k in COEF_FIELDS and is_number(c)]
            coefs = [c for c in coefs if c not in (0, 1)]  # 0 and 1 are the field's defaults
            gameplay = defaultdict(list)  # stat -> ratios the gameplay calculations use
            for g in here:
                for k, c in (vals.calcs.get(g) or {}).items():
                    if not c.get("tooltip_only"):
                        for stat, x in stat_parts(c, []):
                            gameplay[stat].append(x)
            for stat, c in stat_parts(formula, []):
                if near(c, 0) or near(c, 1):
                    continue  # a ratio of 0 or 100% is a convention more than a tuned number
                if stat == "AP":
                    known, against = coefs, "the spell's coefficients"
                elif stat in AD_STATS:
                    known, against = gameplay[stat], f"the gameplay calculations' {stat} ratios"
                else:
                    continue
                if known and not any(near(c, x) for x in known):
                    flag(tok, name, "ratio", shown_txt,
                         f"its {stat} ratio {c:g} is none of {against} "
                         f"({', '.join(f'{x:g}' for x in sorted(set(known)))})")

        # copy: a shown tooltip-only calculation against a gameplay calculation with its parts,
        # linked to it by name or by reading data values.
        if tooltip_calc:
            my_shape = shape(formula)
            my_parts = top_parts(formula)
            reads = bool(dv_names(formula, []))  # same shape means the same data values, affixes off
            for g in here:
                for k, c in (vals.calcs.get(g) or {}).items():
                    if k.lower() == name.lower() or c.get("tooltip_only"):
                        continue
                    if not (reads or name_link(name, k)):
                        continue
                    if shape(c) == my_shape:
                        if filled_numbers(c, vals, g) != filled_numbers(formula, vals, sp):
                            theirs = c.get("value")
                            if differ("copy", vals.calc_value(formula, shown), theirs):
                                flag(tok, name, "copy", shown_txt,
                                     f"it has the parts of the gameplay calculation {k} ({theirs}) with different numbers", k)
                        continue
                    their_parts = top_parts(c)
                    if my_parts is not None and their_parts is not None and len(their_parts) == len(my_parts) + 1:
                        rest = {kk: vv for kk, vv in formula.items() if kk != "parts"}
                        their_rest = {kk: vv for kk, vv in c.items() if kk != "parts"}
                        if shape(rest) != shape(their_rest):
                            continue
                        for i in range(len(their_parts)):
                            if shape(their_parts[:i] + their_parts[i + 1:]) == shape(my_parts):
                                flag(tok, name, "copy", shown_txt,
                                     f"it is the gameplay calculation {k} ({c.get('value')}) with a term left out", k)
                                break

        # stale: a value shown from a spell of the ability that is not its slot spell.
        slot_spells = [g for g in vals.group if vals.slot.get(g) in SLOTS]
        if sp in vals.group and vals.slot.get(sp) not in SLOTS:
            for g in slot_spells:
                if kind == "data_value":
                    _, mine = vals.dv(sp, name)
                    k, theirs = vals.dv(g, name)
                    if mine is not None and theirs is not None and ranks_differ("stale", mine, theirs):
                        flag(tok, name, "stale", shown_txt,
                             f"{sp} has {name} = {mine} but the slot spell {g} has {theirs}", name)
                else:
                    k, c = vals.calc(g, name)
                    if c is None:
                        continue
                    mine = vals.calc_value(formula, shown)
                    theirs = c.get("value")
                    if differ("stale", mine, theirs):
                        flag(tok, name, "stale", shown_txt,
                             f"{sp} has {name} = {mine} but the slot spell {g} has {theirs}", name)
    return list(found.values())


# ---------------------------------------------------------------- running

def check_input(inp, planted_id=None, skipped=None):
    """Every flag for one input. skipped, a Counter, gets the pairs a rule could not compare."""
    loc = locale_of(inp)
    if loc != ENGLISH:
        return []
    out = []
    for f in check_typed_numbers(inp) + check_tooltip_calcs(inp, skipped):
        flag = {"id": inp.get("id")}
        if planted_id:
            flag["planted_id"] = planted_id
        flag.update({"text_field": inp.get("text_field"), "locale": loc})
        flag.update(f)
        out.append({k: v for k, v in flag.items() if v is not None})
    return out


def read_items(path):
    """(planted entry or None, input) for each line of an inputs or planted file."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                o = json.loads(line)
                yield (o, o["input"]) if "input" in o and "kind" in o else (None, o)


def plain_name(token):
    """A placeholder's name for matching: no spell prefix, scale or index ('X.0*100' gives 'x')."""
    return re.sub(r"\.\d+$", "", token_name(token)).lower()


def planted_targets(entry):
    """The placeholders that show a planted tooltip-calculation error, by plain name. Every change
    is made in place: the changed calculation, the placeholder pointed at another value, or the
    changed data value and each shown calculation that reads it."""
    ch = entry.get("change") or {}
    out = {plain_name(str(ch[k])) for k in ("calc", "points_at") if ch.get(k)}
    d = ch.get("data_value")
    if d and not ch.get("calc"):
        out.add(plain_name(d))
        for tok, ph in ((entry.get("input") or {}).get("placeholders") or {}).items():
            if d.lower() in {x.lower() for x in dv_names(ph.get("formula"), [])}:
                out.add(plain_name(tok))
    return out


def caught(entry, flags):
    """The development matcher (see the docstring): does any flag name the planted change?"""
    ch = entry.get("change") or {}
    if entry.get("rule") == "typed_number":
        return any(f["check"] == "typed_number" and f.get("start") == ch.get("start") for f in flags)
    targets = planted_targets(entry)
    return any(f["check"] == "tooltip_calc" and plain_name(str(f.get("placeholder", ""))) in targets
               for f in flags)


def dev_report(items, flags_by_id):
    per = defaultdict(lambda: [0, 0])
    for entry, _ in items:
        key = (entry["kind"], entry["rule"] if entry["locale"] == ENGLISH else f"{entry['rule']} ({entry['locale']})")
        per[key][1] += 1
        if caught(entry, flags_by_id.get(entry["id"], [])):
            per[key][0] += 1
    by_kind = defaultdict(lambda: [0, 0])
    lines = ["kind / rule: caught of planted"]
    for (kind, rule), (c, n) in sorted(per.items()):
        lines.append(f"  {kind} / {rule}: {c} of {n}")
        by_kind[kind][0] += c
        by_kind[kind][1] += n
    lines.append("by kind:")
    for kind, (c, n) in sorted(by_kind.items()):
        lines.append(f"  {kind}: {c} of {n} ({100 * c / n:.0f}%)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path, help="an inputs file or a planted set")
    ap.add_argument("--out", type=Path, help="where to write the flags (default data/baseline/<name>.flags.jsonl)")
    ap.add_argument("--dev-report", action="store_true", help="on a planted set: print the development catch counts")
    args = ap.parse_args()
    items = list(read_items(args.path))
    out = args.out or DEFAULT_OUT / (args.path.name.replace(".jsonl", "") + ".flags.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    flags_by_id = {}
    counts = Counter()
    skipped = 0
    pairs_skipped = Counter()
    with out.open("w", encoding="utf-8") as fh:
        for entry, inp in items:
            if locale_of(inp) != ENGLISH:
                skipped += 1
            flags = check_input(inp, entry["id"] if entry else None, pairs_skipped)
            flags_by_id[entry["id"] if entry else inp.get("id")] = flags
            for f in flags:
                counts[f["check"]] += 1
                for r in f["rule"].split("+"):
                    counts[f"{f['check']}/{r}"] += 1
                fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    total = counts["typed_number"] + counts["tooltip_calc"]
    print(f"{args.path.name}: {len(items)} inputs, {skipped} not in English (not checked), {total} flags")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")
    print(f"  pairs not compared (a side unresolved): {sum(pairs_skipped.values())}"
          + "".join(f", {r} {n}" for r, n in sorted(pairs_skipped.items())))
    print(f"  wrote {out}")
    if args.dev_report:
        if not all(entry for entry, _ in items):
            sys.exit("--dev-report needs a planted set")
        print(dev_report(items, flags_by_id))


if __name__ == "__main__":
    main()
