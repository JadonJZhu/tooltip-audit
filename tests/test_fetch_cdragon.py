"""Tests for the parts of scripts/fetch_cdragon.py that need no network.

Run from the project root: python3 -m unittest discover -s tests
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_cdragon as fc  # noqa: E402


class LayoutOrderTest(unittest.TestCase):
    def first(self, patch):
        return fc.layout_order(patch)[0]

    def test_boundaries(self):
        # Each pair is the last patch of one layout and the first of the next,
        # as listed on CommunityDragon on 2026-10-05.
        cases = {
            "10.1": ("fontconfig", "game/data/menu/fontconfig_{loc}.txt"),
            "10.25": ("fontconfig", "game/data/menu/fontconfig_{loc}.txt"),
            "11.1": ("fontconfig", "game/data/menu/fontconfig_{loc}.txt.json"),
            "12.22": ("fontconfig", "game/data/menu/fontconfig_{loc}.txt.json"),
            "12.23": ("main_locale", "game/data/menu/main_{loc}.stringtable.json"),
            "14.3": ("main_locale", "game/data/menu/main_{loc}.stringtable.json"),
            "14.4": ("main", "game/{loc}/data/menu/en_us/main.stringtable.json"),
            "14.14": ("main", "game/{loc}/data/menu/en_us/main.stringtable.json"),
            "14.15": ("lol", "game/{loc}/data/menu/en_us/lol.stringtable.json"),
            "16.19": ("lol", "game/{loc}/data/menu/en_us/lol.stringtable.json"),
        }
        for patch, want in cases.items():
            with self.subTest(patch=patch):
                self.assertEqual(self.first(patch), want)

    def test_every_layout_still_tried(self):
        for patch in ("10.1", "12.23", "16.19"):
            self.assertCountEqual(fc.layout_order(patch), fc.STRINGTABLE_LAYOUTS)

    def test_layout_names_are_the_resolver_contract(self):
        self.assertEqual({n for n, _ in fc.STRINGTABLE_LAYOUTS}, {"lol", "main", "main_locale", "fontconfig"})


class CheckBodyTest(unittest.TestCase):
    ST = "game/en_us/data/menu/en_us/lol.stringtable.json"

    def test_good_files(self):
        self.assertIsNone(fc.check_body(self.ST, b'{"entries": {"a": "b"}}'))
        self.assertIsNone(fc.check_body("game/data/menu/fontconfig_en_us.txt.json", b'{"entries": {}, "version": 5}'))
        self.assertIsNone(fc.check_body("game/data/menu/fontconfig_en_us.txt", b"RST\x02\x01rest"))
        self.assertIsNone(fc.check_body(fc.CHAMPION_SUMMARY, b'[{"id": 1}]'))
        self.assertIsNone(fc.check_body("game/data/characters/ahri/ahri.bin.json",
                                        b'{"Characters/Ahri/CharacterRecords/Root": {}}'))
        # The case of the name in the key can differ from the folder name.
        self.assertIsNone(fc.check_body("game/data/characters/monkeyking/monkeyking.bin.json",
                                        b'{"{00b31aa1}": {}, "Characters/MonkeyKing/CharacterRecords/Root": {}}'))
        # Senna in 10.1: the name was not recovered, so the key is its hash.
        self.assertEqual(fc.entry_hash("Characters/Senna/CharacterRecords/Root"), "{d6802066}")
        self.assertIsNone(fc.check_body("game/data/characters/senna/senna.bin.json", b'{"{d6802066}": {}}'))
        self.assertIsNone(fc.check_body("game/data/characters/ahri/ahri.bin", b"PROP\x02\x00\x00\x00rest"))
        self.assertIsNone(fc.check_body(fc.CONTENT_METADATA, b'{"version": "16.19.1"}'))

    def test_bad_files(self):
        bad = [
            (self.ST, b""),
            (self.ST, b'{"entries": {"a": "b"'),  # cut off
            (self.ST, b"<html>error</html>"),
            (self.ST, b'{"other": 1}'),
            ("game/data/menu/fontconfig_en_us.txt", b"<html>"),
            (fc.CHAMPION_SUMMARY, b'{"id": 1}'),
            ("game/data/characters/ahri/ahri.bin.json", b"[]"),
            ("game/data/characters/ahri/ahri.bin.json", b'{"x": {}}'),  # valid JSON, not champion data
            ("game/data/characters/ahri/ahri.bin.json", b'{"Characters/Annie/CharacterRecords/Root": {}}'),
            ("game/data/characters/ahri/ahri.bin", b'{"error": "not found"}'),
            ("game/data/characters/ahri/ahri.bin", b""),
            (fc.CONTENT_METADATA, b"{}"),
        ]
        for path, body in bad:
            with self.subTest(path=path, body=body):
                self.assertIsNotNone(fc.check_body(path, body))

    def test_size_check(self):
        body = b'{"entries": {}}'
        self.assertIsNone(fc.check_body(self.ST, body, len(body)))
        self.assertIn("size", fc.check_body(self.ST, body, len(body) + 1))


class PlanRunTest(unittest.TestCase):
    def test_first_download(self):
        self.assertEqual(fc.plan_run("v2", None, False, False), "first")
        self.assertEqual(fc.plan_run("v2", None, False, True), "first")

    def test_same_build_reuses_cache(self):
        self.assertEqual(fc.plan_run("v2", "v2", True, False), "recheck")

    def test_changed_build_stops(self):
        with self.assertRaises(fc.BuildMismatch) as cm:
            fc.plan_run("v2", "v1", True, False)
        self.assertIn("--refresh", str(cm.exception))

    def test_unknown_build_stops(self):
        with self.assertRaises(fc.BuildMismatch):
            fc.plan_run("v2", None, True, False)

    def test_refresh(self):
        self.assertEqual(fc.plan_run("v2", "v1", True, True), "refresh")
        self.assertEqual(fc.plan_run("v2", None, True, True), "refresh")


class StoredBuildTest(unittest.TestCase):
    def test_sources(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertIsNone(fc.stored_build(d, None))
            self.assertEqual(fc.stored_build(d, {"cdragon_version": "old"}), "old")
            (d / fc.CONTENT_METADATA).write_text('{"version": "saved"}')
            self.assertEqual(fc.stored_build(d, {"cdragon_version": "old"}), "saved")

    def test_has_cached_files_ignores_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertFalse(fc.has_cached_files(d / "missing"))
            (d / "manifest.json").write_text("{}")
            self.assertFalse(fc.has_cached_files(d))
            (d / "game").mkdir()
            (d / "game" / "x.json").write_text("{}")
            self.assertTrue(fc.has_cached_files(d))


def run_result(files, seconds=1.0, requests=3, layouts=None, paths=None, fetched_at="2026-10-06T00:00:00+00:00"):
    return {
        "patch": "16.19",
        "cdragon_version": "v1",
        "fetched_at": fetched_at,
        "stringtable_layout": layouts or {"en_us": "lol"},
        "stringtable_path": paths or {"en_us": "game/en_us/x.json"},
        "champions": {"playable": 1, "saved": 1},
        "downloaded_bytes": sum(f["bytes"] for f in files if f["status"] == "downloaded"),
        "http_requests": requests,
        "seconds": seconds,
        "failures": [],
        "files": files,
    }


class MergeManifestTest(unittest.TestCase):
    def setUp(self):
        first_files = [
            {"path": "a.json", "bytes": 10, "last_modified": "Mon", "downloaded_at": "T1", "status": "downloaded"},
            {"path": "b.json", "bytes": 20, "last_modified": "Mon", "downloaded_at": "T1", "status": "downloaded"},
        ]
        self.first = fc.merge_manifest(
            None, run_result(first_files, seconds=40.0, requests=170, fetched_at="2026-10-05T00:00:00+00:00"), "first")

    def test_first_download_facts(self):
        m = self.first
        self.assertEqual((m["seconds"], m["http_requests"], m["downloaded_bytes"]), (40.0, 170, 30))
        self.assertEqual(m["fetched_at"], "2026-10-05T00:00:00+00:00")
        self.assertEqual((m["file_count"], m["total_bytes"]), (2, 30))
        self.assertNotIn("status", m["files"][0])

    def test_recheck_keeps_first_download_facts(self):
        cached = [{"path": "a.json", "bytes": 10, "status": "cached"}, {"path": "b.json", "bytes": 20, "status": "cached"}]
        m = fc.merge_manifest(self.first, run_result(cached), "recheck")
        for k in fc.FIRST_DOWNLOAD_KEYS:
            self.assertEqual(m[k], self.first[k], k)
        self.assertTrue(m["first_download_complete"])
        # A second recheck still keeps them.
        m2 = fc.merge_manifest(m, run_result(cached), "recheck")
        self.assertEqual((m2["seconds"], m2["first_download_complete"]), (40.0, True))
        self.assertEqual(m["last_checked"], "2026-10-06T00:00:00+00:00")
        self.assertEqual(m["last_run"], {"mode": "recheck", "seconds": 1.0, "downloaded_bytes": 0, "http_requests": 3})
        self.assertEqual(m["files"], self.first["files"])

    def test_recheck_adds_new_files_and_locales(self):
        run = run_result(
            [{"path": "a.json", "bytes": 10, "status": "cached"},
             {"path": "c.json", "bytes": 5, "last_modified": "Tue", "downloaded_at": "T2", "status": "downloaded"}],
            layouts={"fr_fr": "lol"}, paths={"fr_fr": "game/fr_fr/x.json"})
        m = fc.merge_manifest(self.first, run, "recheck")
        self.assertEqual([f["path"] for f in m["files"]], ["a.json", "b.json", "c.json"])
        self.assertEqual(m["total_bytes"], 35)
        self.assertEqual(m["stringtable_layout"], {"en_us": "lol", "fr_fr": "lol"})
        self.assertEqual(set(m["stringtable_path"]), {"en_us", "fr_fr"})
        self.assertEqual(m["downloaded_bytes"], 30)
        self.assertEqual(m["last_run"]["downloaded_bytes"], 5)

    def test_redownloaded_file_replaces_its_entry(self):
        run = run_result([{"path": "a.json", "bytes": 11, "last_modified": "Wed", "downloaded_at": "T3", "status": "downloaded"}])
        m = fc.merge_manifest(self.first, run, "recheck")
        a = next(f for f in m["files"] if f["path"] == "a.json")
        self.assertEqual((a["bytes"], a["last_modified"]), (11, "Wed"))

    def test_legacy_cached_manifest_is_not_a_first_download(self):
        # Like data/raw/15.1 before this fix: written by a run that reused every file.
        old = {"fetched_at": "old", "seconds": 0.5, "downloaded_bytes": 0, "http_requests": 2,
               "files": [{"path": "a.json", "bytes": 10, "status": "cached"}]}
        m = fc.merge_manifest(old, run_result([{"path": "a.json", "bytes": 10, "status": "cached"}]), "recheck")
        self.assertEqual(m["files"], [{"path": "a.json", "bytes": 10}])
        for k in fc.FIRST_DOWNLOAD_KEYS:
            self.assertIsNone(m[k], k)
        self.assertFalse(m["first_download_complete"])
        self.assertEqual(m["last_run"]["seconds"], 1.0)
        # And it stays unknown on later rechecks.
        m2 = fc.merge_manifest(m, run_result([{"path": "a.json", "bytes": 10, "status": "cached"}]), "recheck")
        self.assertIsNone(m2["seconds"])
        self.assertFalse(m2["first_download_complete"])

    def test_legacy_first_download_manifest_counts(self):
        old = {"fetched_at": "old", "seconds": 30.0, "downloaded_bytes": 10, "http_requests": 9,
               "files": [{"path": "a.json", "bytes": 10, "status": "downloaded"}]}
        self.assertTrue(fc.first_download_is_complete(old))
        self.assertFalse(fc.first_download_is_complete({**old, "last_run": {"mode": "recheck"}}))
        self.assertTrue(fc.first_download_is_complete({**old, "last_run": {"mode": "first"}}))

    def test_resumed_download_without_manifest(self):
        # An interrupted first download leaves files but no manifest.
        run = run_result([{"path": "a.json", "bytes": 10, "status": "cached"},
                          {"path": "b.json", "bytes": 20, "status": "downloaded"}], seconds=9.0)
        m = fc.merge_manifest(None, run, "recheck")
        self.assertIsNone(m["seconds"])
        self.assertFalse(m["first_download_complete"])
        self.assertEqual(m["last_run"]["downloaded_bytes"], 20)
        self.assertEqual(m["file_count"], 2)

    def test_failed_file_loses_old_entry(self):
        run = run_result([{"path": "a.json", "bytes": 10, "status": "cached"}])
        run["failures"] = [{"path": "b.json", "error": "simulated outage"}]
        m = fc.merge_manifest(self.first, run, "recheck")
        self.assertEqual([f["path"] for f in m["files"]], ["a.json"])
        self.assertEqual(m["total_bytes"], 10)

    def test_first_run_with_failures_is_incomplete(self):
        run = run_result([{"path": "a.json", "bytes": 10, "status": "downloaded"}], seconds=20.0)
        run["failures"] = [{"path": "b.json", "error": "simulated outage"}]
        for mode in ("first", "refresh"):
            with self.subTest(mode=mode):
                m = fc.merge_manifest(None, run, mode)
                self.assertFalse(m["first_download_complete"])
                for k in fc.FIRST_DOWNLOAD_KEYS:
                    self.assertIsNone(m[k], k)
                self.assertEqual(m["last_run"], {"mode": mode, "seconds": 20.0, "downloaded_bytes": 10,
                                                 "http_requests": 3})
        # A recheck that downloads the missing file does not make it a complete first download.
        m = fc.merge_manifest(None, run, "first")
        fix = run_result([{"path": "a.json", "bytes": 10, "status": "cached"},
                          {"path": "b.json", "bytes": 20, "status": "downloaded"}])
        m2 = fc.merge_manifest(m, fix, "recheck")
        self.assertFalse(m2["first_download_complete"])
        for k in fc.FIRST_DOWNLOAD_KEYS:
            self.assertIsNone(m2[k], k)
        self.assertEqual((m2["file_count"], m2["total_bytes"], m2["failures"]), (2, 30, []))

    def test_first_run_without_failures_is_complete(self):
        self.assertTrue(self.first["first_download_complete"])

    def test_legacy_manifest_with_failures_is_incomplete(self):
        old = {"fetched_at": "old", "seconds": 30.0, "downloaded_bytes": 10, "http_requests": 9,
               "failures": [{"path": "b.json", "error": "404"}],
               "files": [{"path": "a.json", "bytes": 10, "status": "downloaded"}]}
        self.assertFalse(fc.first_download_is_complete(old))
        self.assertTrue(fc.first_download_is_complete({**old, "failures": []}))

    def test_refresh_starts_over(self):
        run = run_result([{"path": "a.json", "bytes": 12, "status": "downloaded"}], seconds=30.0)
        m = fc.merge_manifest(self.first, run, "refresh")
        self.assertEqual((m["seconds"], m["file_count"]), (30.0, 1))


class FakeFetcher:
    """Stands in for Fetcher. bodies maps URL suffix to bytes, None (404) or an exception."""

    def __init__(self, bodies):
        self.bodies = bodies
        self.requests = 0

    def fetch(self, url):
        self.requests += 1
        for suffix, body in self.bodies.items():
            if url.endswith(suffix):
                if isinstance(body, Exception):
                    raise body
                return body, "Mon"
        return None, None

    def listing(self, path):
        raise AssertionError("not used")


AHRI = "game/data/characters/ahri/ahri.bin.json"
AHRI_BODY = b'{"Characters/Ahri/CharacterRecords/Root": {"x": 1}}'


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dest = self.root / "16.19" / AHRI
        self.dest.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def patch_run(self, body):
        r = fc.PatchRun(FakeFetcher({AHRI: body}), "16.19", self.root)
        r.old_files = {AHRI: {"path": AHRI, "bytes": len(AHRI_BODY)}}
        return r

    def test_good_cache_is_reused(self):
        self.dest.write_bytes(AHRI_BODY)
        r = self.patch_run(RuntimeError("must not be called"))
        self.assertTrue(r.save(AHRI))
        self.assertEqual(r.files[0]["status"], "cached")

    def test_bad_cache_removed_when_download_fails(self):
        self.dest.write_bytes(AHRI_BODY[:20])
        r = self.patch_run(RuntimeError("simulated outage"))
        self.assertFalse(r.save(AHRI))
        self.assertFalse(self.dest.exists())
        self.assertEqual(r.failures, [{"path": AHRI, "error": "simulated outage"}])

    def test_bad_cache_removed_when_server_returns_404(self):
        self.dest.write_bytes(AHRI_BODY[:20])
        r = self.patch_run(None)
        self.assertFalse(r.save(AHRI))
        self.assertFalse(self.dest.exists())
        self.assertIn("404", r.failures[0]["error"])

    def test_bad_cache_replaced_by_good_download(self):
        self.dest.write_bytes(AHRI_BODY[:20])
        r = self.patch_run(AHRI_BODY)
        self.assertTrue(r.save(AHRI))
        self.assertEqual(self.dest.read_bytes(), AHRI_BODY)
        self.assertEqual(r.files[0]["status"], "downloaded")


CHARS = "game/data/characters"
AHRI_BIN = "game/data/characters/ahri/ahri.bin"
BIN_BODY = b"PROP\x02\x00\x00\x00rest"
SUMMARY_BODY = json.dumps([{"id": -1, "alias": "None"}, {"id": 103, "alias": "Ahri"},
                           {"id": 60001, "alias": "Jade_Ahri"}]).encode()


def stub_run(root, patch, bodies, listings):
    """A PatchRun whose downloads come from bodies and whose folder listings are fixed."""
    r = fc.PatchRun(FakeFetcher(bodies), patch, root)
    r.listings = dict(listings)
    return r


class ChampionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def bodies(self):
        return {fc.CHAMPION_SUMMARY: SUMMARY_BODY, AHRI: AHRI_BODY, AHRI_BIN: BIN_BODY}

    def test_before_11_1_saves_the_binary(self):
        r = stub_run(self.root, "10.1", self.bodies(), {CHARS: {"ahri": {"type": "directory"}}})
        c = r.champions()
        self.assertEqual(c, {"playable": 1, "saved": 1, "bin_saved": 1, "unmapped": [],
                             "excluded_from_summary": ["Jade_Ahri", "None"]})
        self.assertEqual((self.root / "10.1" / AHRI_BIN).read_bytes(), BIN_BODY)
        self.assertTrue((self.root / "10.1" / AHRI).exists())
        self.assertEqual(r.failures, [])

    def test_from_11_1_skips_the_binary(self):
        r = stub_run(self.root, "11.1", self.bodies(), {CHARS: {"ahri": {"type": "directory"}}})
        c = r.champions()
        self.assertNotIn("bin_saved", c)
        self.assertEqual((c["playable"], c["saved"]), (1, 1))
        self.assertFalse((self.root / "11.1" / AHRI_BIN).exists())
        self.assertNotIn(AHRI_BIN, [x["path"] for x in r.files])

    def test_missing_binary_is_a_failure(self):
        bodies = self.bodies()
        del bodies[AHRI_BIN]
        r = stub_run(self.root, "10.1", bodies, {CHARS: {"ahri": {"type": "directory"}}})
        c = r.champions()
        self.assertEqual((c["saved"], c["bin_saved"]), (1, 0))
        self.assertEqual(r.failures, [{"path": AHRI_BIN, "error": "404"}])


class RunTest(unittest.TestCase):
    def test_old_entries_for_files_gone_from_disk_are_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdir = root / "16.19"
            meta = b'{"version": "v1"}'
            (pdir / AHRI).parent.mkdir(parents=True)
            (pdir / AHRI).write_bytes(AHRI_BODY)
            (pdir / fc.CHAMPION_SUMMARY).parent.mkdir(parents=True)
            (pdir / fc.CHAMPION_SUMMARY).write_bytes(SUMMARY_BODY)
            (pdir / fc.CONTENT_METADATA).write_bytes(meta)
            old_files = [{"path": AHRI, "bytes": len(AHRI_BODY), "last_modified": "Mon", "downloaded_at": "T1"},
                         {"path": fc.CHAMPION_SUMMARY, "bytes": len(SUMMARY_BODY)},
                         {"path": "game/gone.json", "bytes": 99, "downloaded_at": "T1"}]
            (pdir / "manifest.json").write_text(json.dumps(
                {"cdragon_version": "v1", "first_download_complete": False, "files": old_files}))
            # The server would serve gone.json again, but nothing asks for it in this run.
            r = stub_run(root, "16.19", {fc.CONTENT_METADATA: meta, "game/gone.json": b"{}"},
                         {CHARS: {"ahri": {"type": "directory"}}})
            m = r.run([])
            self.assertEqual(m["last_run"]["mode"], "recheck")
            self.assertEqual([x["path"] for x in m["files"]], sorted([AHRI, fc.CHAMPION_SUMMARY]))
            self.assertEqual(m["total_bytes"], len(AHRI_BODY) + len(SUMMARY_BODY))
            # The entry for a file still on disk keeps its first-download details.
            ahri = next(x for x in m["files"] if x["path"] == AHRI)
            self.assertEqual(ahri["downloaded_at"], "T1")
            self.assertEqual(json.loads((pdir / "manifest.json").read_text()), m)


class MainKeepsGoingTest(unittest.TestCase):
    def test_one_patch_failing_does_not_stop_the_rest(self):
        ran = []

        class FakeRun:
            def __init__(self, f, patch, out, refresh=False):
                self.patch = patch

            def run(self, locales):
                ran.append(self.patch)
                if self.patch == "15.1":
                    raise RuntimeError("giving up on listing")
                return {"champions": {}, "last_run": {"mode": "first", "downloaded_bytes": 0, "seconds": 0},
                        "cdragon_version": "v", "file_count": 0, "total_bytes": 0,
                        "stringtable_layout": {}, "failures": []}

        class FakeF:
            def __init__(self, delay):
                pass

        saved = (fc.PatchRun, fc.Fetcher, fc.discover_patches, sys.argv)
        fc.PatchRun, fc.Fetcher = FakeRun, FakeF
        fc.discover_patches = lambda f: ["15.1", "16.19"]
        sys.argv = ["fetch_cdragon.py", "--patches", "15.1", "16.19"]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = fc.main()
        finally:
            fc.PatchRun, fc.Fetcher, fc.discover_patches, sys.argv = saved
        self.assertEqual(ran, ["15.1", "16.19"])
        self.assertEqual(code, 1)
        self.assertIn("15.1: FAILED, giving up on listing", out.getvalue())
        self.assertIn("16.19: build v", out.getvalue())


class LocalesTest(unittest.TestCase):
    def test_old_and_new_layouts(self):
        game = {"en_us": {"type": "directory"}, "data": {"type": "directory"}, "fr_fr.bin": {"type": "file"}}
        menu = {"main_de_de.stringtable.json": {}, "main_de_de.stringtable": {},
                "fontconfig_ja_jp.txt": {}, "fontconfig_ko_kr.txt.json": {}, "minimapicons": {}}
        self.assertEqual(fc.locales_from_listings(game, menu), ["de_de", "en_us", "ja_jp", "ko_kr"])
        self.assertEqual(fc.locales_from_listings(None, None), [])


if __name__ == "__main__":
    unittest.main()
