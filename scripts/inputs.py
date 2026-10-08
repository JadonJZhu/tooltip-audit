#!/usr/bin/env python3
"""Build the input each checker reads: one object per checked tooltip record.

The baseline script, the planting code and the model checker all read the same input, built
here from what resolve_tooltips.py wrote: the records (data/resolved/<patch>.<locale>.jsonl)
and the spell lines (data/resolved/<patch>.<locale>.spells.jsonl). A checked record is one
without duplicate_of and whose text_field is not passiveToolTip, the same set the summary's
checked_records counts.

The API: build_input(rec, lines, english=None) builds one input, where lines is {key: spell
line} and english is the English input for a translated record; build_inputs(records, lines,
english_records=None, english_lines=None) builds every checked record's. build_input works only
on what it is handed and never reads a file, and the input it returns shares no object with
them. Every worked-out value in an input (each placeholder's value, each calculation's value and
the level-up list's shown values) is the one resolve_tooltips.py wrote; the builder works none
of them out. So a changed copy of a spell line gives an input whose formulas and data values
change but whose worked-out values do not, unless the copy is resolved again first.

Each input holds (keys left out when empty):
  id                  '<patch>:<locale>:<champion_folder>:<spell_path>:<text_field>'
  champion, slot, text_field, ranks (the record's own ranks)
  text                the text as stored, with its @placeholders@
  typed_numbers       each number typed into the text by hand, as the resolver found it:
                      {value, text, start, end}, with start and end offsets into text
  filled              the same text with each placeholder replaced by its displayed value
                      (an unresolved placeholder stays as @Name@)
  placeholders        {token: {kind, value, formula, of, factor, unresolved}}; value is the
                      displayed value, one per rank joined by '/' ('35/60/85 (+50% AP)');
                      formula is the calculation the token names, written as below, with
                      its own worked-out value even when that is the placeholder's (a
                      checker comparing two calculations reads it there); of is the
                      other spell a @spell.X:Name@ token reads
  spell               the record's own spell: its data values, effect amounts, coefficients,
                      per-rank stats (cooldown, cost and so on), the calculations no
                      placeholder names, its level-up list as [label, value read, value
                      shown], EnableExtendedTooltip when the line sets it, its own ranks and
                      rank_source when they differ from the record's, and joined_by when the
                      group is not the game's own ability object
  ability             the other spells of the same ability, in the same form, each with the
                      rule that grouped it when that is not the game's own ability object
  referenced          any other spell the record's placeholders or its spell's calculations
                      read, in the same form
  spells_not_in_file  the keys of any of these spells, the record's own included, that are
                      not in the lines handed in
  rank_source, varies_by_rank, includes, extended_text_hidden_in_game
                      copied from the record when they say something (rank_source is left
                      out when it is the LevelUp list)
  english             for a locale other than en_us: {text, filled} of the English input for
                      the same spell_path and text_field, always both and nothing else, so
                      every translated input's English side has the same shape (the game
                      data is the same in every language); english_missing is set instead
                      when there is none

An effect amount (EffectNAmount) or coefficient (mCoefficient, mCoefficient2) is left out of a
spell when nothing in the input reads it: no placeholder, calculation or level-up row of that
spell names it.

A list of per-rank values that are all the same is written once. A value that differs by rank
is always written in full. A calculation keeps every part and number of the game's own
formula, with the type names shortened ('NamedDataValueCalculationPart' becomes {"dv": name},
a stat ratio {"stat": "AP", "coef": 0.5}, a plain number the number itself), the 'm' prefix
dropped from the game's field names, and the fields that only choose an icon or a layout in
the tooltip (mSimpleTooltipCalculationDisplay, mExpandedTooltipCalculationDisplay,
StaticTooltipCalculationDisplay, mIconKey) left out. Its worked-out value is in value. A
DamageType code is written as damage_type, a word ('physical', 'magic' or 'true'). A field that
names another calculation by hash ('modifies': '{550661bd}') gives the readable name instead
when the input shows that calculation under one.

Examples (run from the project root):
  python3 scripts/inputs.py --patch 16.19
  python3 scripts/inputs.py --patch 16.18 --locale fr_fr
"""

import argparse
import copy
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resolve_tooltips import CALC_REF_FIELDS, LEGACY_STAT_RE, TOKEN_RE, fnv1a  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESOLVED = PROJECT_ROOT / "data" / "resolved"
DEFAULT_OUT = PROJECT_ROOT / "data" / "inputs"
ENGLISH = "en_us"
# Characters per token for the size estimate main() prints. Measured once, on 2026-10-05: the
# 16.19 English inputs of that day, 3.33 million characters, came to 1,113,760 tokens with the
# DeepSeek-V3 tokenizer (a stand-in for DeepSeek-V4-Pro's), about 2.99 characters per token.
CHARS_PER_TOKEN = 3.0

# Fields that only pick an icon or a layout in the tooltip, not a value.
DISPLAY_ONLY = {"mSimpleTooltipCalculationDisplay", "mExpandedTooltipCalculationDisplay", "StaticTooltipCalculationDisplay",
                "mStaticTooltipCalculationDisplay", "mIconKey"}
# Short names for the calculation fields every reader meets; any other field keeps its own
# name, less the leading 'm'.
CALC_FIELDS = {"mFormulaParts": "parts", "mMultiplier": "multiplier", "mDisplayAsPercent": "percent",
               "mPrecision": "precision", "tooltipOnly": "tooltip_only", "mModifiedGameCalculation": "modifies",
               "mDefaultGameCalculation": "default", "mConditionalGameCalculation": "if_condition",
               "mConditionalCalculationRequirements": "condition"}
# Fields the resolver already turned into words ('stat', 'effect'), so the codes are dropped.
CODED = {"stat": ("mStat", "mStatFormula", "mAbilityResource"), "effect": ("mEffectIndex",)}
# A calculation's DamageType code as a word. Checked against the English text of every resolved
# en_us patch on 2026-10-05: code 0 sits before "physical damage" (7 calculations, such as Jinx
# Q RocketDamage), code 1 before "magic damage" (10 calculations, such as Janna W BonusDamage),
# with no calculation of either code next to another damage word, and code 2 is Corki's passive
# BasicAttackTOOLTIP, whose text says the Attacks deal "bonus true damage". Any other code is
# written as "code N".
DAMAGE_TYPES = {0: "physical", 1: "magic", 2: "true"}
# The short names of the fields that name another calculation.
CALC_REFS = {CALC_FIELDS.get(k, k[1:]) for k in CALC_REF_FIELDS}
DV_FIELDS = {"mDataValue": "data_value_name", "DataValue": "data_value_name",
             "StartDataValue": "start_data_value_name", "EndDataValue": "end_data_value_name"}


def record_id(rec):
    return ":".join(str(rec[k]) for k in ("patch", "locale", "champion_folder", "spell_path", "text_field"))


def is_checked(rec):
    """The records the summary's checked_records counts."""
    return not rec.get("duplicate_of") and rec.get("text_field") != "passiveToolTip"


def once(values):
    """A per-rank list written once when every rank has the same value."""
    if isinstance(values, list) and values and all(v == values[0] for v in values):
        return values[0]
    return values


def joined(display):
    """Per-rank display strings as one string: '35/60/85 (+50% AP)'. The part every rank shares
    at the end, from a ' (' on, is written once."""
    if not display:
        return None
    if all(d == display[0] for d in display):
        return display[0]
    first = display[0]
    cut = None
    for i in range(len(first)):
        if first[i:i + 2] == " (" and all(d.endswith(first[i:]) and len(d) > len(first) - i for d in display):
            cut = i
            break
    if cut is None:
        return "/".join(display)
    tail = first[cut:]
    return "/".join(d[:len(d) - len(tail)] for d in display) + tail


def short_key(k):
    if k in CALC_FIELDS:
        return CALC_FIELDS[k]
    if len(k) > 1 and k[0] == "m" and k[1].isupper():
        return k[1:]
    return k


def part(p):
    """One calculation part, or any bin object inside one, in the short form."""
    if isinstance(p, list):
        return [part(x) for x in p]
    if not isinstance(p, dict):
        return p
    t = p.get("__type") or ""
    dv = p.get("data_value_name") or p.get("mDataValue")
    if t == "NumberCalculationPart" and set(p) <= {"__type", "mNumber"}:
        return p.get("mNumber", 0)
    if t == "NamedDataValueCalculationPart" and set(p) <= {"__type", "mDataValue", "data_value_name"}:
        return {"dv": dv}
    if t == "StatByCoefficientCalculationPart" and set(p) <= {"__type", "mCoefficient", "stat", "mStat", "mStatFormula"}:
        return {"stat": p.get("stat"), "coef": p.get("mCoefficient", 1)}
    if t == "StatByNamedDataValueCalculationPart" and set(p) <= {"__type", "mDataValue", "data_value_name", "stat",
                                                                 "mStat", "mStatFormula"}:
        return {"stat": p.get("stat"), "dv": dv}
    if t == "SumOfSubPartsCalculationPart" and set(p) <= {"__type", "mSubparts"}:
        return {"sum": part(p.get("mSubparts") or [])}
    if t == "ProductOfSubPartsCalculationPart" and set(p) <= {"__type", "mPart1", "mPart2"}:
        return {"product": [part(p.get("mPart1")), part(p.get("mPart2"))]}
    if t == "EffectValueCalculationPart" and "effect" in p:
        return {"effect": p["effect"]}
    out = {}
    if t and t not in ("Breakpoint", "GameCalculation"):
        out["type"] = t[:-len("CalculationPart")] if t.endswith("CalculationPart") else t
    drop = {"__type"} | DISPLAY_ONLY
    for word, codes in CODED.items():
        if word in p:
            drop.update(codes)
    for field, name_field in DV_FIELDS.items():
        if p.get(name_field):
            drop.add(name_field)  # the name replaces the hash below
    for k, v in p.items():
        if k in drop:
            continue
        name_field = DV_FIELDS.get(k)
        if name_field and p.get(name_field):
            v = p[name_field]
        if k == "DamageType" and isinstance(v, int) and not isinstance(v, bool):
            out["damage_type"] = DAMAGE_TYPES.get(v, f"code {v}")
            continue
        out[short_key(k)] = part(v)
    return out


def calc_value(result):
    if not isinstance(result, dict):
        return None
    if result.get("status") == "resolved":
        return joined(result.get("display"))
    return "unresolved: " + " ".join(x for x in (result.get("reason"), result.get("detail")) if x)


def calculation(c):
    """A calculation from a spell line in the short form, with its value."""
    if not isinstance(c, dict):
        return c
    out = part({k: v for k, v in c.items() if k != "result"})
    if not isinstance(out, dict):
        out = {"value_as_written": out}
    v = calc_value(c.get("result"))
    if v is not None:
        out["value"] = v
    return out


def find_calc(line, name):
    """(name as stored, calculation) for a placeholder name, matched as the resolver matches it:
    without regard to case, or by the hash of the name."""
    calcs = (line or {}).get("calculations") or {}
    low = name.lower()
    for k, c in calcs.items():
        if k.lower() == low:
            return k, c
    h = fnv1a(name) if not low.startswith("{") else None
    for k, c in calcs.items():
        if k.lower() == h:
            return k, c
    return None, None


def placeholder_value(ph):
    if ph.get("status") == "resolved":
        return joined(ph.get("display"))
    return None


def placeholder_entry(ph, line):
    out = {"kind": ph.get("kind")}
    if ph.get("owner_spell"):
        out["of"] = ph["owner_spell"]
    if ph.get("factor") is not None:
        out["factor"] = ph["factor"]
    value = placeholder_value(ph)
    if value is not None:
        out["value"] = value
    elif ph.get("status") == "unresolved":
        out["unresolved"] = " ".join(x for x in (ph.get("reason"), ph.get("detail")) if x)
    if ph.get("kind") == "calculation" and line is not None:
        key, c = find_calc(line, ph.get("name") or "")
        if c is not None:
            # The formula keeps its own value even when the placeholder shows the same one, so
            # every calculation in an input carries its value where a checker looks for it.
            f = calculation(c)
            if isinstance(f, dict) and str(f.get("known_name", "")).lower() == (ph.get("name") or "").lower():
                f.pop("known_name")  # the token already gives the name
            out["formula"] = f
            out["_calc"] = key
    return out


def level_up(line):
    rows = []
    for row in ((line.get("level_up") or {}).get("rows") or []):
        shown = row.get("value_times_multiplier") or row.get("value") or {}
        value = joined(shown.get("display")) if "display" in shown else \
            "unresolved: " + str(shown.get("reason") or shown.get("status"))
        rows.append([row.get("label") or row.get("nameOverride") or row.get("type"), row.get("reads"), value])
    return rows


def read_field(name):
    """The effect amount or coefficient field a placeholder or level-up name reads, or None."""
    m = re.search(r"effect(\d+)amount", name or "", re.I)
    if m:
        return f"Effect{int(m.group(1))}Amount"
    m = LEGACY_STAT_RE.match(name or "")
    if m:
        return "mCoefficient2" if m.group(2) else "mCoefficient"
    return None


def fields_read(line, names=()):
    """The effect amounts and coefficients of a spell line that its calculations, its level-up
    rows or the given placeholder names read."""
    found = {read_field(n) for n in names}

    def walk(o):
        if isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            if isinstance(o.get("effect"), str):
                found.add(read_field(o["effect"]))
            for v in o.values():
                walk(v)

    walk(line.get("calculations"))
    for row in ((line.get("level_up") or {}).get("rows") or []):
        found.add(read_field(row.get("reads")))
    return found


def spell_part(line, ranks=None, skip_calcs=(), with_level_up=True, names=()):
    """A spell line in the short form. ranks are written only when they differ from the
    record's. names are the placeholder names of the input that read this spell."""
    out = {"spell": line.get("script_name") or line.get("spell_path"), "slot": line.get("slot")}
    if ranks is not None and line.get("ranks") != ranks:
        out["ranks"] = line.get("ranks")
        if line.get("rank_source"):
            out["rank_source"] = line["rank_source"]
    read = fields_read(line, names)
    for src, dst in (("data_values", "data_values"), ("effect_amounts", "effects"), ("spell_stats", "stats")):
        vals = {k: once(v) for k, v in (line.get(src) or {}).items() if src != "effect_amounts" or k in read}
        if vals:
            out[dst] = vals
    coefs = {k: v for k, v in (line.get("coefficients") or {}).items() if k in read}
    if coefs:
        out["coefficients"] = coefs
    calcs = {k: calculation(c) for k, c in (line.get("calculations") or {}).items() if k not in skip_calcs}
    if calcs:
        out["calculations"] = calcs
    if with_level_up:
        rows = level_up(line)
        if rows:
            out["level_up"] = rows
    if line.get("EnableExtendedTooltip") is not None:
        out["EnableExtendedTooltip"] = line["EnableExtendedTooltip"]
    if set(out) <= {"spell", "slot", "ranks", "rank_source"}:
        out.pop("ranks", None)  # no values for the ranks to describe
        out.pop("rank_source", None)
    return out


def owner_line(rec, script, lines):
    """The spell line a @spell.Script:Name@ token reads: a line of the same champion with that
    script name (or path end), preferring the spells the record lists as referenced."""
    low = script.lower()
    keys = list(rec.get("referenced_spells") or [])
    folder = rec.get("champion_folder")
    keys += [k for k in lines if k.startswith(f"{folder}:")]
    for k in keys:
        ln = lines.get(k)
        if ln and ((ln.get("script_name") or "").lower() == low or ln.get("spell_path", "").lower().endswith("/" + low)):
            return k, ln
    return None, None


def fill(text, entries):
    def sub(m):
        e = entries.get(m.group(1))
        return e["value"] if e and e.get("value") is not None else m.group(0)
    return TOKEN_RE.sub(sub, text or "")


def build_input(rec, lines, english=None):
    """The input for one record. lines is {key: spell line}, holding at least the record's own
    line, its group's and the lines it refers to; english is the English input for the same
    spell_path and text_field (for a translated record), or None."""
    own_key = rec.get("spell_context")
    own = lines.get(own_key)
    missing = []
    if own is None:
        missing.append(own_key or rec.get("spell_path"))
        own = {}
    ranks = rec.get("ranks")
    entries = {}
    used = {}  # spell key -> calculation names a placeholder shows
    names = {}  # spell key -> placeholder names that read it
    for ph in rec.get("placeholders") or []:
        tok = ph.get("token")
        if tok in entries:
            continue
        line_key, line = own_key, own
        if ph.get("owner_spell"):
            line_key, line = owner_line(rec, ph["owner_spell"], lines)
        names.setdefault(line_key, set()).add(ph.get("name"))
        e = placeholder_entry(ph, line)
        if "_calc" in e:
            used.setdefault(line_key, set()).add(e.pop("_calc"))
        entries[tok] = e
    out = {"id": record_id(rec), "champion": rec.get("champion"), "slot": rec.get("slot"),
           "text_field": rec.get("text_field"), "ranks": ranks,
           "text": rec.get("raw_text"), "filled": fill(rec.get("raw_text"), entries)}
    if entries:
        out["placeholders"] = entries
    if rec.get("typed_numbers"):
        # Offsets are into text. The resolver's context is left out: it is a piece of text.
        out["typed_numbers"] = [{k: n.get(k) for k in ("value", "text", "start", "end")}
                                for n in rec["typed_numbers"]]
    for k in ("varies_by_rank", "includes"):
        if rec.get(k):
            out[k] = rec[k]
    if rec.get("rank_source") and rec["rank_source"] != "LevelUp list":
        out["rank_source"] = rec["rank_source"]
    if rec.get("extended_text_hidden_in_game"):
        out["extended_text_hidden_in_game"] = True
    out["spell"] = spell_part(own, None, used.get(own_key, ()), names=names.get(own_key, ()))
    if own.get("ranks") != ranks:
        out["spell"]["ranks"] = own.get("ranks")
        out["spell"]["rank_source"] = own.get("rank_source")
    seen = {own_key}
    group = own.get("group") or {}
    ability = []
    for k in group.get("spells") or []:
        if k in seen:
            continue
        seen.add(k)
        ln = lines.get(k)
        if ln is None:
            missing.append(k)
            continue
        s = spell_part(ln, ranks, used.get(k, ()), names=names.get(k, ()))
        g = ln.get("group") or {}
        if g.get("joined_by") and g.get("joined_by") != "AbilityObject":
            s["joined_by"] = g["joined_by"]
        ability.append(s)
    if ability:
        out["ability"] = ability
    if group.get("joined_by") and group.get("joined_by") != "AbilityObject":
        out["spell"]["joined_by"] = group["joined_by"]
    referenced = []
    for k in list(rec.get("referenced_spells") or []) + list(own.get("refers_to") or []):
        if k in seen:
            continue
        seen.add(k)
        ln = lines.get(k)
        if ln is None:
            missing.append(k)
            continue
        referenced.append(spell_part(ln, ranks, used.get(k, ()), names=names.get(k, ())))
    if referenced:
        out["referenced"] = referenced
    if missing:
        out["spells_not_in_file"] = missing
    name_hashed_refs(out, rec, [lines.get(k) for k in seen])
    if rec.get("locale") != ENGLISH:
        if english is None:
            out["english_missing"] = True
        else:
            out["english"] = english_part(english)
    # Nothing in the input is shared with the record or the lines it came from (or with the
    # English input), so editing one never changes the other.
    return copy.deepcopy(out)


def readable(name):
    return isinstance(name, str) and bool(name) and not (name.startswith("{") and name.endswith("}"))


def name_hashed_refs(out, rec, lines_used):
    """Where a formula names another calculation by its hash ('modifies': '{550661bd}') and that
    calculation has a readable name in the input (a placeholder's name, or a calculation stored
    or known under one), write the readable name instead."""
    names = {}
    for ph in rec.get("placeholders") or []:
        if ph.get("kind") == "calculation" and readable(ph.get("name")):
            names.setdefault(fnv1a(ph["name"]), ph["name"])
    for ln in lines_used:
        for k, c in ((ln or {}).get("calculations") or {}).items():
            for n in (k, (c or {}).get("known_name") if isinstance(c, dict) else None):
                if readable(n):
                    names.setdefault(fnv1a(n), n)
    if not names:
        return

    def walk(o):
        if isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in CALC_REFS and isinstance(v, str) and v.lower() in names:
                    o[k] = names[v.lower()]
                else:
                    walk(v)

    for e in (out.get("placeholders") or {}).values():
        walk(e.get("formula"))
    for s in [out["spell"]] + out.get("ability", []) + out.get("referenced", []):
        walk(s.get("calculations"))


def english_part(en):
    """The English side of a translated input: the English text and filled text, always both and
    nothing more. The game data is the same in every language, and a fixed shape keeps a planted
    translation from standing out by which English keys it carries."""
    return {"text": en.get("text"), "filled": en.get("filled")}


def build_inputs(records, lines, english_records=None, english_lines=None):
    """One input per checked record, in file order. lines is the spell lines (a list, or a
    {key: line} dict). For a translated patch, english_records and english_lines are the
    en_us ones for the same patch."""
    by_key = lines if isinstance(lines, dict) else {ln["key"]: ln for ln in lines}
    en_by_id = {}
    if english_records is not None:
        en_lines = english_lines if isinstance(english_lines, dict) else \
            {ln["key"]: ln for ln in (english_lines or [])}
        for r in english_records:
            if is_checked(r):
                en_by_id[(r["champion_folder"], r["spell_path"], r["text_field"])] = (r, en_lines)
    out = []
    for rec in records:
        if not is_checked(rec):
            continue
        en = None
        if rec.get("locale") != ENGLISH and english_records is not None:
            hit = en_by_id.get((rec["champion_folder"], rec["spell_path"], rec["text_field"]))
            if hit:
                en = build_input(hit[0], hit[1])
        out.append(build_input(rec, by_key, en))
    return out


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load(patch, locale, resolved_dir=DEFAULT_RESOLVED):
    """(records, spell lines) for a resolved patch and language."""
    d = Path(resolved_dir)
    rec_path = d / f"{patch}.{locale}.jsonl"
    if not rec_path.exists():
        raise FileNotFoundError(f"{rec_path} not found. Run: python3 scripts/resolve_tooltips.py "
                                f"--patches {patch} --locale {locale}")
    return read_jsonl(rec_path), read_jsonl(d / f"{patch}.{locale}.spells.jsonl")


def dumps(inp):
    return json.dumps(inp, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patch", required=True)
    ap.add_argument("--locale", default=ENGLISH, type=str.lower)
    ap.add_argument("--resolved-dir", type=Path, default=DEFAULT_RESOLVED)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    try:
        records, lines = load(args.patch, args.locale, args.resolved_dir)
        en_records = en_lines = None
        if args.locale != ENGLISH:
            en_records, en_lines = load(args.patch, ENGLISH, args.resolved_dir)
    except FileNotFoundError as e:
        sys.exit(str(e))
    inputs = build_inputs(records, lines, en_records, en_lines)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"{args.patch}.{args.locale}.jsonl"
    sizes = []
    with path.open("w", encoding="utf-8") as fh:
        for inp in inputs:
            s = dumps(inp)
            sizes.append(len(s))
            fh.write(s + "\n")
    total = sum(sizes)
    note = "" if args.locale == ENGLISH else \
        f" ({sum(1 for i in inputs if i.get('english_missing'))} with no English record)"
    print(f"{args.patch} {args.locale}: {len(inputs)} inputs from {len(records)} records{note}")
    if sizes:
        print(f"  {total:,} characters, about {round(total / CHARS_PER_TOKEN):,} tokens at "
              f"{CHARS_PER_TOKEN} characters per token; median {int(statistics.median(sizes)):,} "
              f"characters, largest {max(sizes):,}")
    print(f"  wrote {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
