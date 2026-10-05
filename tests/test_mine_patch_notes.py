"""Tests for scripts/mine_patch_notes.py. Run from the project root:

    python3 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import mine_patch_notes as m  # noqa: E402


def names_table():
    names = {
        "jarvan iv": ("Jarvan IV", "champion"),
        "jarvaniv": ("Jarvan IV", "champion"),
        "miss fortune": ("Miss Fortune", "champion"),
        "morgana": ("Morgana", "champion"),
        "veigar": ("Veigar", "champion"),
        "nilah": ("Nilah", "champion"),
        "sona": ("Sona", "champion"),
        "kindred": ("Kindred", "champion"),
        "celerity": ("Celerity", "rune"),
        "mark": ("Mark", "summoner spell"),
        "guinsoo's rageblade": ("Guinsoo's Rageblade", "item"),
        "blade of the ruined king": ("Blade of The Ruined King", "item"),
        "jak'sho, the protean": ("Jak'Sho, The Protean", "item"),
    }
    m.add_short_names(names)
    return names


def line(text, section="Bugfixes", subject="", ability=""):
    return {"section": section, "category": "", "subject": subject, "ability": ability,
            "text": text, "tag": "li", "quote": False}


class PatchKey(unittest.TestCase):
    def test_lettered_patch_is_its_own_patch(self):
        key_b, name_b = m.patch_key("Patch 13.1B Notes")
        key_1, name_1 = m.patch_key("Patch 13.1 Notes")
        self.assertEqual(name_b, "13.1B")
        self.assertEqual(name_1, "13.1")
        self.assertNotEqual(key_b, key_1)
        self.assertLess(key_1, key_b)
        self.assertLess(key_b, m.patch_key("Patch 13.3 Notes")[0])

    def test_other_title_forms(self):
        self.assertEqual(m.patch_key("Patch 10.17 notes"), ((2020, 17, ""), "10.17"))
        self.assertEqual(m.patch_key("Patch 25.S1.2 Notes"), ((2025, 2, ""), "25.S1.2"))
        self.assertEqual(m.patch_key("Patch 2025.S1.3 Notes"), ((2025, 3, ""), "2025.S1.3"))
        self.assertEqual(m.patch_key("Patch 26.19 Notes"), ((2026, 19, ""), "26.19"))

    def test_13_1b_slug_is_tried_for_13_2(self):
        self.assertIn("patch-13-1b-notes", m.candidate_slugs(2023, 2))


class TextWasRight(unittest.TestCase):
    def test_game_fixed_to_match_text_is_not_high(self):
        c = m.classify(line("Morgana's Passive - Soul Siphon now properly benefits from small and "
                            "medium monsters as her tooltip states"), names_table())
        self.assertEqual(c["confidence"], "borderline")
        self.assertIn("text was right", c["notes"])

    def test_game_fixed_to_match_tooltip_wording_variants(self):
        for text in ("Fixed a bug where Nilah’s Q passive shield duration did not match the ability tooltip",
                     "Corrected Blade of the Ruined King's Siphon damage in game to be consistent with the "
                     "values in the item's tooltip"):
            c = m.classify(line(text), names_table())
            self.assertEqual(c["confidence"], "borderline", text)
            self.assertIn("text was right", c["notes"], text)

    def test_tooltip_fixed_to_match_values_is_not_text_was_right(self):
        c = m.classify(line("Corrected Morgana's E tooltip to properly match its actual values"), names_table())
        self.assertNotIn("text was right", c["notes"])
        self.assertEqual(c["confidence"], "high")

    def test_did_not_display_its_is_a_strong_text_signal(self):
        c = m.classify(line("Fixed a bug where Morgana's Q did not display its bonus damage value"),
                       names_table())
        self.assertNotIn("weak text signal", c["notes"])

    def test_plain_tooltip_fix_stays_high(self):
        c = m.classify(line("Fixed a bug where Morgana's Q tooltip displayed the wrong damage value"),
                       names_table())
        self.assertEqual(c["confidence"], "high")
        self.assertEqual(c["notes"], "")

    def test_hover_and_tracker_lines_are_not_high(self):
        for text in ("Fixed a bug that caused Morgana's R upgrades to not display tooltips when hovered over.",
                     "Fixed Morgana's W tooltip to properly count blocked damage"):
            self.assertEqual(m.classify(line(text), names_table())["confidence"], "borderline", text)


class ShortNames(unittest.TestCase):
    def test_first_word_and_comma_aliases(self):
        names = names_table()
        self.assertEqual(m.find_subjects("Fixed a bug that caused Jarvan’s W tooltip to be wrong", names),
                         [("Jarvan IV", "champion")])
        self.assertEqual(m.find_subjects("Fixed Jak’Sho’s in-game descriptions", names),
                         [("Jak'Sho, The Protean", "item")])

    def test_champion_ability_phrase_is_not_a_rune_or_spell(self):
        names = names_table()
        self.assertEqual(m.find_subjects("Fixed a bug where Sona's Song of Celerity description incorrectly stated",
                                         names), [("Sona", "champion")])
        self.assertEqual(m.find_subjects("Sona’s E - Song of Celerity's tooltip now properly states", names),
                         [("Sona", "champion")])
        self.assertEqual(m.find_subjects("Kindred's Passive - Mark of the Kindred's tooltip no longer shows zeroes",
                                         names), [("Kindred", "champion")])

    def test_item_after_champion_sentence_is_kept(self):
        self.assertEqual(m.find_subjects("Sona's basic attacks no longer apply if she owns Guinsoo's Rageblade "
                                         "(tooltip will be updated next patch)", names_table()),
                         [("Sona", "champion"), ("Guinsoo's Rageblade", "item")])

    def test_ordinary_first_word_is_not_an_alias(self):
        self.assertNotIn("miss", names_table())

    def test_bugfix_heading_used_when_sentence_names_nobody(self):
        c = m.classify(line("Fixed Q - Baleful Strike's tooltip to correctly state that it grants 1 stack, not 3",
                            subject="Veigar"), names_table())
        self.assertEqual(c["subject"], "Veigar")
        self.assertEqual(c["confidence"], "high")

    def test_ability_heading_not_repeated(self):
        self.assertEqual(m.subject_with_ability("Rek'Sai", "Rek'Sai"), "Rek'Sai")
        self.assertEqual(m.subject_with_ability("Ashe; Rageknife", "Ashe"), "Ashe; Rageknife")
        self.assertEqual(m.subject_with_ability("Ashe; Rageknife", "Q - Volley"), "Ashe Q - Volley; Rageknife")


CHAMPS = {
    "folders": {"sona": "sona", "kindred": "kindred", "veigar": "veigar", "nunu & willump": "nunu",
                "wukong": "monkeyking", "morgana": "morgana", "nilah": "nilah", "jarvan iv": "jarvaniv"},
    "abilities": {"sona": {"Song of Celerity": {"E"}, "Power Chord": {"P"}}},
}


def names_with_extra():
    names = names_table()
    names.update({"nunu & willump": ("Nunu & Willump", "champion"), "nunu": ("Nunu & Willump", "champion"),
                  "wukong": ("Wukong", "champion")})
    return names


class ChampionColumns(unittest.TestCase):
    def cols(self, text, **kw):
        c = m.classify(line(text, **kw), names_with_extra(), CHAMPS)
        return c["champion_folder"], c["slot"]

    def test_folder_is_the_cdragon_alias(self):
        self.assertEqual(self.cols("Fixed a bug where Nunu's E - Snowball Barrage tooltip was wrong"), ("nunu", "E"))
        self.assertEqual(self.cols("Fixed a bug where Wukong's Q tooltip showed the wrong damage"), ("monkeyking", "Q"))

    def test_slot_from_heading_letter_passive_and_ability_name(self):
        self.assertEqual(self.cols("Tooltip now correctly states the damage", subject="Veigar",
                                   ability="Q - Baleful Strike", section="Champions"), ("veigar", "Q"))
        self.assertEqual(self.cols("Fixed a bug where Kindred's Passive - Mark of the Kindred's tooltip was wrong"),
                         ("kindred", "P"))
        self.assertEqual(self.cols("Fixed a bug where Sona's Song of Celerity description incorrectly stated"),
                         ("sona", "E"))
        self.assertEqual(self.cols("Fixed a bug where Morgana's tooltip (W) displayed the wrong value"),
                         ("morgana", "W"))

    def test_lower_case_passive_inside_another_ability_is_not_p(self):
        self.assertEqual(self.cols("Fixed a bug where Nilah's Q passive shield tooltip was wrong")[1], "Q")

    def test_no_slot_named(self):
        self.assertEqual(self.cols("Fixed a bug where Morgana's tooltip displayed the wrong value"), ("morgana", ""))

    def test_non_champion_row_gets_no_folder(self):
        self.assertEqual(self.cols("Fixed a bug where Guinsoo's Rageblade's tooltip displayed the wrong value"),
                         ("", ""))

    def test_several_champions_share_a_possessive(self):
        self.assertEqual(self.cols("Fixed a bug where Sona and Morgana's passive tooltip values were wrong"),
                         ("sona;morgana", "P;P"))
        self.assertEqual(self.cols("Fixed an issue where Sona, Veigar, and Morgana's passive tooltip "
                                   "cooldown values were wrong"), ("sona;veigar;morgana", "P;P;P"))

    def test_slot_pairs_with_the_champion_named_before_it(self):
        self.assertEqual(self.cols("Fixed a bug where Morgana's W tooltip was wrong against Sona's Power Chord"),
                         ("morgana;sona", "W;P"))
        self.assertEqual(self.cols("Fixed a bug where Morgana's W tooltip was wrong against Veigar"),
                         ("morgana;veigar", "W;"))
        self.assertEqual(self.cols("Fixed a bug where Kindred’s passive tooltip was wrong in Veigar’s E"),
                         ("kindred;veigar", "P;E"))

    def test_slot_not_tied_to_one_champion_is_left_empty(self):
        self.assertEqual(self.cols("Fixed a bug where Morgana and Veigar tooltips for W were wrong"),
                         ("morgana;veigar", ""))

    def test_one_champion_with_several_slots(self):
        self.assertEqual(self.cols("Fixed a bug with Morgana's Q and E tooltips displaying incorrect values"),
                         ("morgana", "Q+E"))

    def test_ability_name_in_two_slots_gives_no_slot(self):
        abilities = {"veigar": {"Event Horizon": {"W", "E"}, "Baleful Strike": {"Q"}}}
        self.assertEqual(m.parse_slots("Veigar's Event Horizon tooltip", "", ["Veigar"], abilities), [""])
        self.assertEqual(m.parse_slots("Veigar's Baleful Strike tooltip", "", ["Veigar"], abilities), ["Q"])

    def test_item_text_mentioning_a_champion_gets_no_folder(self):
        names = names_with_extra()
        names["ornn"] = ("Ornn", "champion")
        champs = {"folders": dict(CHAMPS["folders"], ornn="ornn"), "abilities": {}}
        for text in ("Fixed Guinsoo's Rageblade's item description to correctly display the AD it grants "
                     "when upgraded by Ornn",
                     "Fixed a bug with Ornn's forgeable items having debug strings or outdated information."):
            c = m.classify(line(text), names, champs)
            self.assertEqual((c["champion_folder"], c["slot"], c["confidence"]), ("", "", "borderline"), text)
            self.assertIn("item text mentioning a champion", c["notes"], text)


if __name__ == "__main__":
    unittest.main()
