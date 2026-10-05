"""Tests for scripts/patches.py (no network). Run from the project root:

    python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import patches as p  # noqa: E402

# CommunityDragon's folders around every boundary the rule has to get right, as listed on
# 2026-10-05: no 10.17, no 12.24, no 13.2.
FOLDERS = (["9.24", "10.15", "10.16", "10.18", "10.25", "11.1", "12.22", "12.23", "13.1", "13.3", "13.24",
            "14.1", "14.24"] + [f"15.{n}" for n in range(1, 25)] + [f"16.{n}" for n in range(1, 20)])


def mapped(name):
    return p.map_notes_name(name, FOLDERS)


class NotesNames(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(p.parse_notes_name("10.25"), ("10.25", ""))
        self.assertEqual(p.parse_notes_name("13.1B"), ("13.1", "B"))
        self.assertEqual(p.parse_notes_name("10.16b"), ("10.16", "B"))
        self.assertEqual(p.parse_notes_name("25.S1.1"), ("15.1", ""))
        self.assertEqual(p.parse_notes_name("2025.S1.3"), ("15.3", ""))
        self.assertEqual(p.parse_notes_name("25.04"), ("15.4", ""))
        self.assertEqual(p.parse_notes_name("26.19"), ("16.19", ""))
        self.assertIsNone(p.parse_notes_name("Patch notes"))


class Mapping(unittest.TestCase):
    def test_plain_numbers(self):
        self.assertEqual(mapped("10.16"), ("10.16", "10.15", None))
        self.assertEqual(mapped("12.23"), ("12.23", "12.22", None))

    def test_year_boundaries(self):
        self.assertEqual(mapped("11.1"), ("11.1", "10.25", None))
        self.assertEqual(mapped("13.1"), ("13.1", "12.23", None))  # no 12.24
        self.assertEqual(mapped("14.1"), ("14.1", "13.24", None))
        self.assertEqual(mapped("25.S1.1"), ("15.1", "14.24", None))
        self.assertEqual(mapped("26.1"), ("16.1", "15.24", None))

    def test_2025_names(self):
        self.assertEqual(mapped("25.S1.2"), ("15.2", "15.1", None))
        self.assertEqual(mapped("2025.S1.3"), ("15.3", "15.2", None))
        self.assertEqual(mapped("25.04"), ("15.4", "15.3", None))
        self.assertEqual(mapped("25.24"), ("15.24", "15.23", None))

    def test_mid_patch_pages_map_to_the_next_folder(self):
        self.assertEqual(mapped("13.1B"), ("13.3", "13.1", None))
        self.assertEqual(mapped("10.17"), ("10.18", "10.16", None))  # page slug patch-10-16b-notes
        self.assertEqual(mapped("10.16b"), ("10.18", "10.16", None))
        self.assertEqual(mapped("13.3"), ("13.3", "13.1", None))  # no 13.2

    def test_unmappable(self):
        shipped, prefix, problem = mapped("26.20")
        self.assertIsNone(shipped)
        self.assertEqual(prefix, "16.19")
        self.assertIn("no folder", problem)
        self.assertIsNotNone(mapped("9.24")[2])  # oldest folder in this list: nothing before it
        self.assertIsNotNone(mapped("hello")[2])


class CommandLine(unittest.TestCase):
    def test_help_needs_no_network(self):
        import contextlib
        import io
        from unittest import mock
        with mock.patch.object(sys, "argv", ["patches.py", "--help"]), \
                mock.patch.object(p, "_get", side_effect=AssertionError("network used")), \
                contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as done:
            p.main()
        self.assertEqual(done.exception.code, 0)
        self.assertIn("--offline", out.getvalue())


if __name__ == "__main__":
    unittest.main()
