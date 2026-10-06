"""Tests for scripts/baseline.py (no network). Run from the project root:

    python3 -m unittest discover -s tests
"""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import baseline as B  # noqa: E402

ID = "16.18:en_us:ahri:Characters/Ahri/Spells/AhriQAbility/AhriQ:keyTooltip"


def inp(text="Deals @TotalDamage@ magic damage.", placeholders=None, spell=None, ability=None, typed=None,
        id_=ID, **extra):
    out = {"id": id_, "champion": "Ahri", "slot": "Q", "text_field": "keyTooltip", "ranks": [1, 2, 3],
           "text": text, "filled": text,
           "spell": {"spell": "AhriQ", "slot": "Q", **(spell or {})}}
    if placeholders:
        out["placeholders"] = placeholders
    if ability:
        out["ability"] = ability
    if typed:
        out["typed_numbers"] = typed
    out.update(extra)
    return out


def typed(text, value, raw=None):
    raw = raw or str(value)
    s = text.index(raw)
    return [{"value": value, "text": raw, "start": s, "end": s + len(raw)}]


def calc_ph(value, parts, tooltip_only=False, **extra):
    f = {"parts": parts, **extra}
    if tooltip_only:
        f["tooltip_only"] = True
    return {"kind": "calculation", "value": value, "formula": f}


def tooltip_flags(i):
    return [f for f in B.check_input(i) if f["check"] == "tooltip_calc"]


class TypedNumbers(unittest.TestCase):
    def check(self, text, value, raw=None, **spell):
        return [f for f in B.check_input(inp(text, spell=spell, typed=typed(text, value, raw)))
                if f["check"] == "typed_number"]

    def test_number_in_the_data_is_not_flagged(self):
        self.assertEqual(self.check("Slows for 2 seconds.", 2, data_values={"SlowDuration": 2}), [])

    def test_number_in_no_value_is_flagged_with_its_offsets(self):
        text = "Slows for 3 seconds."
        flags = self.check(text, 3, data_values={"SlowDuration": 2})
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f["start"], f["end"]), (10, 11))
        self.assertEqual((f["id"], f["locale"], f["text_field"]), (ID, "en_us", "keyTooltip"))
        self.assertIn("3", f["names"])

    def test_any_rank_and_percent_scales(self):
        self.assertEqual(self.check("Hits 60 times.", 60, effects={"Effect1Amount": [40, 50, 60]}), [])
        self.assertEqual(self.check("Slows by 30%.", 30, "30%", data_values={"Slow": -0.3}), [])
        self.assertEqual(self.check("Takes 0.5 seconds.", 0.5, data_values={"X": 50}), [])

    def test_rounding_only_within_two_percent(self):
        self.assertEqual(self.check("Heals 33% of it.", 33, "33%", data_values={"X": 0.333}), [])
        self.assertEqual(len(self.check("Lasts 2 seconds.", 2, data_values={"X": 2.4})), 1)

    def test_no_millisecond_scale(self):
        self.assertEqual(len(self.check("Lasts 1 second.", 1, data_values={"X": 1000})), 1)

    def test_ranks_are_not_values(self):
        self.assertEqual(len(self.check("Hits 3 times.", 3, data_values={"X": 7})), 1)

    def test_values_of_calculations_level_up_and_other_spells_count(self):
        text = "Lasts 9 seconds."
        t = typed(text, 9)
        for kw in ({"spell": {"calculations": {"C": {"parts": [{"dv": "D"}], "multiplier": 9}}}},
                   {"spell": {"level_up": [["Duration", "D", "7/8/9"]]}},
                   {"ability": [{"spell": "AhriQMissile", "slot": "Q-form", "stats": {"Cooldown": 9}}]},
                   {"placeholders": {"X": {"kind": "data_value", "value": "9"}}}):
            with self.subTest(kw=kw):
                self.assertEqual(B.check_typed_numbers(inp(text, typed=t, **kw)), [])

    def test_names_in_formulas_are_not_values(self):
        text = "Lasts 4 seconds."
        i = inp(text, typed=typed(text, 4), spell={"calculations": {"C": {"parts": [{"dv": "Damage4"}]}}})
        self.assertEqual(len(B.check_typed_numbers(i)), 1)


class Names(unittest.TestCase):
    def test_affixes(self):
        self.assertEqual(B.base_name("NetDamageTooltip"), ("netdamage", True))
        self.assertEqual(B.base_name("TooltipManaRefund"), ("manarefund", True))
        self.assertEqual(B.base_name("Tooltip_WQMoveSpeed"), ("wqmovespeed", True))
        self.assertEqual(B.base_name("ChampionHealTT"), ("championheal", True))
        self.assertEqual(B.base_name("TotalDamageTooltip2"), ("totaldamagetooltip2", False))  # no game name has this
        self.assertEqual(B.base_name("SlowAmount2Tooltip"), ("slowamount2", True))
        self.assertEqual(B.base_name("Damage2"), ("damage2", False))
        self.assertEqual(B.base_name("Tooltip"), ("tooltip", False))

    def test_token_name(self):
        self.assertEqual(B.token_name("spell.AhriQ:TotalDamage*100"), "TotalDamage")
        self.assertEqual(B.token_name("Spell.X:Y"), "Y")
        self.assertEqual(B.token_name("Slow*-100"), "Slow")


class TooltipCalcs(unittest.TestCase):
    GAMEPLAY = {"Damage": {"parts": [{"dv": "Base"}, {"stat": "AP", "coef": 0.8}], "value": "40/60/80 (+80% AP)"}}

    def test_name_rule_calculation(self):
        ph = {"DamageTooltip": calc_ph("40/60/80 (+60% AP)", [{"dv": "Base"}, {"stat": "AP", "coef": 0.6}], True)}
        i = inp("Deals @DamageTooltip@.", ph, {"data_values": {"Base": [40, 60, 80]}, "calculations": self.GAMEPLAY})
        flags = tooltip_flags(i)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["placeholder"], "DamageTooltip")
        self.assertIn("name", flags[0]["rule"].split("+"))
        self.assertIn("copy", flags[0]["rule"].split("+"))  # same parts, other numbers

    def test_same_value_is_not_flagged(self):
        ph = {"DamageTooltip": calc_ph("40/60/80 (+80% AP)", [{"dv": "Base"}, {"stat": "AP", "coef": 0.8}], True)}
        i = inp("Deals @DamageTooltip@.", ph, {"data_values": {"Base": [40, 60, 80]}, "calculations": self.GAMEPLAY,
                                               "coefficients": {"mCoefficient": 0.8}})
        self.assertEqual(tooltip_flags(i), [])

    def test_gameplay_calculation_shown_is_not_checked_by_name(self):
        ph = {"Damage": calc_ph("1", [1])}
        i = inp("Deals @Damage@.", ph, {"calculations": {"DamageTooltip": {"parts": [2], "value": "2",
                                                                            "tooltip_only": True}}})
        self.assertEqual(tooltip_flags(i), [])

    def test_unresolved_side_is_skipped_and_counted(self):
        ph = {"DamageTooltip": calc_ph("1", [{"dv": "Base"}], True)}
        g = {"Damage": {"parts": [{"dv": "Base"}], "value": "unresolved: no data"}}
        skipped = B.Counter()
        self.assertEqual(B.check_input(inp("@DamageTooltip@", ph, {"calculations": g}), skipped=skipped), [])
        self.assertEqual(skipped["name"], 1)

    def test_shown_gameplay_calculation_is_compared(self):
        # The gameplay calculation is shown too, so it is only in the placeholders, and its formula
        # may carry no value of its own: the value its placeholder shows is used.
        ph = {"DamageTooltip": calc_ph("40 (+60% AP)", [40, {"stat": "AP", "coef": 0.6}], True),
              "Damage": calc_ph("40 (+80% AP)", [40, {"stat": "AP", "coef": 0.8}])}
        flags = tooltip_flags(inp("Deals @DamageTooltip@, really @Damage@.", ph))
        self.assertEqual([(f["placeholder"], f["value_name"]) for f in flags], [("DamageTooltip", "Damage")])
        self.assertEqual(set(flags[0]["rule"].split("+")), {"name", "copy"})

    def test_name_rule_data_value_and_its_scale(self):
        ph = {"EnergyTooltip": {"kind": "data_value", "value": "80"}}
        spell = {"data_values": {"Energy": 100, "EnergyTooltip": 80}}
        flags = tooltip_flags(inp("Restores @EnergyTooltip@ Energy.", ph, spell))
        self.assertEqual([(f["placeholder"], f["value_name"], f["rule"]) for f in flags],
                         [("EnergyTooltip", "Energy", "name")])
        spell = {"data_values": {"Energy": 0.8, "EnergyTooltip": 80}}
        self.assertEqual(tooltip_flags(inp("Restores @EnergyTooltip@ Energy.", ph, spell)), [])

    def test_name_rule_data_value_read_by_tooltip_only_calculation(self):
        ph = {"HealCalc": calc_ph("12/18/24", [{"dv": "BaseHealTooltip"}], True)}
        spell = {"data_values": {"BaseHeal": [10, 15, 20], "BaseHealTooltip": [12, 18, 24]}}
        flags = tooltip_flags(inp("Heals @HealCalc@.", ph, spell))
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0]["placeholder"], flags[0]["value_name"]), ("HealCalc", "BaseHealTooltip"))

    def test_value_in_another_spell_of_the_ability(self):
        ph = {"DamageTooltip": calc_ph("2", [2], True)}
        ab = [{"spell": "AhriQMissile", "slot": "Q-form", "calculations": {"Damage": {"parts": [1], "value": "1"}}}]
        flags = tooltip_flags(inp("@DamageTooltip@", ph, ability=ab))
        self.assertEqual(flags[0]["value_name"], "Damage")

    def test_ratio_rule_ap_against_coefficient_fields_only(self):
        spell = {"coefficients": {"mCoefficient": 0.5}}
        ph = {"Shield": calc_ph("50 (+40% AP)", [50, {"stat": "AP", "coef": 0.4}], True)}
        flags = tooltip_flags(inp("Shields @Shield@.", ph, spell))
        self.assertEqual([f["rule"] for f in flags], ["ratio"])
        # A gameplay calculation's AP ratio does not explain it; a matching field does.
        spell2 = dict(spell, calculations={"Other": {"parts": [{"stat": "AP", "coef": 0.4}], "value": "x"}})
        self.assertEqual([f["rule"] for f in tooltip_flags(inp("Shields @Shield@.", ph, spell2))], ["ratio"])
        spell3 = {"coefficients": {"mCoefficient": 0.5, "mCoefficient2": 0.4}}
        self.assertEqual(tooltip_flags(inp("Shields @Shield@.", ph, spell3)), [])
        # Not for a calculation shown as a percent, nor for a stat that has nothing to compare with.
        ph_pct = {"Shield": calc_ph("5% (+4% per 100 AP)", [5, {"stat": "AP", "coef": 0.04}], True, percent=True)}
        self.assertEqual(tooltip_flags(inp("Shields @Shield@.", ph_pct, spell)), [])
        ph_hp = {"Shield": calc_ph("50 (+40% bonus health)", [50, {"stat": "bonus health", "coef": 0.4}], True)}
        self.assertEqual(tooltip_flags(inp("Shields @Shield@.", ph_hp, spell)), [])
        # Default coefficient fields (0 and 1) say nothing, and a ratio of 0 or 1 is not checked.
        self.assertEqual(tooltip_flags(inp("Shields @Shield@.", ph, {"coefficients": {"mCoefficient": 1}})), [])
        ph_one = {"Shield": calc_ph("50 (+100% AP)", [50, {"stat": "AP", "coef": 1}], True)}
        self.assertEqual(tooltip_flags(inp("Shields @Shield@.", ph_one, spell)), [])

    def test_ratio_rule_ad_against_gameplay_ad_parts(self):
        ph = {"Hit": calc_ph("50 (+60% bonus AD)", [50, {"stat": "bonus AD", "coef": 0.6}], True)}
        # The coefficient fields name no stat, so they are not compared with an AD ratio.
        self.assertEqual(tooltip_flags(inp("@Hit@", ph, {"coefficients": {"mCoefficient": 0.8}})), [])
        other_stat = {"Real": {"parts": [{"stat": "AD", "coef": 0.8}], "value": "x"}}
        self.assertEqual(tooltip_flags(inp("@Hit@", ph, {"calculations": other_stat})), [])
        same_stat = {"Real": {"parts": [{"stat": "bonus AD", "coef": 0.8}], "value": "x"}}
        flags = tooltip_flags(inp("@Hit@", ph, {"calculations": same_stat}))
        self.assertEqual([f["rule"] for f in flags], ["ratio"])
        same_stat["Real2"] = {"parts": [{"stat": "bonus AD", "coef": 0.6}], "value": "y"}
        self.assertEqual(tooltip_flags(inp("@Hit@", ph, {"calculations": same_stat})), [])

    def test_copy_rule_with_another_name(self):
        ph = {"ShownDamage": calc_ph("3", [{"dv": "BaseTooltip"}], True)}
        spell = {"data_values": {"Base": 2, "BaseTooltip": 3},
                 "calculations": {"RealDamage": {"parts": [{"dv": "Base"}], "value": "2"}}}
        flags = tooltip_flags(inp("@ShownDamage@", ph, spell))
        self.assertIn("copy", flags[0]["rule"].split("+"))
        self.assertEqual(flags[0]["placeholder"], "ShownDamage")

    def test_copy_rule_term_left_out(self):
        ph = {"ShownDamage": calc_ph("2", [{"dv": "Base"}], True)}
        spell = {"data_values": {"Base": 2},
                 "calculations": {"RealDamage": {"parts": [{"dv": "Base"}, {"stat": "AD", "coef": 1}],
                                                 "value": "2 (+100% AD)"}}}
        flags = tooltip_flags(inp("@ShownDamage@", ph, spell))
        self.assertEqual([f["rule"] for f in flags], ["copy"])
        self.assertIn("left out", flags[0]["detail"])

    def test_copy_rule_needs_a_link(self):
        # Two marks with the same shape and no data values or shared name (Kindred, 16.18).
        ph = {"QMarkBonus": calc_ph("1", [{"stat": "stacks", "coef": 0.01}], True)}
        spell = {"calculations": {"WMarkBonus": {"parts": [{"stat": "stacks", "coef": 0.02}], "value": "2"}}}
        self.assertEqual(tooltip_flags(inp("@QMarkBonus@", ph, spell)), [])
        ph = {"MarkBonusTooltip": calc_ph("1", [{"stat": "stacks", "coef": 0.01}], True)}
        spell = {"calculations": {"MarkBonusTotal": {"parts": [{"stat": "stacks", "coef": 0.02}], "value": "2"}}}
        self.assertEqual([f["rule"] for f in tooltip_flags(inp("@MarkBonusTooltip@", ph, spell))], ["copy"])

    def test_copy_rule_needs_tooltip_only(self):
        ph = {"ShownDamage": calc_ph("3", [3])}
        spell = {"calculations": {"RealDamage": {"parts": [2], "value": "2"}}}
        self.assertEqual(tooltip_flags(inp("@ShownDamage@", ph, spell)), [])

    def test_stale_rule(self):
        own = {"spell": "AhriQRecast", "slot": "Q-form", "data_values": {"Range": 500}}
        ab = [{"spell": "AhriQ", "slot": "Q", "data_values": {"Range": 600}}]
        i = inp("Range @Range@.", {"Range": {"kind": "data_value", "value": "500"}}, ability=ab)
        i["spell"] = own
        flags = tooltip_flags(i)
        self.assertEqual([(f["rule"], f["placeholder"]) for f in flags], [("stale", "Range")])
        ab[0]["data_values"]["Range"] = 500
        self.assertEqual(tooltip_flags(i), [])

    def test_of_token_reads_the_named_spell(self):
        ab = [{"spell": "AhriQMissile", "slot": "Q-form", "data_values": {"Speed": 300}}]
        ph = {"spell.AhriQMissile:Speed": {"kind": "data_value", "value": "300", "of": "AhriQMissile"}}
        i = inp("@spell.AhriQMissile:Speed@", ph, {"data_values": {"Speed": 400}}, ab)
        flags = tooltip_flags(i)
        self.assertEqual([(f["rule"], f["placeholder"]) for f in flags], [("stale", "Speed")])

    def test_translated_input_gets_no_flags(self):
        ph = {"EnergyTooltip": {"kind": "data_value", "value": "80"}}
        i = inp("@EnergyTooltip@ 3", ph, {"data_values": {"Energy": 100, "EnergyTooltip": 80}},
                typed=[{"value": 3, "text": "3", "start": 16, "end": 17}],
                id_=ID.replace("en_us", "fr_fr"))
        self.assertEqual(B.check_input(i), [])
        i["id"] = ID
        self.assertEqual(len(B.check_input(i)), 2)

    def test_does_not_change_its_input(self):
        ph = {"DamageTooltip": calc_ph("2", [{"dv": "BaseTooltip"}], True)}
        i = inp("@DamageTooltip@", ph, {"data_values": {"Base": 1, "BaseTooltip": 2},
                                        "calculations": {"Damage": {"parts": [{"dv": "Base"}], "value": "1"}}})
        before = copy.deepcopy(i)
        B.check_input(i)
        self.assertEqual(i, before)


class DevMeasure(unittest.TestCase):
    def test_caught(self):
        flag = {"check": "tooltip_calc", "placeholder": "TotalDamage", "value_name": "TotalDamage"}
        self.assertTrue(B.caught({"rule": "stat_ratio", "change": {"calc": "TotalDamage"}}, [flag]))
        self.assertTrue(B.caught({"rule": "drop_term", "change": {"calc": "totaldamage"}}, [flag]))
        self.assertFalse(B.caught({"rule": "stat_ratio", "change": {"calc": "Other"}}, [flag]))
        moved = {"check": "tooltip_calc", "placeholder": "Other.0", "value_name": "Other"}
        self.assertTrue(B.caught({"rule": "other_value", "change": {"points_at": "Other"}}, [moved]))
        # A changed data value is caught through a shown calculation that reads it.
        i = inp(placeholders={"TotalDamage": calc_ph("1", [{"dv": "BaseDamage"}])})
        entry = {"rule": "base_values", "change": {"data_value": "BaseDamage"}, "input": i}
        self.assertEqual(B.planted_targets(entry), {"basedamage", "totaldamage"})
        self.assertTrue(B.caught(entry, [flag]))
        # A flag on another placeholder whose value_name is the changed value is not a catch.
        other = {"check": "tooltip_calc", "placeholder": "Shown", "value_name": "TotalDamage"}
        self.assertFalse(B.caught({"rule": "stat_ratio", "change": {"calc": "TotalDamage"}}, [other]))
        tflag = {"check": "typed_number", "start": 10}
        self.assertTrue(B.caught({"rule": "typed_number", "change": {"start": 10}}, [tflag]))
        self.assertFalse(B.caught({"rule": "typed_number", "change": {"start": 11}}, [tflag]))
        self.assertFalse(B.caught({"rule": "damage_type", "change": {"start": 10}}, [tflag]))


class Cli(unittest.TestCase):
    def run_main(self, *argv):
        buf = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", ["baseline.py", *argv]), contextlib.redirect_stdout(buf):
            B.main()
        return buf.getvalue()

    def test_planted_set_and_report_are_deterministic(self):
        text = "Slows for 3 seconds."
        i = inp(text, spell={"data_values": {"SlowDuration": 2}}, typed=typed(text, 3))
        fr = inp(text, id_=ID.replace("en_us", "fr_fr"), typed=typed(text, 3))
        entries = [{"id": "dev-001", "kind": "typed_number", "rule": "typed_number", "locale": "en_us",
                    "record_id": ID, "change": {"start": 10}, "answer": "", "input": i},
                   {"id": "dev-002", "kind": "translation", "rule": "typed_number", "locale": "fr_fr",
                    "record_id": fr["id"], "change": {"start": 10}, "answer": "", "input": fr}]
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "dev.jsonl"
            src.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
            outs = []
            for n in (1, 2):
                out = Path(d) / f"flags{n}.jsonl"
                printed = self.run_main(str(src), "--out", str(out), "--dev-report")
                outs.append(out.read_bytes())
            self.assertEqual(outs[0], outs[1])
            flags = [json.loads(x) for x in outs[0].decode().splitlines()]
            self.assertEqual([(f["planted_id"], f["check"]) for f in flags], [("dev-001", "typed_number")])
            self.assertIn("1 not in English", printed)
            self.assertIn("typed_number / typed_number: 1 of 1", printed)
            self.assertIn("translation / typed_number (fr_fr): 0 of 1", printed)

    def test_inputs_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "16.18.en_us.jsonl"
            src.write_text(json.dumps(inp()) + "\n", encoding="utf-8")
            out = Path(d) / "f.jsonl"
            printed = self.run_main(str(src), "--out", str(out))
            self.assertIn("1 inputs, 0 not in English (not checked), 0 flags", printed)
            self.assertIn("pairs not compared (a side unresolved): 0", printed)
            self.assertEqual(out.read_text(), "")


if __name__ == "__main__":
    unittest.main()
