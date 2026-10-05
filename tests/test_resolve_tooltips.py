"""Tests for scripts/resolve_tooltips.py. Run from the project root:

    python3 -m unittest discover tests
"""

import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import resolve_tooltips as r  # noqa: E402


def fnv(name):
    return int(r.fnv1a(name)[1:-1], 16)


def rst(entries, version=5, font_config=None):
    """A binary string table holding {key: text}, hashed the way the game hashes keys."""
    bits = r.rst_hash_bits(version)
    mask = (1 << bits) - 1
    data = b""
    packed = []
    for key, text in entries.items():
        packed.append(((len(data)) << bits) | (r.xxh64(key.lower().encode()) & mask))
        data += text.encode() + b"\0"
    head = b"RST" + bytes([version])
    if version == 2:
        if font_config is None:
            head += b"\0"
        else:
            cfg = font_config.encode()
            head += b"\1" + struct.pack("<I", len(cfg)) + cfg
    body = struct.pack("<I", len(packed)) + struct.pack("<%dQ" % len(packed), *packed)
    if version < 5:
        body += b"\0"
    return head + body + data


def bin_field(name, type_byte, payload):
    return struct.pack("<IB", fnv(name), type_byte) + payload


def bin_string(text):
    b = text.encode()
    return struct.pack("<H", len(b)) + b


def bin_struct(class_name, fields):
    body = struct.pack("<H", len(fields)) + b"".join(fields)
    return struct.pack("<II", fnv(class_name), len(body)) + body


def prop(entries):
    """A PROP file: entries is [(path, class, [fields])]."""
    out = b"PROP" + struct.pack("<II", 2, 0) + struct.pack("<I", len(entries))
    out += b"".join(struct.pack("<I", fnv(c)) for _, c, _ in entries)
    for path, _, fields in entries:
        body = struct.pack("<IH", fnv(path), len(fields)) + b"".join(fields)
        out += struct.pack("<I", len(body)) + body
    return out


def spell(data_values=None, calcs=None, effects=None, level_count=None, loc_keys=None):
    m = {"mDataValues": [{"mName": k, "mValues": v} for k, v in (data_values or {}).items()],
         "mSpellCalculations": calcs or {}}
    if effects is not None:
        m["mEffectAmount"] = [{"value": v} for v in effects]
    td = {"mLocKeys": loc_keys or {}}
    if level_count:
        td["mLists"] = {"LevelUp": {"levelCount": level_count}}
    m["mClientData"] = {"mTooltipData": td}
    return {"__type": "SpellObject", "mScriptName": "TestSpell", "mSpell": m}


def context(sp_obj):
    s = r.Spell("Characters/Test/Spells/TestSpell", sp_obj)
    ch = r.Champion("test", {s.path: sp_obj})
    return r.Context(ch, s, r.STATS_B), ch, s


class Hashes(unittest.TestCase):
    def test_xxh64_known_values(self):
        self.assertEqual(r.xxh64(b""), 0xEF46DB3751D8E999)
        self.assertEqual(r.xxh64(b"abc"), 0x44BC2CF5AD770999)
        # 39 bytes, so the 32-byte block loop runs (value from the python-xxhash docs).
        self.assertEqual(r.xxh64(b"Nobody inspects the spammish repetition"), 0xFBCEA83C8A378BF1)

    def test_fnv_matches_known_field_hashes(self):
        # Seen in 10.25 and 11.1 exports, where these fields are left unnamed.
        self.assertEqual(r.fnv1a("mSpellCalculations"), "{94572284}")
        self.assertEqual(r.fnv1a("mCharacterPassiveSpell"), "{e96f0412}")


class Tokens(unittest.TestCase):
    def test_spaced_token_resolves_against_a_spaced_data_value(self):
        # Kennen E in 15.1 declares data values named 'movement speed' and 'duration - as ball'.
        text = "Gains @Movement Speed*100@% speed for @duration - as ball@ seconds and 50 armor."
        matches, stray = r.tokens_in(text)
        self.assertEqual([m.group(1) for m in matches], ["Movement Speed*100", "duration - as ball"])
        self.assertEqual(stray, 0)
        _, ch, s = context(spell(data_values={"movement speed": [0.4] * 7, "duration - as ball": [2] * 7}))
        speed = r.resolve_placeholder(matches[0].group(1), ch, s, [1], r.STATS_B)
        self.assertEqual((speed["status"], speed["kind"], speed["base"]), ("resolved", "data_value", [40]))
        dur = r.resolve_placeholder(matches[1].group(1), ch, s, [1], r.STATS_B)
        self.assertEqual((dur["status"], dur["base"]), ("resolved", [2]))

    def test_spaced_name_not_in_data_gets_the_usual_reason(self):
        _, ch, s = context(spell())
        res = r.resolve_placeholder("Movement Speed*100", ch, s, [1], r.STATS_B)
        self.assertEqual(res["status"], "unresolved")
        self.assertEqual(res["reason"], "name not found in spell data")

    def test_spaced_token_is_masked_from_typed_numbers(self):
        nums, _ = r.typed_numbers("Gains @Movement Speed*100@% speed and 50 armor.")
        self.assertEqual([n["value"] for n in nums], [50])

    def test_unpaired_at_is_counted(self):
        _, stray = r.tokens_in("Deals @Damage@ damage, mail me @ home")
        self.assertEqual(stray, 1)


class LegacyTokens(unittest.TestCase):
    def test_char_tokens_read_the_spell_coefficients(self):
        obj = spell()
        obj["mSpell"]["mCoefficient"] = 0.5
        obj["mSpell"]["mCoefficient2"] = 0.15
        _, ch, s = context(obj)
        ap = r.resolve_placeholder("CharAbilityPower", ch, s, [1], r.STATS_C)
        ad2 = r.resolve_placeholder("CharBonusPhysical2", ch, s, [1], r.STATS_C)
        self.assertEqual(ap["scalings"][0]["label"], "+50% AP")
        self.assertEqual(ad2["scalings"][0]["label"], "+15% bonus AD")
        total_ad = r.resolve_placeholder("CharTotalPhysical", ch, s, [1], r.STATS_C)
        self.assertEqual(total_ad["status"], "resolved")
        self.assertEqual(total_ad["scalings"][0]["label"], "+50% AD")
        _, ch, s = context(spell())
        self.assertEqual(r.resolve_placeholder("CharAbilityPower", ch, s, [1], r.STATS_C)["status"], "unresolved")


class NoInventedZeros(unittest.TestCase):
    def setUp(self):
        self.ctx, _, _ = context(spell(effects=[[0, 10, 20, 30, 40, 50, 60]]))

    def assertUnresolved(self, fn, reason):
        with self.assertRaises(r.Unresolved) as cm:
            fn()
        self.assertEqual(cm.exception.reason, reason)

    def test_effect_index_above_10(self):
        self.assertUnresolved(lambda: self.ctx.effect(11, 1), "effect index above 10")
        self.assertEqual(self.ctx.effect(1, 2), 20)

    def test_product_with_missing_part(self):
        part = {"__type": "ProductOfSubPartsCalculationPart",
                "mPart1": {"__type": "NumberCalculationPart", "mNumber": 2.0}}
        self.assertUnresolved(lambda: self.ctx.part(part, 1, 5), "product part missing")

    def test_empty_level_formula(self):
        part = {"__type": "ByCharLevelFormulaCalculationPart", "mValues": []}
        self.assertUnresolved(lambda: self.ctx.part(part, 1, 5), "level formula has no values")

    def test_stat_part_without_subpart(self):
        part = {"__type": "StatBySubPartCalculationPart", "mStat": 2}
        self.assertUnresolved(lambda: self.ctx.part(part, 1, 5), "stat part has no subpart")


class Labels(unittest.TestCase):
    def test_fraction_stat_in_percent_calculation(self):
        # Jhin's passive: 0.3 x bonus attack speed shown as % AD (layout B, attack speed = 4).
        self.assertEqual(r.term_label(("stat", 4, 2), 0.3, True, r.STATS_B),
                         "+30% per 100% bonus attack speed")
        self.assertEqual(r.term_label(("stat", 8, 0), 4, False, r.STATS_B), "+4 per 100% crit chance")

    def test_flat_stat_unchanged(self):
        self.assertEqual(r.term_label(("stat", 0, 0), 0.6, False, r.STATS_B), "+60% AP")
        self.assertEqual(r.term_label(("stat", 2, 2), 0.002, True, r.STATS_B), "+20% per 100 bonus AD")


class Ranks(unittest.TestCase):
    def test_one_rank_spell_with_varying_data_is_flagged(self):
        obj = spell(data_values={"BonusAttackSpeed": [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]})
        _, ch, s = context(obj)
        ranks, source, varying = r.rank_info(ch, s.path, s)
        self.assertEqual(ranks, [1])
        self.assertEqual(source, "one rank, but data varies across indices 1 to 5")
        self.assertEqual(varying, ["BonusAttackSpeed"])

    def test_one_rank_spell_with_flat_data(self):
        _, ch, s = context(spell(data_values={"Duration": [3] * 7}))
        self.assertEqual(r.rank_info(ch, s.path, s)[1], "none (one rank)")


class StringTables(unittest.TestCase):
    def test_fontconfig_version_2_with_font_config(self):
        blob = rst({"Spell_TestQ_Tooltip": "Deals @Damage@ damage."}, version=2,
                   font_config='[FontConfig "English"]\nfontlib "fonts_latin.swf"\n')
        version, entries = r.parse_rst(blob)
        self.assertEqual(version, 2)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "fontconfig_en_us.txt"
            p.write_bytes(blob)
            table = r.TextTable(p, "fontconfig")
            self.assertEqual(table.get("spell_testq_tooltip"), "Deals @Damage@ damage.")
            self.assertIsNone(table.get("spell_testw_tooltip"))
            self.assertIsNone(table.readable_keys())

    def test_versions_4_and_5_use_39_bit_hashes(self):
        for version in (4, 5):
            blob = rst({"a_key": "first", "b_key": "second"}, version=version)
            _, entries = r.parse_rst(blob)
            self.assertEqual(entries[r.xxh64(b"b_key") & ((1 << 39) - 1)], "second")

    def test_json_table_falls_back_to_hashed_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "lol.stringtable.json"
            h = "{%010x}" % (r.xxh64(b"spell_x_tooltip") & ((1 << 39) - 1))
            p.write_text(json.dumps({"version": 5, "entries": {"plain_key": "a", h: "b"}}))
            table = r.TextTable(p, "lol")
            self.assertEqual(table.get("Plain_Key"), "a")
            self.assertEqual(table.get("Spell_X_Tooltip"), "b")

    def test_find_text_table_uses_manifest_path_first(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            exact = raw / "game/ko_kr/data/menu/en_us/lol.stringtable.json"
            other = raw / "game/data/menu/main_ko_kr.stringtable.json"
            for p in (exact, other):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("{}")
            manifest = {"stringtable_layout": {"ko_kr": "lol"},
                        "stringtable_path": {"ko_kr": "game/ko_kr/data/menu/en_us/lol.stringtable.json"}}
            self.assertEqual(r.find_text_table(raw, manifest, "ko_kr"), (exact, "lol"))
            # When the manifest's file is gone, the search finds the next form on disk.
            exact.unlink()
            self.assertEqual(r.find_text_table(raw, manifest, "ko_kr"), (other, "main_locale"))

    def test_find_text_table_search_uses_inner_en_us_folder(self):
        # CommunityDragon keeps the inner folder named en_us for every language.
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            p = raw / "game/ko_kr/data/menu/en_us/lol.stringtable.json"
            p.parent.mkdir(parents=True)
            p.write_text("{}")
            self.assertEqual(r.find_text_table(raw, {}, "ko_kr"), (p, "lol"))

    def test_find_text_table_fontconfig_forms(self):
        # 11.1 to 12.22 offer the decoded .txt.json; 10.x only the binary .txt.
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            menu = raw / "game/data/menu"
            menu.mkdir(parents=True)
            (menu / "fontconfig_en_us.txt").write_bytes(rst({"k": "v"}, version=2))
            self.assertEqual(r.find_text_table(raw, {}, "en_us"), (menu / "fontconfig_en_us.txt", "fontconfig"))
            (menu / "fontconfig_en_us.txt.json").write_text("{}")
            self.assertEqual(r.find_text_table(raw, {}, "en_us"),
                             (menu / "fontconfig_en_us.txt.json", "fontconfig"))

    def test_find_text_table_without_manifest_layout(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            p = raw / "game/data/menu/main_en_us.stringtable.json"
            p.parent.mkdir(parents=True)
            p.write_text("{}")
            self.assertEqual(r.find_text_table(raw, {}, "en_us"), (p, "main_locale"))


class OldChampionFiles(unittest.TestCase):
    def test_hashed_field_names_are_renamed(self):
        out = r.unhash_names({"{94572284}": {"Calc": {"__type": r.fnv1a("GameCalculation")}}})
        self.assertEqual(out, {"mSpellCalculations": {"Calc": {"__type": "GameCalculation"}}})

    def test_binary_file_gives_classes(self):
        part = bin_struct("StatByNamedDataValueCalculationPart",
                          [bin_field("mDataValue", 16, bin_string("APRatio"))])
        calc = bin_struct("GameCalculation", [bin_field("mFormulaParts", 0x80, struct.pack("<B", 0x83)
                                                        + struct.pack("<II", 4 + len(part), 1) + part)])
        calcs = bin_field("mSpellCalculations", 0x86, struct.pack("<BB", 17, 0x83)
                          + struct.pack("<II", 4 + 4 + len(calc), 1) + struct.pack("<I", fnv("Damage")) + calc)
        msp = bin_struct("SpellDataResource", [calcs])
        blob = prop([("Characters/Test/Spells/TestQ", "SpellObject",
                      [bin_field("mScriptName", 16, bin_string("TestQ")), bin_field("mSpell", 0x82, msp)])])
        export = {"Characters/Test/Spells/TestQ": {"mScriptName": "TestQ"}}
        data = r.unhash_names(r.merge_bin(export, r.parse_bin(blob)))
        sp = data["Characters/Test/Spells/TestQ"]
        self.assertEqual(sp["__type"], "SpellObject")
        c = sp["mSpell"]["mSpellCalculations"][r.fnv1a("Damage")]
        self.assertEqual(c["mFormulaParts"][0]["__type"], "StatByNamedDataValueCalculationPart")

    def test_binary_file_with_old_type_numbers(self):
        # Before about 10.10 the container types have no unordered list, so 0x83 is a link
        # (a 4-byte hash) rather than an embedded object.
        path = "Characters/Test/Spells/TestQAbility"
        root = "Characters/Test/Spells/TestQ"
        blob = prop([(path, "AbilityObject", [bin_field("mRootSpell", 0x83, struct.pack("<I", fnv(root)))]),
                     (root, "SpellObject", [bin_field("mScriptName", 16, bin_string("TestQ"))])])
        export = {path: {}, root: {}}
        data = r.unhash_names(r.merge_bin(export, r.parse_bin(blob)))
        self.assertEqual(data[path]["mRootSpell"], root)
        self.assertEqual(data[path]["__type"], "AbilityObject")


class OldPassives(unittest.TestCase):
    def test_passive_lua_name_gives_slot_p_and_record_text_is_not_read(self):
        # Annie in 10.1: no mCharacterPassiveSpell, and the passive spell has its own tooltip.
        data = {
            "Characters/Test/CharacterRecords/Root": {
                "__type": "CharacterRecord", "passiveToolTip": "game_character_passiveDescription_Test",
                "passiveLuaName": "TestPassive", "spellNames": ["TestQ"]},
            "Characters/Test/Spells/TestPassive": spell(loc_keys={"keyTooltip": "Spell_TestPassive_Tooltip"}),
            "Characters/Test/Spells/TestQ": spell(loc_keys={"keyTooltip": "Spell_TestQ_Tooltip"}),
        }
        data["Characters/Test/Spells/TestPassive"]["mScriptName"] = "TestPassive"
        data["Characters/Test/Spells/TestQ"]["mScriptName"] = "TestQ"
        jobs = r.text_jobs(r.Champion("test", data))
        self.assertEqual(sorted((j[0], j[2], j[3]) for j in jobs),
                         [("Characters/Test/Spells/TestPassive", "P", [("keyTooltip", "Spell_TestPassive_Tooltip")]),
                          ("Characters/Test/Spells/TestQ", "Q", [("keyTooltip", "Spell_TestQ_Tooltip")])])

    def test_record_text_joins_the_passive_spell_entry(self):
        data = {
            "Characters/Test/CharacterRecords/Root": {
                "__type": "CharacterRecord", "passiveToolTip": "game_character_passiveDescription_Test",
                "passiveLuaName": "TestPassive"},
            "Characters/Test/Spells/TestPassive": spell(loc_keys={"keyTooltipSimple": "Spell_TestPassive_Simple"}),
        }
        data["Characters/Test/Spells/TestPassive"]["mScriptName"] = "TestPassive"
        jobs = r.text_jobs(r.Champion("test", data))
        self.assertEqual([(j[0], j[2], j[3]) for j in jobs],
                         [("Characters/Test/Spells/TestPassive", "P",
                           [("keyTooltipSimple", "Spell_TestPassive_Simple"),
                            ("passiveToolTip", "game_character_passiveDescription_Test")])])

    def test_record_passive_text_is_read_when_no_spell_names_one(self):
        data = {
            "Characters/Test/CharacterRecords/Root": {
                "__type": "CharacterRecord", "passiveToolTip": "game_character_passiveDescription_Test",
                "passiveLuaName": "TestPassive"},
            "Characters/Test/Spells/TestPassive": {"__type": "SpellObject", "mScriptName": "TestPassive",
                                                   "mSpell": {}},
        }
        jobs = r.text_jobs(r.Champion("test", data))
        self.assertEqual([(j[0], j[2], j[3]) for j in jobs],
                         [("Characters/Test/Spells/TestPassive", "P",
                           [("passiveToolTip", "game_character_passiveDescription_Test")])])


class UnlinkedPassiveFallbacks(unittest.TestCase):
    def record(self, **fields):
        return {"__type": "CharacterRecord", "passiveLuaName": "", "spellNames": ["TestQ"], **fields}

    def named(self, script, keys):
        obj = spell(loc_keys=keys)
        obj["mScriptName"] = script
        return obj

    def test_champion_p_spell_is_the_passive(self):
        # Yuumi in 10.1: passiveLuaName is empty and passiveToolTip names a key no spell has.
        data = {
            "Characters/Test/CharacterRecords/Root": self.record(
                passiveToolTip="GeneratedTip_Passive_TestP_Description"),
            "Characters/Test/Spells/TestP": self.named("TestP", {"keyTooltip": "Spell_TestPassive_Tooltip"}),
            "Characters/Test/Spells/TestQ": self.named("TestQ", {"keyTooltip": "Spell_TestQ_Tooltip"}),
        }
        jobs = r.text_jobs(r.Champion("test", data))
        self.assertEqual(sorted((j[0], j[2], j[3]) for j in jobs),
                         [("Characters/Test/Spells/TestP", "P", [("keyTooltip", "Spell_TestPassive_Tooltip")]),
                          ("Characters/Test/Spells/TestQ", "Q", [("keyTooltip", "Spell_TestQ_Tooltip")])])

    def test_spell_named_by_passive_tooltip_key(self):
        data = {
            "Characters/Test/CharacterRecords/Root": self.record(passiveToolTip=""),
            "Characters/Test/Spells/TestInnate": self.named("TestInnate",
                                                            {"keyTooltip": "Spell_TestPassive_Tooltip"}),
        }
        ch = r.Champion("test", data)
        self.assertEqual(ch.slot("Characters/Test/Spells/TestInnate"), "P")

    def test_two_spells_with_the_passive_key_pick_neither(self):
        data = {
            "Characters/Test/CharacterRecords/Root": self.record(passiveToolTip=""),
            "Characters/Test/Spells/TestA": self.named("TestA", {"keyTooltip": "Spell_TestPassive_Tooltip"}),
            "Characters/Test/Spells/TestB": self.named("TestB", {"keyTooltip": "Spell_TestPassive_Tooltip"}),
        }
        self.assertIsNone(r.Champion("test", data).passive)


class HashedEntryPaths(unittest.TestCase):
    def test_record_and_spells_under_hashed_keys(self):
        # Senna in 10.1: the record and every spell are stored under the hash of their path.
        q = spell(loc_keys={"keyTooltip": "Spell_TestQ_Tooltip"})
        q["mScriptName"] = "TestQ"
        p = spell(loc_keys={"keyTooltip": "Spell_TestPassive_Tooltip"})
        p["mScriptName"] = "TestPassive"
        data = {
            r.fnv1a("Characters/Test/CharacterRecords/SLIME"): {"__type": "CharacterRecord", "spellNames": []},
            r.fnv1a("Characters/Test/CharacterRecords/Root"): {
                "__type": "CharacterRecord", "mCharacterName": "Test", "spellNames": ["TestQ"],
                "passiveLuaName": "TestPassive"},
            r.fnv1a("Characters/Test/Spells/TestQ"): q,
            r.fnv1a("Characters/Test/Spells/TestPassive"): p,
        }
        ch = r.Champion("test", data)
        self.assertEqual(ch.record[0], r.fnv1a("Characters/Test/CharacterRecords/Root"))
        self.assertEqual(ch.slot(r.fnv1a("Characters/Test/Spells/TestQ")), "Q")
        self.assertEqual(ch.slot(r.fnv1a("Characters/Test/Spells/TestPassive")), "P")

    def test_only_record_in_file_is_used(self):
        data = {"{12345678}": {"__type": "CharacterRecord", "mCharacterName": "Other"}}
        self.assertEqual(r.Champion("test", data).name, "Other")

    def test_hashed_spell_sharing_a_named_spells_key_is_a_duplicate(self):
        jobs = [("Characters/Test/Spells/TestR", None, "R", [("keyTooltip", "Spell_TestR_Tooltip")]),
                ("{36b6a65c}", None, "R-form", [("keyTooltip", "Spell_TestR_Tooltip")]),
                ("{00000001}", None, "other", [("keyTooltip", "Spell_TestOther_Tooltip")])]
        self.assertEqual(r.duplicate_targets(jobs),
                         {("{36b6a65c}", "spell_testr_tooltip"): "Characters/Test/Spells/TestR"})

    def test_all_hashed_spells_keep_the_main_slot_one(self):
        # Samira in 10.20: SamiraE and SamiraEBuff are both stored under hashes.
        jobs = [("{3f544e19}", None, "other", [("keyTooltip", "Spell_TestE_Tooltip")]),
                ("{49dcc318}", None, "E", [("keyTooltip", "Spell_TestE_Tooltip")]),
                ("{00000001}", None, "other", [("keyTooltip", "Spell_TestX_Tooltip")]),
                ("{00000002}", None, "Q-form", [("keyTooltip", "Spell_TestX_Tooltip")])]
        self.assertEqual(r.duplicate_targets(jobs), {("{3f544e19}", "spell_teste_tooltip"): "{49dcc318}"})

    def test_spell_named_in_the_key_owns_it(self):
        # Zed in 12.8: ZedW2 (hashed, W-form) and ZedR2 (readable, R-form) share ZedW2's text.
        # Neither is in slot P to R, so the key's script name decides, and ZedW2 is not marked.
        w2 = r.Spell("{e0c2427d}", {"mScriptName": "ZedW2"})
        r2 = r.Spell("Characters/Zed/Spells/ZedRAbility/ZedR2", {"mScriptName": "ZedR2"})
        stray = r.Spell("{00000003}", {"mScriptName": "ZedShadowDash"})
        jobs = [(r2.path, r2, "R-form", [("keyTooltip", "Spell_ZedW2_Tooltip")]),
                (w2.path, w2, "W-form", [("keyTooltip", "Spell_ZedW2_Tooltip")])]
        self.assertEqual(r.duplicate_targets(jobs), {})
        # A third hashed spell sharing the key is marked as a duplicate of ZedW2.
        jobs.append((stray.path, stray, "other", [("keyTooltip", "Spell_ZedW2_Tooltip")]))
        self.assertEqual(r.duplicate_targets(jobs), {("{00000003}", "spell_zedw2_tooltip"): "{e0c2427d}"})

    def test_key_with_no_owner_is_left_unmarked(self):
        a = r.Spell("Characters/Test/Spells/TestA", {"mScriptName": "TestA"})
        b = r.Spell("{00000004}", {"mScriptName": "TestB"})
        jobs = [(a.path, a, "other", [("keyTooltip", "Spell_TestShared_Tooltip")]),
                (b.path, b, "other", [("keyTooltip", "Spell_TestShared_Tooltip")])]
        self.assertEqual(r.duplicate_targets(jobs), {})


class StatLayouts(unittest.TestCase):
    def champs(self, feast_code, zac_codes):
        def stat_calc(codes):
            return {"__type": "GameCalculation", "mFormulaParts": [
                {"__type": "StatByCoefficientCalculationPart", "mStat": c} for c in codes]}
        feast = spell(calcs={"RDamage": stat_calc([feast_code])})
        feast["mScriptName"] = "Feast"
        zac = spell(calcs={"HealthCostTooltip": stat_calc(zac_codes)})
        zac["mScriptName"] = "ZacQ"
        return {"chogath": r.Champion("chogath", {"Characters/Chogath/Spells/Feast": feast}),
                "zac": r.Champion("zac", {"Characters/Zac/Spells/ZacQ": zac})}

    def test_layout_before_ability_haste(self):
        # 10.20: Cho'Gath R's bonus health is 9 and Zac's health cost uses 9 and 10.
        layout, names, votes = r.detect_stat_layout(self.champs(9, [9, 10]))
        self.assertEqual((layout, votes), ("D", ["D", "D"]))
        self.assertEqual(names[9], "health")

    def test_layout_c_and_a(self):
        self.assertEqual(r.detect_stat_layout(self.champs(10, [10, 11]))[0], "C")
        self.assertEqual(r.detect_stat_layout(self.champs(11, [11, 12]))[0], "A")

    def test_disagreeing_anchors_give_unknown(self):
        layout, names, votes = r.detect_stat_layout(self.champs(9, [10, 11]))
        # Votes follow STAT_ANCHORS order: Zac before Cho'Gath.
        self.assertEqual((layout, names, votes), ("unknown", None, ["C", "D"]))


class WholePatch(unittest.TestCase):
    def test_locale_in_paths_and_records_with_extended_text(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            out = Path(d) / "out"
            patch = raw / "10.25"
            menu = patch / "game/data/menu"
            menu.mkdir(parents=True)
            (patch / "manifest.json").write_text(json.dumps({
                "stringtable_layout": {"ko_kr": "fontconfig"}, "cdragon_version": "10.25.1+test",
                "failures": [{"path": "game/data/characters/gone/gone.bin.json", "error": "HTTP 404"}]}))
            (menu / "fontconfig_ko_kr.txt").write_bytes(rst({
                "Spell_TestQ_Tooltip": "Deals @Damage@ damage and @Movement Speed@ speed.",
                "Spell_TestQ_TooltipExtended": "{{Spell_TestQ_Tooltip}} Also @Effect11Amount@ for 2 seconds.",
            }, version=2))
            champ = patch / "game/data/characters/test"
            champ.mkdir(parents=True)
            sp = spell(data_values={"Damage": [0, 10, 20, 30, 40, 50, 60]}, level_count=5,
                       loc_keys={"keyTooltip": "Spell_TestQ_Tooltip",
                                 "keyTooltipExtended": "Spell_TestQ_TooltipExtended",
                                 "keyTooltipSimple": "Spell_TestQ_Jade_TooltipSimple"})
            sp["mScriptName"] = "TestQ"  # the key names TestQ, so TestQ owns the text the missile shares
            missile = spell(loc_keys={"keyTooltip": "Spell_TestQ_Tooltip"})
            (champ / "test.bin.json").write_text(json.dumps({"Characters/Test/Spells/TestQ": sp,
                                                             "{36b6a65c}": missile}))
            jade = patch / "game/data/characters/jade_test"
            jade.mkdir(parents=True)
            (jade / "jade_test.bin.json").write_text(json.dumps({"Characters/Jade_Test/Spells/TestQ": sp}))
            summary, path = r.run_patch("10.25", raw, out, "ko_kr")
            self.assertEqual(path, out / "10.25.ko_kr.jsonl")
            self.assertTrue((out / "10.25.ko_kr.summary.json").exists())
            self.assertEqual(summary["locale"], "ko_kr")
            recs = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([x["text_field"] for x in recs], ["keyTooltip", "keyTooltipExtended", "keyTooltip"])
            self.assertTrue(all(x["locale"] == "ko_kr" for x in recs))
            self.assertTrue(all(x["cdragon_version"] == "10.25.1+test" for x in recs))
            main, ext, dup = recs
            self.assertNotIn("duplicate_of", main)
            self.assertEqual((dup["spell_path"], dup["duplicate_of"]), ("{36b6a65c}", "Characters/Test/Spells/TestQ"))
            self.assertEqual(summary["counts"]["records_marked_duplicate"], 1)
            # The duplicate is left out of the checked records; the 2 seconds in the extended text is in.
            self.assertEqual(summary["checked_records"], {"all": 2, "keyTooltip": 1})
            self.assertEqual(summary["counts"]["checked_typed_numbers"], 1)
            self.assertEqual(summary["by_text_field"]["keyTooltip"]["checked_records"], 1)
            self.assertIn("placeholder_coverage_pqwer_slots", summary)
            self.assertEqual(summary["cdragon_version"], "10.25.1+test")
            self.assertEqual(len(summary["manifest_failures"]), 1)
            self.assertEqual(main["placeholders"][0]["base"], [10, 20, 30, 40, 50])
            self.assertEqual(main["placeholders"][1]["reason"], "name not found in spell data")
            self.assertEqual(ext["includes"], ["Spell_TestQ_Tooltip"])
            self.assertEqual(ext["placeholders"][0]["reason"], "effect index above 10")
            self.assertEqual([n["value"] for n in ext["typed_numbers"]], [2])
            self.assertEqual(summary["jade_keys_skipped"], 1)
            self.assertEqual(summary["jade_folders_skipped"], 1)
            self.assertNotIn("records_fully_resolved", summary["counts"])


class FailedPatch(unittest.TestCase):
    def test_a_failed_patch_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            out = Path(d) / "out"
            (raw / "10.1").mkdir(parents=True)
            (raw / "10.1" / "manifest.json").write_text("{}")  # no text file on disk
            menu = raw / "10.2" / "game/data/menu"
            menu.mkdir(parents=True)
            (raw / "10.2" / "manifest.json").write_text("{}")
            (menu / "fontconfig_en_us.txt").write_bytes(rst({"k": "v"}, version=2))
            argv = sys.argv
            sys.argv = ["resolve_tooltips.py", "--raw-dir", str(raw), "--out-dir", str(out)]
            try:
                with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    r.main()
            finally:
                sys.argv = argv
            self.assertIn("10.1", str(cm.exception.code))
            self.assertTrue((out / "10.2.en_us.summary.json").exists())

    def test_a_truncated_text_file_does_not_stop_the_others(self):
        # A half-downloaded binary text file: header and a count of 5, but no entries.
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            out = Path(d) / "out"
            for patch, blob in (("a", b"RST\x03" + struct.pack("<I", 5)), ("b", rst({"k": "v"}, version=3))):
                menu = raw / patch / "game/data/menu"
                menu.mkdir(parents=True)
                (raw / patch / "manifest.json").write_text("{}")
                (menu / "fontconfig_en_us.txt").write_bytes(blob)
            argv = sys.argv
            sys.argv = ["resolve_tooltips.py", "--raw-dir", str(raw), "--out-dir", str(out)]
            err = io.StringIO()
            try:
                with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(err):
                    r.main()
            finally:
                sys.argv = argv
            self.assertIn("1 of 2 patches failed: a", str(cm.exception.code))
            self.assertIn("error", err.getvalue())
            self.assertTrue((out / "b.en_us.summary.json").exists())


if __name__ == "__main__":
    unittest.main()
