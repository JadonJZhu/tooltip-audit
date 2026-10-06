"""Tests for scripts/inputs.py (no network). Run from the project root:

    python3 -m unittest discover -s tests
"""

import builtins
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
import inputs as I  # noqa: E402
from resolve_tooltips import fnv1a  # noqa: E402

AHRI_Q = "Characters/Ahri/Spells/AhriQAbility/AhriQ"
AHRI_QM = "Characters/Ahri/Spells/AhriQAbility/AhriQMissile"
AHRI_P = "Characters/Ahri/Spells/AhriPassiveAbility/AhriPassive"


def key(path):
    return f"ahri:{path}"


def placeholder(token, kind="calculation", display=None, **extra):
    ph = {"token": token, "name": extra.pop("name", token.split(":")[-1].split("*")[0]), "kind": kind,
          "status": "resolved" if display else "unresolved", "start": 0, "end": 0}
    if display:
        ph.update(ranks=[1, 2, 3], display=display)
    ph.update(extra)
    return ph


def record(path=AHRI_Q, field="keyTooltip", text="Deals @TotalDamage@ magic damage.", phs=None, locale="en_us",
           **extra):
    rec = {"patch": "16.19", "locale": locale, "cdragon_version": "16.19.1", "champion": "Ahri",
           "champion_folder": "ahri", "spell_path": path, "script_name": path.rsplit("/", 1)[-1], "slot": "Q",
           "text_field": field, "loc_key": "Spell_AhriQ_Tooltip", "ranks": [1, 2, 3],
           "rank_source": "LevelUp list", "raw_text": text, "plain_text": text,
           "placeholders": phs if phs is not None else
           [placeholder("TotalDamage", display=["40 (+50% AP)", "65 (+50% AP)", "90 (+50% AP)"])],
           "typed_numbers": [], "spell_context": key(path)}
    rec.update(extra)
    return rec


def line(path=AHRI_Q, label="Damage", **extra):
    ln = {"patch": "16.19", "locale": "en_us", "champion_folder": "ahri", "has_text": True, "key": key(path),
          "spell_path": path, "script_name": path.rsplit("/", 1)[-1], "slot": "Q", "ranks": [1, 2, 3],
          "rank_source": "LevelUp list", "coefficients": {"mCoefficient": 0.5},
          "data_values": {"BaseDamage": [40, 65, 90], "Range": [900, 900, 900]},
          "effect_amounts": {}, "spell_stats": {"Cooldown": [7, 7, 7], "Cost": [55, 65, 75]},
          "calculations": {
              "TotalDamage": {
                  "mSimpleTooltipCalculationDisplay": 6,
                  "mFormulaParts": [
                      {"mDataValue": "BaseDamage", "__type": "NamedDataValueCalculationPart"},
                      {"mCoefficient": 0.5, "mStat": 0, "__type": "StatByCoefficientCalculationPart", "stat": "AP"}],
                  "__type": "GameCalculation",
                  "result": {"status": "resolved", "ranks": [1, 2, 3],
                             "display": ["40 (+50% AP)", "65 (+50% AP)", "90 (+50% AP)"]}},
              "OtherCalc": {
                  "mFormulaParts": [{"mNumber": 2, "__type": "NumberCalculationPart"}],
                  "__type": "GameCalculation", "tooltipOnly": True,
                  "result": {"status": "resolved", "ranks": [1, 2, 3], "display": ["2", "2", "2"]}}},
          "level_up": {"levelCount": 3, "rows": [
              {"type": "BaseDamage", "reads": "BaseDamage", "nameOverride": "Spell_ListType_Damage", "label": label,
               "value": {"display": ["40", "65", "90"]}}]},
          "group": {"id": "Characters/Ahri/Spells/AhriQAbility", "source": "AbilityObject",
                    "joined_by": "AbilityObject", "spells": [key(AHRI_QM)]},
          "refers_to": []}
    ln.update(extra)
    return ln


def missile_line(**extra):
    ln = {"key": key(AHRI_QM), "spell_path": AHRI_QM, "script_name": "AhriQMissile", "slot": "Q-form",
          "ranks": [1, 2, 3], "coefficients": {"mCoefficient": 0.4}, "data_values": {},
          "effect_amounts": {"Effect1Amount": [50, 80, 110]}, "spell_stats": {"CastRange": [1000, 1000, 1000]},
          "calculations": {}, "level_up": None,
          "group": {"id": "Characters/Ahri/Spells/AhriQAbility", "source": "AbilityObject",
                    "joined_by": "AbilityObject", "spells": [key(AHRI_Q)]},
          "refers_to": []}
    ln.update(extra)
    return ln


def passive_line():
    return {"key": key(AHRI_P), "spell_path": AHRI_P, "script_name": "AhriPassive", "slot": "P", "ranks": [1],
            "rank_source": "none (one rank)", "coefficients": {}, "data_values": {"Heal": [9]},
            "effect_amounts": {}, "spell_stats": {}, "calculations": {}, "level_up": None, "group": None,
            "refers_to": []}


def lines():
    return {ln["key"]: ln for ln in (line(), missile_line(), passive_line())}


class CheckedSet(unittest.TestCase):
    def test_skips_duplicates_and_champion_summary_text(self):
        recs = [record(), record(field="keyTooltipSimple"),
                record(path=AHRI_QM, duplicate_of=AHRI_Q), record(field="passiveToolTip")]
        out = I.build_inputs(recs, list(lines().values()))
        self.assertEqual([i["text_field"] for i in out], ["keyTooltip", "keyTooltipSimple"])

    def test_id(self):
        inp = I.build_input(record(), lines())
        self.assertEqual(inp["id"], f"16.19:en_us:ahri:{AHRI_Q}:keyTooltip")


class Values(unittest.TestCase):
    def test_once_collapses_only_identical_ranks(self):
        self.assertEqual(I.once([7, 7, 7]), 7)
        self.assertEqual(I.once([7, 7, 6]), [7, 7, 6])
        self.assertIsNone(I.once([None, None]))

    def test_joined(self):
        self.assertEqual(I.joined(["40 (+50% AP)", "65 (+50% AP)"]), "40/65 (+50% AP)")
        self.assertEqual(I.joined(["20%", "30%"]), "20%/30%")
        self.assertEqual(I.joined(["5 (+1% AP)", "5 (+2% AP)"]), "5 (+1% AP)/5 (+2% AP)")
        self.assertEqual(I.joined(["55% to 70% (by level)"] * 3), "55% to 70% (by level)")

    def test_a_value_that_differs_by_rank_is_kept_in_full(self):
        inp = I.build_input(record(), lines())
        self.assertEqual(inp["spell"]["data_values"], {"BaseDamage": [40, 65, 90], "Range": 900})
        self.assertEqual(inp["spell"]["stats"], {"Cooldown": 7, "Cost": [55, 65, 75]})


class Parts(unittest.TestCase):
    def test_short_forms(self):
        self.assertEqual(I.part({"mNumber": 2, "__type": "NumberCalculationPart"}), 2)
        self.assertEqual(I.part({"mDataValue": "{03da00f9}", "data_value_name": "BaseDamage",
                                 "__type": "NamedDataValueCalculationPart"}), {"dv": "BaseDamage"})
        self.assertEqual(I.part({"mStat": 2, "mStatFormula": 2, "mDataValue": "Ratio", "stat": "bonus AD",
                                 "__type": "StatByNamedDataValueCalculationPart"}), {"stat": "bonus AD", "dv": "Ratio"})
        self.assertEqual(I.part({"mEffectIndex": 3, "effect": "Effect3Amount", "__type": "EffectValueCalculationPart"}),
                         {"effect": "Effect3Amount"})

    def test_other_types_keep_every_field(self):
        p = {"mLevel1Value": 0.55, "mIconKey": "x", "__type": "ByCharLevelBreakpointsCalculationPart",
             "mBreakpoints": [{"mLevel": 6, "mAdditionalBonusAtThisLevel": 0.05, "__type": "Breakpoint"}]}
        self.assertEqual(I.part(p), {"type": "ByCharLevelBreakpoints", "Level1Value": 0.55,
                                     "Breakpoints": [{"Level": 6, "AdditionalBonusAtThisLevel": 0.05}]})
        hashed = {"{91d404a5}": "Level1MS", "__type": "{4ce08984}"}
        self.assertEqual(I.part(hashed), {"type": "{4ce08984}", "{91d404a5}": "Level1MS"})
        start_end = {"StartDataValue": "{11111111}", "start_data_value_name": "Start", "__type": "{ee18a47b}"}
        self.assertEqual(I.part(start_end), {"type": "{ee18a47b}", "StartDataValue": "Start"})

    def test_calculation_fields(self):
        c = {"mMultiplier": {"mDataValue": "Ticks", "__type": "NamedDataValueCalculationPart"},
             "mModifiedGameCalculation": "Base", "tooltipOnly": True, "mDisplayAsPercent": True,
             "mSimpleTooltipCalculationDisplay": 6, "__type": "GameCalculationModified",
             "result": {"status": "unresolved", "reason": "nonlinear"}}
        self.assertEqual(I.calculation(c), {"type": "GameCalculationModified", "multiplier": {"dv": "Ticks"},
                                            "modifies": "Base", "tooltip_only": True, "percent": True,
                                            "value": "unresolved: nonlinear"})


class Placeholders(unittest.TestCase):
    def test_value_formula_and_filled_text(self):
        inp = I.build_input(record(), lines())
        self.assertEqual(inp["filled"], "Deals 40/65/90 (+50% AP) magic damage.")
        self.assertEqual(inp["placeholders"]["TotalDamage"],
                         {"kind": "calculation", "value": "40/65/90 (+50% AP)",
                          "formula": {"parts": [{"dv": "BaseDamage"}, {"stat": "AP", "coef": 0.5}],
                                      "value": "40/65/90 (+50% AP)"}})
        # A calculation a placeholder shows is not written again under the spell.
        self.assertEqual(list(inp["spell"]["calculations"]), ["OtherCalc"])
        self.assertEqual(inp["spell"]["calculations"]["OtherCalc"],
                         {"parts": [2], "tooltip_only": True, "value": "2"})

    def test_unresolved_placeholder_stays_in_the_text(self):
        rec = record(text="Bonus @f1@ and @TotalDamage@.",
                     phs=[placeholder("f1", kind="script_variable", reason="script variable (fN)"),
                          placeholder("TotalDamage", display=["1", "2", "3"])])
        inp = I.build_input(rec, lines())
        self.assertEqual(inp["filled"], "Bonus @f1@ and 1/2/3.")
        self.assertEqual(inp["placeholders"]["f1"], {"kind": "script_variable", "unresolved": "script variable (fN)"})

    def test_calculation_found_by_case_and_by_hash(self):
        ln = line()
        ln["calculations"] = {fnv1a("TotalDamage"): ln["calculations"]["TotalDamage"]}
        ln["calculations"][fnv1a("TotalDamage")]["known_name"] = "TotalDamage"
        rec = record(text="@totaldamage@", phs=[placeholder("totaldamage", display=["1", "2", "3"])])
        inp = I.build_input(rec, {**lines(), ln["key"]: ln})
        f = inp["placeholders"]["totaldamage"]["formula"]
        self.assertEqual(f["parts"][1], {"stat": "AP", "coef": 0.5})
        self.assertNotIn("known_name", f)
        self.assertNotIn("calculations", inp["spell"])

    def test_other_spell_token(self):
        ln = missile_line(calculations={"MissileDamage": {
            "mFormulaParts": [{"mEffectIndex": 1, "effect": "Effect1Amount", "__type": "EffectValueCalculationPart"}],
            "__type": "GameCalculation", "result": {"status": "resolved", "display": ["50", "80", "110"]}}})
        rec = record(text="@Spell.AhriQMissile:MissileDamage@",
                     phs=[placeholder("Spell.AhriQMissile:MissileDamage", name="MissileDamage",
                                      owner_spell="AhriQMissile", display=["50", "80", "110"])],
                     referenced_spells=[key(AHRI_QM)])
        inp = I.build_input(rec, {**lines(), ln["key"]: ln})
        e = inp["placeholders"]["Spell.AhriQMissile:MissileDamage"]
        self.assertEqual(e["of"], "AhriQMissile")
        # The formula keeps its own value, so a checker can compare it with another calculation.
        self.assertEqual(e["formula"], {"parts": [{"effect": "Effect1Amount"}], "value": "50/80/110"})
        # Its spell is shown once, in the ability, without the calculation already shown.
        self.assertNotIn("referenced", inp)
        self.assertNotIn("calculations", inp["ability"][0])


class Spells(unittest.TestCase):
    def test_ability_level_up_and_referenced(self):
        own = line(refers_to=[key(AHRI_P)])
        inp = I.build_input(record(), {**lines(), own["key"]: own})
        self.assertEqual(inp["spell"]["level_up"], [["Damage", "BaseDamage", "40/65/90"]])
        self.assertEqual(inp["ability"], [{"spell": "AhriQMissile", "slot": "Q-form",
                                           "effects": {"Effect1Amount": [50, 80, 110]},
                                           "stats": {"CastRange": 1000}, "coefficients": {"mCoefficient": 0.4}}])
        self.assertEqual(inp["referenced"], [{"spell": "AhriPassive", "slot": "P", "ranks": [1],
                                              "rank_source": "none (one rank)", "data_values": {"Heal": 9}}])

    def test_level_up_shows_value_times_multiplier(self):
        own = line()
        own["level_up"]["rows"][0].update(multiplier=100, value={"display": ["0.1", "0.2", "0.3"]},
                                          value_times_multiplier={"display": ["10", "20", "30"]})
        inp = I.build_input(record(), {**lines(), own["key"]: own})
        self.assertEqual(inp["spell"]["level_up"], [["Damage", "BaseDamage", "10/20/30"]])

    def test_group_rule_and_missing_spells(self):
        own = line(group={"id": "x", "source": "slot spell", "joined_by": "slot spell",
                          "spells": [key(AHRI_QM), "ahri:Characters/Ahri/Spells/Gone"]})
        qm = missile_line(group={"id": "x", "source": "slot spell", "joined_by": "script-name prefix", "spells": []})
        inp = I.build_input(record(), {**lines(), own["key"]: own, qm["key"]: qm})
        self.assertEqual(inp["spell"]["joined_by"], "slot spell")
        self.assertEqual(inp["ability"][0]["joined_by"], "script-name prefix")
        self.assertEqual(inp["spells_not_in_file"], ["ahri:Characters/Ahri/Spells/Gone"])

    def test_record_flags(self):
        rec = record(field="keyTooltipExtended", extended_text_hidden_in_game=True,
                     rank_source="none (one rank)", ranks=[1], includes=["Spell_X_Name"])
        inp = I.build_input(rec, lines())
        self.assertTrue(inp["extended_text_hidden_in_game"])
        self.assertEqual(inp["rank_source"], "none (one rank)")
        self.assertEqual(inp["includes"], ["Spell_X_Name"])
        # The spell's own ranks are shown when they differ from the record's.
        self.assertEqual(inp["spell"]["ranks"], [1, 2, 3])
        self.assertNotIn("rank_source", I.build_input(record(), lines()))


class ModifiedCopies(unittest.TestCase):
    def test_rebuilds_from_what_it_is_handed_without_reading_files(self):
        base = lines()
        changed = copy.deepcopy(base)
        changed[key(AHRI_Q)]["calculations"]["TotalDamage"]["mFormulaParts"][1]["mCoefficient"] = 0.9
        rec = record()
        rec["placeholders"][0]["display"] = ["40 (+90% AP)", "65 (+90% AP)", "90 (+90% AP)"]
        with unittest.mock.patch.object(builtins, "open", side_effect=AssertionError("read a file")), \
                unittest.mock.patch.object(Path, "read_text", side_effect=AssertionError("read a file")):
            inp = I.build_input(rec, changed)
        self.assertEqual(inp["placeholders"]["TotalDamage"]["formula"]["parts"][1], {"stat": "AP", "coef": 0.9})
        self.assertEqual(inp["filled"], "Deals 40/65/90 (+90% AP) magic damage.")
        # The original copies are untouched.
        self.assertEqual(base[key(AHRI_Q)]["calculations"]["TotalDamage"]["mFormulaParts"][1]["mCoefficient"], 0.5)
        self.assertEqual(I.build_input(record(), base)["filled"], "Deals 40/65/90 (+50% AP) magic damage.")


class ReviewFixes(unittest.TestCase):
    def test_input_shares_no_object_with_its_sources(self):
        by = lines()
        rec = record(varies_by_rank=["a"], typed_numbers=[{"value": 3, "text": "3", "start": 0, "end": 1,
                                                            "context": "[3] fox-fires"}])
        inp = I.build_input(rec, by)
        by[key(AHRI_Q)]["data_values"]["BaseDamage"][0] = 999
        by[key(AHRI_QM)]["effect_amounts"]["Effect1Amount"][0] = 999
        rec["varies_by_rank"].append("b")
        rec["typed_numbers"][0]["value"] = 9
        self.assertEqual(inp["spell"]["data_values"]["BaseDamage"], [40, 65, 90])
        self.assertEqual(inp["ability"][0]["effects"]["Effect1Amount"], [50, 80, 110])
        self.assertEqual(inp["varies_by_rank"], ["a"])
        self.assertEqual(inp["typed_numbers"][0]["value"], 3)
        inp["spell"]["coefficients"]["mCoefficient"] = 7
        self.assertEqual(by[key(AHRI_Q)]["coefficients"]["mCoefficient"], 0.5)

    def test_hashed_reference_gets_the_readable_name(self):
        own = line()
        own["calculations"]["EdgeDamage"] = {
            "mModifiedGameCalculation": fnv1a("TotalDamage"), "mMultiplier": {"mNumber": 1.5,
                                                                             "__type": "NumberCalculationPart"},
            "__type": "GameCalculationModified", "tooltipOnly": True,
            "result": {"status": "resolved", "display": ["60", "97.5", "135"]}}
        own["calculations"]["Unknown"] = {"mModifiedGameCalculation": "{0badf00d}",
                                          "__type": "GameCalculationModified"}
        rec = record(text="@TotalDamage@ or @EdgeDamage@",
                     phs=[placeholder("TotalDamage", display=["1", "2", "3"]),
                          placeholder("EdgeDamage", display=["60", "97.5", "135"])])
        inp = I.build_input(rec, {**lines(), own["key"]: own})
        self.assertEqual(inp["placeholders"]["EdgeDamage"]["formula"]["modifies"], "TotalDamage")
        self.assertEqual(inp["spell"]["calculations"]["Unknown"]["modifies"], "{0badf00d}")
        # The spell line itself still holds the hash.
        self.assertEqual(own["calculations"]["EdgeDamage"]["mModifiedGameCalculation"], fnv1a("TotalDamage"))

    def test_missing_own_spell_is_reported(self):
        inp = I.build_input(record(), {})
        self.assertEqual(inp["spells_not_in_file"], [key(AHRI_Q)])

    def test_damage_type_code_becomes_a_word(self):
        self.assertEqual(I.calculation({"DamageType": 1, "__type": "GameCalculation"}), {"damage_type": "magic"})
        self.assertEqual(I.calculation({"DamageType": 0}), {"damage_type": "physical"})
        self.assertEqual(I.calculation({"DamageType": 2}), {"damage_type": "true"})
        self.assertEqual(I.calculation({"DamageType": 5}), {"damage_type": "code 5"})

    def test_typed_numbers_are_kept_without_the_context(self):
        rec = record(text="Fires 3 orbs.", phs=[], typed_numbers=[
            {"value": 3, "text": "3", "start": 6, "end": 7, "context": "Fires [3] orbs."}])
        inp = I.build_input(rec, lines())
        self.assertEqual(inp["typed_numbers"], [{"value": 3, "text": "3", "start": 6, "end": 7}])
        self.assertEqual(inp["text"][6:7], "3")
        self.assertNotIn("typed_numbers", I.build_input(record(), lines()))


class Translations(unittest.TestCase):
    def test_english_side_by_side(self):
        en_recs = [record()]
        fr_recs = [record(locale="fr_fr", text="Inflige @TotalDamage@ degats magiques.")]
        fr_lines = {k: copy.deepcopy(v) for k, v in lines().items()}
        fr_lines[key(AHRI_Q)]["level_up"]["rows"][0]["label"] = "Degats"
        out = I.build_inputs(fr_recs, fr_lines, en_recs, list(lines().values()))
        self.assertEqual(len(out), 1)
        # The English side is always exactly its text and filled text.
        self.assertEqual(out[0]["english"], {"text": "Deals @TotalDamage@ magic damage.",
                                             "filled": "Deals 40/65/90 (+50% AP) magic damage."})

    def test_english_side_has_the_same_shape_when_the_translation_names_another(self):
        en_recs = [record()]
        fr = record(locale="fr_fr", text="Inflige @OtherCalc@.", phs=[placeholder("OtherCalc", display=["2"] * 3)])
        out = I.build_inputs([fr], lines(), en_recs, lines())
        self.assertEqual(out[0]["english"], {"text": "Deals @TotalDamage@ magic damage.",
                                             "filled": "Deals 40/65/90 (+50% AP) magic damage."})

    def test_no_english_record(self):
        out = I.build_inputs([record(locale="fr_fr")], lines(), [], {})
        self.assertTrue(out[0]["english_missing"])
        self.assertNotIn("english", out[0])


class Cli(unittest.TestCase):
    def test_writes_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            res, out = Path(d) / "resolved", Path(d) / "inputs"
            res.mkdir()
            (res / "16.19.en_us.jsonl").write_text(
                "\n".join(json.dumps(r) for r in [record(), record(field="passiveToolTip")]) + "\n")
            (res / "16.19.en_us.spells.jsonl").write_text("\n".join(json.dumps(ln) for ln in lines().values()) + "\n")
            argv = ["inputs.py", "--patch", "16.19", "--resolved-dir", str(res), "--out-dir", str(out)]
            buf = io.StringIO()
            with unittest.mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
                I.main()
            rows = [json.loads(x) for x in (out / "16.19.en_us.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertIn("1 inputs from 2 records", buf.getvalue())
            self.assertIn("tokens", buf.getvalue())
            self.assertNotIn("English", buf.getvalue())

    def test_missing_patch_says_how_to_make_it(self):
        with tempfile.TemporaryDirectory() as d:
            argv = ["inputs.py", "--patch", "9.9", "--resolved-dir", d, "--out-dir", d]
            with unittest.mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit) as cm:
                I.main()
            self.assertIn("resolve_tooltips.py --patches 9.9", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
