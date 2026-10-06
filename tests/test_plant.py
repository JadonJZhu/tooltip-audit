"""Tests for scripts/plant.py (no network). Run from the project root:

    python3 -m unittest discover -s tests

The fixture is a made-up champion, Testa, with made-up text, written to a temporary data/raw
folder the way fetch_cdragon.py saves a patch.
"""

import contextlib
import copy
import hashlib
import io
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import inputs as I  # noqa: E402
import plant as P  # noqa: E402
import resolve_tooltips as R  # noqa: E402

PATCH = "16.18"
Q = "Characters/Testa/Spells/TestaQAbility/TestaQ"
W = "Characters/Testa/Spells/TestaWAbility/TestaW"
E = "Characters/Testa/Spells/TestaEAbility/TestaE"
E2 = "Characters/Testa/Spells/TestaEAbility/TestaE2"


def dv(name, value):
    return {"name": name, "values": [value] * 7 if not isinstance(value, list) else value, "__type": "SpellDataValue"}


def number(n):
    return {"mNumber": n, "__type": "NumberCalculationPart"}


def named(name):
    return {"mDataValue": name, "__type": "NamedDataValueCalculationPart"}


def ratio(coef, stat=0, formula=0):
    p = {"mCoefficient": coef, "__type": "StatByCoefficientCalculationPart"}
    if stat:
        p["mStat"] = stat
    if formula:
        p["mStatFormula"] = formula
    return p


def row(reads, label_key="Spell_ListType_Damage"):
    return {"type": reads, "nameOverride": label_key, "__type": "TooltipInstanceListElement"}


def spell(script, dvs, calcs, key, rows=("BaseDamage",), **extra):
    return {"mScriptName": script, "__type": "SpellObject", "mSpell": {
        "DataValues": dvs, "mSpellCalculations": calcs, "cooldownTime": [10] * 7, **extra,
        "mClientData": {"mTooltipData": {"mLocKeys": {"keyTooltip": key}, "mLists": {"LevelUp": {
            "levelCount": 3, "Elements": [row(r) for r in rows]}}}}}}


SHIELD = [0, 50, 75, 100, 125, 150, 175]


def champion():
    q_calcs = {
        "TotalDamage": {"mFormulaParts": [named("BaseDamage"), ratio(0.5)], "__type": "GameCalculation"},
        "HitDamage": {"mFormulaParts": [named("BaseDamage")], "mMultiplier": number(3.0),
                      "__type": "GameCalculation"},
        "ShieldAmount": {"mFormulaParts": [named("ShieldBase"), ratio(0.2)], "__type": "GameCalculation"},
        "FlavorOnly": {"mFormulaParts": [number(7.0)], "__type": "GameCalculation", "tooltipOnly": True},
    }
    w_calcs = {"AttackDamage": {"mFormulaParts": [ratio(0.6, 2, 2), number(10.0)], "__type": "GameCalculation"}}
    e_calcs = {"BlinkDamage": {"mFormulaParts": [named("BaseDamage"), named("EchoDamage"), ratio(0.4)],
                               "__type": "GameCalculation"},
               "EchoGameplay": {"mFormulaParts": [named("EchoDamage")], "__type": "GameCalculation"}}
    e_dvs = [dv("BaseDamage", [0, 70, 100, 130, 160, 190, 220]), dv("EchoDamage", [0, 5, 10, 15, 20, 25, 30]),
             dv("EchoLevelUp", [0, 5, 10, 15, 20, 25, 30])]
    return {
        "Characters/Testa/CharacterRecords/Root": {"mCharacterName": "Testa", "__type": "CharacterRecord",
                                                   "spells": [Q, W, E],
                                                   "mAbilities": ["Characters/Testa/Spells/TestaQAbility",
                                                                  "Characters/Testa/Spells/TestaWAbility",
                                                                  "Characters/Testa/Spells/TestaEAbility"]},
        "Characters/Testa/Spells/TestaQAbility": {"mRootSpell": Q, "__type": "AbilityObject"},
        "Characters/Testa/Spells/TestaWAbility": {"mRootSpell": W, "__type": "AbilityObject"},
        "Characters/Testa/Spells/TestaEAbility": {"mRootSpell": E, "mChildSpells": [E2], "__type": "AbilityObject"},
        Q: spell("TestaQ", [dv("BaseDamage", [0, 40, 65, 90, 115, 140, 165]), dv("ShieldBase", SHIELD),
                            dv("ShieldLevelUp", SHIELD), dv("SlowAmount", 0.3), dv("SlowAmountEmpowered", 0.45),
                            dv("SlowAmount_Old", 0.4), dv("SlowDuration", 2.0)],
                 q_calcs, "Spell_TestaQ_Tooltip", rows=("BaseDamage", "ShieldLevelUp"), mCoefficient=0.5),
        W: spell("TestaW", [dv("BaseDamage", [0, 15, 25, 35, 45, 55, 65]), dv("BonusAD", [0, 10, 20, 30, 40, 50, 60]),
                            dv("Duration", 4.0)], w_calcs, "Spell_TestaW_Tooltip"),
        E: spell("TestaE", e_dvs, e_calcs, "Spell_TestaE_Tooltip", rows=("BaseDamage", "EchoLevelUp"),
                 mCoefficient=0.4),
        E2: spell("TestaE2", copy.deepcopy(e_dvs), copy.deepcopy(e_calcs), "Spell_TestaE2_Tooltip",
                  rows=("BaseDamage", "EchoLevelUp"), mCoefficient=0.4),
    }


E_TEXT = "Testa blinks and deals <magicDamage>@BlinkDamage@ magic damage</magicDamage>."
EN = {
    "spell_testaq_tooltip": ("Testa throws a stone, dealing <magicDamage>@TotalDamage@ magic damage</magicDamage>. "
                             "It then hits 3 more times for <magicDamage>@HitDamage@ magic damage</magicDamage> "
                             "each and gains a <shield>@ShieldAmount@ shield</shield>.<br><br>Enemies hit are "
                             "slowed by @SlowAmount*100@% for 2 seconds."),
    "spell_testaw_tooltip": ("Testa gains @BonusAD@ bonus Attack Damage for 4 seconds. Her next attack deals "
                             "<physicalDamage>@AttackDamage@ physical damage</physicalDamage>."),
    "spell_testae_tooltip": E_TEXT,
    "spell_testae2_tooltip": E_TEXT,
    "spell_listtype_damage": "Damage",
}


def write_raw(root):
    raw = root / PATCH
    rel = "game/en_us/data/menu/en_us/lol.stringtable.json"
    (raw / rel).parent.mkdir(parents=True, exist_ok=True)
    (raw / rel).write_text(json.dumps({"version": 5, "entries": EN}), encoding="utf-8")
    manifest = {"patch": PATCH, "cdragon_version": "16.18.1", "stringtable_layout": {"en_us": "lol"},
                "stringtable_path": {"en_us": rel}}
    champ = raw / "game/data/characters/testa/testa.bin.json"
    champ.parent.mkdir(parents=True, exist_ok=True)
    champ.write_text(json.dumps(champion()), encoding="utf-8")
    (raw / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.raw = Path(cls.tmp.name) / "raw"
        write_raw(cls.raw)
        cls.p = P.Patch.load(PATCH, cls.raw)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rec(self, path):
        return next(r for f, r in self.p.records() if r["spell_path"] == path)

    def ctx(self, path):
        return P.Ctx(self.p, "testa", self.rec(path))

    def sites(self, rule, path, keep=lambda s: True):
        return [s for s in P.SITES[rule](self.ctx(path)) if keep(s)]

    def plant(self, rule, path, keep=lambda s: True, seed=0):
        """(planted input, original input, plan, site, failures) for the first site and change."""
        cx = self.ctx(path)
        sites = [s for s in P.SITES[rule](cx) if keep(s)]
        self.assertTrue(sites, f"no {rule} site")
        plan = next(iter(P.PLANS[rule](cx, sites[0], random.Random(seed))))
        inp, new_rec, lines = P.plant_one(self.p, "testa", cx.rec, plan)
        orig = self.p.original_input("testa", cx.rec)
        return inp, orig, plan, sites[0], P.check(cx, sites[0], plan, new_rec, lines, inp, orig)

    def assert_same_shape(self, inp, orig):
        """In place: the planted input names the same calculations and data values."""
        self.assertEqual(set(inp["placeholders"]), set(orig["placeholders"]))
        self.assertEqual(set(inp["spell"]["data_values"]), set(orig["spell"]["data_values"]))
        self.assertEqual(set(inp["spell"].get("calculations") or {}), set(orig["spell"].get("calculations") or {}))
        self.assertEqual(inp["spell"]["level_up"], orig["spell"]["level_up"])


class ResolverHelpers(Fixture):
    def test_resolve_champion_matches_run_patch(self):
        out = Path(self.tmp.name) / "resolved"
        R.run_patch(PATCH, self.raw, out, "en_us")
        recs = [json.loads(x) for x in (out / f"{PATCH}.en_us.jsonl").read_text().splitlines()]
        lines = [json.loads(x) for x in (out / f"{PATCH}.en_us.spells.jsonl").read_text().splitlines()]
        self.assertEqual(self.p.base["testa"], (recs, lines))

    def test_text_override_replaces_only_its_key(self):
        t = P.TextOverride(self.p.src.table, {"Spell_TestaE_Tooltip": "x"})
        self.assertEqual(t.get("spell_testae_tooltip"), "x")
        self.assertEqual(t.get("Spell_TestaW_Tooltip"), EN["spell_testaw_tooltip"])

    def test_original_inputs_match_build_inputs(self):
        recs, lines = self.p.base["testa"]
        built = {i["id"]: i for i in I.build_inputs(recs, lines)}
        for folder, rec in self.p.records():
            self.assertEqual(self.p.original_input(folder, rec), built[I.record_id(rec)])


class Helpers(unittest.TestCase):
    def test_scaled_keeps_one_precision_and_the_stated_factor(self):
        self.assertEqual(P.scaled([0, 35, 60, 85], 0.8), [0, 28, 48, 68])
        self.assertIsNone(P.scaled([35, 60, 85], 0.75))           # 26.25 is not whole
        self.assertIsNone(P.scaled([3, 3, 4, 4, 5], 1.2))         # a count stays whole
        self.assertEqual(P.scaled([0.15, 0.2, 0.25], 1.2), [0.18, 0.24, 0.3])
        self.assertIsNone(P.scaled([0.15, 0.2, 0.25], 0.75))      # 0.1125 needs more decimals
        self.assertEqual(P.scaled([0.5], 0.75, 2), None)
        self.assertEqual(P.scaled([0.6], 1.5, 2), [0.9])

    def test_readable_names(self):
        self.assertTrue(P.readable("SlowAmountEmpowered"))
        for name in ("IGNORE___replaced_the_values_in_the__json", "{0a1b2c3d}", "SlowAmount_Old", "TestValue"):
            self.assertFalse(P.readable(name), name)
        self.assertTrue(P.quantities("CCDuration") & P.quantities("RevealDuration"))
        self.assertFalse(P.quantities("Cooldown_Reduction") & P.quantities("Damage_AD_Ratio"))


class Sites(Fixture):
    def test_stat_ratio_in_place_with_a_coefficient_anchor(self):
        inp, orig, plan, site, fails = self.plant("stat_ratio", Q)
        self.assertEqual(fails, [])
        self.assertEqual(site["calc"], "TotalDamage")
        self.assertEqual(site["anchors"][0]["type"], "coefficient")
        self.assertIn(plan["change"]["to"], [0.25, 0.75, 1])     # 0.375 would need a third decimal
        self.assertIn("@TotalDamage@", inp["text"])
        self.assertNotEqual(inp["placeholders"]["TotalDamage"]["value"], orig["placeholders"]["TotalDamage"]["value"])
        self.assert_same_shape(inp, orig)
        # The ShieldAmount ratio (0.2) has no anchor, nor has W's.
        self.assertEqual([s["calc"] for s in self.sites("stat_ratio", Q)], ["TotalDamage"])
        self.assertEqual(self.sites("stat_ratio", W), [])

    def test_the_raw_data_is_never_changed(self):
        before = copy.deepcopy(self.p.src.champs["testa"].data)
        self.plant("stat_ratio", Q)
        self.plant("base_values", Q)
        self.plant("drop_term", Q)
        self.assertEqual(self.p.src.champs["testa"].data, before)

    def test_base_values_need_a_field_only_the_text_reads(self):
        # BaseDamage is read by a level-up row, so only ShieldBase (anchored by the ShieldLevelUp row) is a site.
        sites = self.sites("base_values", Q)
        self.assertEqual([s["dv"] for s in sites], ["ShieldBase"])
        self.assertEqual(sites[0]["anchors"][0]["name"], "ShieldLevelUp")
        inp, orig, plan, site, fails = self.plant("base_values", Q)
        self.assertEqual(fails, [])
        self.assertEqual(plan["change"]["from"], [50, 75, 100])
        self.assertEqual(inp["spell"]["data_values"]["ShieldLevelUp"], [50, 75, 100])
        self.assert_same_shape(inp, orig)
        # EchoDamage is also read by EchoGameplay, which no placeholder shows.
        self.assertFalse([s for s in self.sites("base_values", E) if s["dv"] == "EchoDamage"])

    def test_other_value_picks_a_readable_value_of_the_same_kind(self):
        sites = self.sites("other_value", Q)
        # Not SlowAmount_Old (junk name), not SlowDuration (more than 4 times as large).
        self.assertEqual({(s["token"], s["target"]) for s in sites}, {("SlowAmount", "SlowAmountEmpowered")})
        inp, orig, plan, site, fails = self.plant("other_value", Q)
        self.assertEqual(fails, [])
        self.assertIn("@SlowAmountEmpowered*100@%", inp["text"])
        self.assertIn("SlowAmount", inp["spell"]["data_values"])

    def test_drop_term(self):
        sites = self.sites("drop_term", Q)
        # Dropping BaseDamage would leave only a ratio (a base of 0), so only the ratio term goes.
        self.assertEqual([(s["calc"], s["part"]) for s in sites], [("TotalDamage", ["mFormulaParts", 1])])
        inp, orig, plan, site, fails = self.plant("drop_term", Q)
        self.assertEqual(fails, [])
        self.assertEqual(len(inp["placeholders"]["TotalDamage"]["formula"]["parts"]), 1)

    def test_multiplier_anchored_by_a_typed_count(self):
        inp, orig, plan, site, fails = self.plant("multiplier", Q)
        self.assertEqual(fails, [])
        self.assertEqual(site["anchors"][0]["type"], "typed_number")
        self.assertEqual(plan["change"]["from"], 3)
        self.assertIn(plan["change"]["to"], (2, 4))
        self.assert_same_shape(inp, orig)


class SelfCheck(Fixture):
    def test_a_change_that_shows_the_same_value_fails(self):
        cx = self.ctx(Q)
        site = self.sites("other_value", Q)[0]
        plan = {"data": None, "text": cx.rec["raw_text"], "change": {"points_at": "SlowAmount"}}
        inp, new_rec, lines = P.plant_one(self.p, "testa", cx.rec, plan)
        fails = P.check(cx, site, plan, new_rec, lines, inp, self.p.original_input("testa", cx.rec))
        self.assertIn("the planted input does not differ from the original", fails)

    def test_an_added_calculation_fails(self):
        cx = self.ctx(Q)
        site = self.sites("stat_ratio", Q)[0]
        plan = next(iter(P.plan_stat_ratio(cx, site, random.Random(0))))
        plan["data"][Q]["mSpell"]["mSpellCalculations"]["TotalDamageTooltip"] = {"mFormulaParts": [number(1.0)]}
        inp, new_rec, lines = P.plant_one(self.p, "testa", cx.rec, plan)
        fails = P.check(cx, site, plan, new_rec, lines, inp, self.p.original_input("testa", cx.rec))
        self.assertIn("the change added, removed or renamed something", fails)

    def test_a_changed_anchor_fails(self):
        cx = self.ctx(Q)
        site = self.sites("stat_ratio", Q)[0]
        plan = next(iter(P.plan_stat_ratio(cx, site, random.Random(0))))
        plan["data"][Q]["mSpell"]["mCoefficient"] = plan["change"]["to"]
        inp, new_rec, lines = P.plant_one(self.p, "testa", cx.rec, plan)
        fails = P.check(cx, site, plan, new_rec, lines, inp, self.p.original_input("testa", cx.rec))
        self.assertIn("the anchor is gone from the planted input", fails)


class Drawing(Fixture):
    def test_draw_is_seeded_one_per_spell_and_text(self):
        a, ra = P.draw(self.p, 10, 7)
        b, rb = P.draw(self.p, 10, 7)
        self.assertEqual([e["_sha"] for e in a], [e["_sha"] for e in b])
        spells = [e["record_id"].split(":")[3] for e in a]
        self.assertEqual(len(spells), len(set(spells)))
        # Q, and one of E and E2, which share their text; W has no site.
        self.assertEqual(len(a), 2)
        self.assertEqual(len([s for s in spells if s in (E, E2)]), 1)
        self.assertTrue(ra["reallocated"])
        self.assertEqual(sum(ra["planted"].values()), 2)

    def test_split_and_reallocation(self):
        self.assertEqual(P.split(12, 5), [3, 3, 2, 2, 2])
        errors, report = P.draw(self.p, 5, 1)
        moved = sum(m["count"] for m in report["reallocated"])
        self.assertGreater(moved, 0)
        for m in report["reallocated"]:
            self.assertEqual(sum(m["to"].values()), m["count"])

    def test_cli_writes_set_and_manifest_and_verifies(self):
        out = Path(self.tmp.name) / "planted"
        man = Path(self.tmp.name) / "elsewhere" / "t.manifest.json"
        with contextlib.redirect_stdout(io.StringIO()):
            P.main(["--patch", PATCH, "--set", "t", "--seed", "3", "--counts", "tooltip_calc=2",
                    "--raw-dir", str(self.raw), "--out-dir", str(out), "--manifest-out", str(man)])
        rows = [json.loads(x) for x in (out / "t.jsonl").read_text(encoding="utf-8").splitlines()]
        manifest = json.loads(man.read_text(encoding="utf-8"))
        self.assertFalse((out / "t.manifest.json").exists())
        self.assertEqual(len(rows), 2)
        self.assertEqual(manifest["seed"], 3)
        self.assertEqual(manifest["cdragon_version"], "16.18.1")
        self.assertEqual(set(manifest["code"]["sha256"]), {"scripts/plant.py", "scripts/inputs.py",
                                                           "scripts/resolve_tooltips.py"})
        for row, entry in zip(rows, manifest["errors"]):
            self.assertEqual(row["id"], entry["id"])
            self.assertEqual(hashlib.sha256(I.dumps(row["input"]).encode("utf-8")).hexdigest(), entry["sha256"])
            self.assertTrue(row["answer"])
            self.assertNotIn("\u2014", row["answer"])
            self.assertNotIn("\u2013", row["answer"])
        text = json.dumps(manifest, ensure_ascii=False)
        for sentence in EN.values():
            if len(sentence) > 30:
                self.assertNotIn(sentence[:30], text)
        self.assertEqual(P.verify(man, self.raw), ([], 2))
        manifest["errors"][0]["sha256"] = "0" * 64
        man.write_text(json.dumps(manifest), encoding="utf-8")
        fails, _ = P.verify(man, self.raw)
        self.assertEqual(fails, [f"{manifest['errors'][0]['id']}: sha256 differs"])


if __name__ == "__main__":
    unittest.main()
