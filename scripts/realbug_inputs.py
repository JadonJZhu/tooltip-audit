#!/usr/bin/env python3
"""Build the checkers' inputs for the real-bug case study (PLAN.md, "Real bugs").

For each confirmed unit in answer_key/confirmations.csv, it takes the patch the bug was checked
in (prefix_patch) and builds, with inputs.py's own code, the input of every checked record of
the bug's ability: the records of the same champion whose spell is the bug record's own spell or
in its spell's group, or whose slot is the bug's slot. The bug's own record (its spell_path and
text_field) is marked, because only a flag on that record counts as a catch.

A translation bug's records are built in the bug's language, and each carries the English text
of the same record beside it (inputs.py's `english`), so a checker sees both side by side.

The resolved files must already exist and come from the CommunityDragon build the answer key
names (prefix_cdragon_version); otherwise the script stops and says which to resolve.

It writes data/inputs/realbugs.jsonl, one line per input:
  {"id": the input's id, "kind": "real", "bug": unit_id, "own_record": true|false, "input": {...}}
and prints the number of inputs per bug. The wrapper's "id" and "kind" let baseline.py and
check_model.py read the file like a planted set (both unwrap "input"), and every output line
then carries the record's own id, which is what evaluate.py joins a real bug on.

  python3 scripts/realbug_inputs.py
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inputs  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY = PROJECT_ROOT / "answer_key" / "confirmations.csv"
DEFAULT_OUT = PROJECT_ROOT / "data" / "inputs" / "realbugs.jsonl"


def confirmed(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["status"] == "confirmed"]


def check_build(patch, locale, want, resolved_dir):
    path = Path(resolved_dir) / f"{patch}.{locale}.summary.json"
    got = json.loads(path.read_text(encoding="utf-8")).get("cdragon_version") if path.exists() else None
    if got != want:
        sys.exit(f"{path}: build {got}, answer key says {want}. Run: python3 scripts/resolve_tooltips.py "
                 f"--patches {patch} --locale {locale}")


def ability_records(bug, records, lines):
    """The checked records of the bug's ability, and the bug's own record among them."""
    own = [r for r in records if r["champion_folder"] == bug["champion_folder"]
           and r["spell_path"] == bug["spell_path"] and r["text_field"] == bug["text_field"]]
    if len(own) != 1 or not inputs.is_checked(own[0]):
        raise ValueError(f"{bug['unit_id']}: expected one checked own record, found {len(own)}")
    own = own[0]
    group = (lines.get(own["spell_context"]) or {}).get("group") or {}
    keys = {own["spell_context"]} | set(group.get("spells") or [])
    out = [r for r in records if inputs.is_checked(r) and r["champion_folder"] == bug["champion_folder"]
           and (r["spell_context"] in keys or r["slot"] == bug["slot"])]
    return out, own


def bug_lines(bug, resolved_dir=inputs.DEFAULT_RESOLVED):
    """The output lines for one confirmed bug."""
    patch, locale = bug["prefix_patch"], bug["locale"]
    check_build(patch, locale, bug["prefix_cdragon_version"], resolved_dir)
    records, lines = inputs.load(patch, locale, resolved_dir)
    lines = {ln["key"]: ln for ln in lines}
    en_records = en_lines = None
    if locale != inputs.ENGLISH:
        check_build(patch, inputs.ENGLISH, bug["prefix_cdragon_version"], resolved_dir)
        en_records, en_lines = inputs.load(patch, inputs.ENGLISH, resolved_dir)
    recs, own = ability_records(bug, records, lines)
    built = inputs.build_inputs(recs, lines, en_records, en_lines)
    own_id = inputs.record_id(own)
    return [{"id": inp["id"], "kind": "real", "bug": bug["unit_id"], "own_record": inp["id"] == own_id, "input": inp}
            for inp in built]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answer-key", type=Path, default=DEFAULT_KEY)
    ap.add_argument("--resolved-dir", type=Path, default=inputs.DEFAULT_RESOLVED)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    bugs = confirmed(args.answer_key)
    out = []
    for bug in bugs:
        got = bug_lines(bug, args.resolved_dir)
        own = sum(x["own_record"] for x in got)
        if own != 1:
            sys.exit(f"{bug['unit_id']}: {own} own records")
        english = sum("english" in x["input"] for x in got)
        note = f", {english} with English beside" if bug["locale"] != inputs.ENGLISH else ""
        print(f"{bug['unit_id']:28} {bug['mechanism']:12} {bug['prefix_patch']:6} {bug['locale']}: "
              f"{len(got)} inputs{note}")
        out.extend(got)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for x in out:
            fh.write(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(bugs)} bugs, {len(out)} inputs; wrote {args.out}")


if __name__ == "__main__":
    main()
