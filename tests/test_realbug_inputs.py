"""Tests for scripts/realbug_inputs.py (no network). Run from the project root:

    python3 -m unittest tests.test_realbug_inputs
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import realbug_inputs as R  # noqa: E402

BUILD = "9.9.1+test"
W = "Characters/Ahri/Spells/AhriW"
W2 = "Characters/Ahri/Spells/AhriWDetonate"
Q = "Characters/Ahri/Spells/AhriQ"


def rec(path, field, slot, locale="en_us", text="Deals 10 damage.", **extra):
    r = {"patch": "9.9", "locale": locale, "champion": "Ahri", "champion_folder": "ahri", "spell_path": path,
         "text_field": field, "slot": slot, "raw_text": text, "spell_context": f"ahri:{path}", "ranks": [1]}
    r.update(extra)
    return r


def line(path, slot, group=None):
    ln = {"key": f"ahri:{path}", "spell_path": path, "script_name": path.split("/")[-1], "slot": slot}
    if group:
        ln["group"] = {"source": "slot spell", "spells": group}
    return ln


def write(d, locale, records, lines):
    d = Path(d)
    with (d / f"9.9.{locale}.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (d / f"9.9.{locale}.spells.jsonl").open("w", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(json.dumps(ln) + "\n")
    (d / f"9.9.{locale}.summary.json").write_text(json.dumps({"cdragon_version": BUILD}))


def bug(path=W2, field="keyTooltip", locale="en_us"):
    return {"unit_id": "9.10-ahri-W", "prefix_patch": "9.9", "prefix_cdragon_version": BUILD, "champion_folder": "ahri",
            "slot": "W", "spell_path": path, "text_field": field, "locale": locale}


GROUP = [f"ahri:{W}", f"ahri:{W2}"]
LINES = [line(W, "W", GROUP), line(W2, "other", GROUP), line(Q, "Q")]


class AbilityRecords(unittest.TestCase):
    def test_group_member_in_other_slot_is_included_and_own_record_marked(self):
        records = [rec(W, "keyTooltip", "W"), rec(W2, "keyTooltip", "other"), rec(Q, "keyTooltip", "Q"),
                   rec(W, "keyTooltipExtended", "W", duplicate_of=W2)]
        with tempfile.TemporaryDirectory() as d:
            write(d, "en_us", records, LINES)
            got = R.bug_lines(bug(), d)
        ids = [(x["input"]["id"].split(":")[3], x["own_record"]) for x in got]
        self.assertEqual(ids, [(W, False), (W2, True)])  # Q and the duplicate are left out
        self.assertTrue(all(x["bug"] == "9.10-ahri-W" for x in got))
        self.assertTrue(all(x["id"] == x["input"]["id"] and x["kind"] == "real" for x in got))

    def test_translation_carries_english_beside(self):
        zh = [rec(W2, "keyTooltip", "other", locale="zh_cn", text="造成10伤害"), rec(W, "keyTooltip", "W", locale="zh_cn")]
        en = [rec(W2, "keyTooltip", "other"), rec(W, "keyTooltip", "W")]
        with tempfile.TemporaryDirectory() as d:
            write(d, "zh_cn", zh, LINES)
            write(d, "en_us", en, LINES)
            got = R.bug_lines(bug(locale="zh_cn"), d)
        own = [x for x in got if x["own_record"]]
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]["input"]["text"], "造成10伤害")
        self.assertEqual(own[0]["input"]["english"]["text"], "Deals 10 damage.")
        self.assertTrue(all("english" in x["input"] for x in got))

    def test_wrong_build_stops(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "en_us", [rec(W2, "keyTooltip", "other")], LINES)
            b = bug()
            b["prefix_cdragon_version"] = "other build"
            with self.assertRaises(SystemExit):
                R.bug_lines(b, d)

    def test_missing_own_record_raises(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "en_us", [rec(W, "keyTooltip", "W")], LINES)
            with self.assertRaises(ValueError):
                R.bug_lines(bug(), d)


if __name__ == "__main__":
    unittest.main()
