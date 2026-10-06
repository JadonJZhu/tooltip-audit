"""Tests for scripts/evaluate.py (no network: the judge's HTTP call is faked). Run from the project root:

    python3 -m unittest tests.test_evaluate
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate as E  # noqa: E402

RID = "16.18:en_us:ahri:Characters/Ahri/Spells/AhriQAbility/AhriQ:keyTooltip"
RID2 = "16.18:en_us:zyra:Characters/Zyra/Spells/ZyraRAbility/ZyraR:keyTooltip"


class FakeJudge:
    """Answers catch true when the flag names @TotalDamage@, label real_mismatch likewise."""

    def __init__(self, fail_first=0):
        self.calls = []
        self.fail_first = fail_first

    def __call__(self, body, key):
        self.calls.append(body)
        if self.fail_first:
            self.fail_first -= 1
            raise OSError("boom")
        user = json.loads(body["messages"][1]["content"])
        hit = user["flag"]["names"] == "@TotalDamage@"
        content = {"catch": hit} if "answer" in user else {"label": "real_mismatch" if hit else "not_a_mismatch"}
        return {"choices": [{"message": {"content": json.dumps(content)}}], "usage": {"cost": 0.01}}


class Normalize(unittest.TestCase):
    def test_baseline_calc(self):
        f = {"id": RID, "names": "@TotalDamage@ shows 200/300/400 (+105% AP)", "check": "tooltip_calc"}
        self.assertEqual(E.normalize(f, "baseline"),
                         {"record_id": RID, "text_field": "keyTooltip", "names": "@TotalDamage@"})

    def test_baseline_spell_placeholder(self):
        f = {"id": RID, "names": "@spell.HweiW:Tooltip_WEOnHitDamage@ shows 20/30 (+15% AP)"}
        self.assertEqual(E.normalize(f, "baseline")["names"], "@spell.HweiW:Tooltip_WEOnHitDamage@")

    def test_baseline_typed_number(self):
        f = {"id": RID, "names": 'the typed number 50% in "ces the Cooldown by 50%."'}
        self.assertEqual(E.normalize(f, "baseline")["names"], '"Cooldown by 50%"')
        f = {"id": RID, "names": 'the typed number 2 in "cast</recast> up to 2 more times within @"'}
        self.assertEqual(E.normalize(f, "baseline")["names"], '"up to 2 more times"')

    def test_baseline_typed_number_reads_like_a_quote(self):
        def typed(snippet, start, raw):
            return E.normalize({"id": RID, "names": f'the typed number {raw} in "{snippet}"', "start": start},
                               "baseline")["names"]
        # cut words at the window's edges are dropped, tags are taken out, a whole tagged word is kept
        self.assertEqual(typed("keywordMajor> loses 100 <scaleArmor>Armor</", 163, "100"), '"loses 100 Armor"')
        self.assertEqual(typed("status> ramps up to 99% while Bel'Veth cons", 219, "99%"), '"up to 99% while Bel\'Veth"')
        # the quote stays in the number's sentence
        self.assertEqual(typed("</magicDamage> over 4 seconds. If Brand k", 160, "4"), '"over 4 seconds"')
        self.assertEqual(typed("</magicDamage> over 4 seconds.", 160, "4"), '"over 4 seconds"')
        # the window began at the text's start, so the first word is whole
        self.assertEqual(typed("If she survives for 6 seconds, she is reb", 7, "6"), '"survives for 6 seconds, she"')
        self.assertEqual(typed("Lasts .5 seconds.", 6, ".5"), '"Lasts .5 seconds"')
        self.assertEqual(typed("ing around them for 4 seconds and gains <", 86, "4"), '"them for 4 seconds and"')
        # a placeholder beside the number stays part of the quote; a list item tag separates words
        self.assertEqual(typed("@BaseStunTime@ and 2.25 seconds based on ch", 316, "2.25"),
                         '"@BaseStunTime@ and 2.25 seconds based"')
        self.assertEqual(typed("Effect2Amount@% for 2.5 seconds.<li>The Gol", 300, "2.5"), '"for 2.5 seconds"')

    def test_model_quote_without_tags(self):
        self.assertEqual(E.normalize({"names": "“<magicDamage>40 magic damage</magicDamage>”"}, "strong", RID)["names"],
                         '"40 magic damage"')
        self.assertEqual(E.normalize({"names": '".5 seconds"'}, "strong", RID)["names"], '".5 seconds"')
        self.assertEqual(E.normalize({"names": '"for 2 seconds.<br"'}, "strong", RID)["names"], '"for 2 seconds"')

    def test_model_same_rule(self):
        self.assertEqual(E.normalize({"names": "@TotalDamage@ (65/100)", "reason": "x"}, "strong", RID)["names"],
                         "@TotalDamage@")
        self.assertEqual(E.normalize({"names": "“for 8 seconds”", "reason": "x"}, "strong", RID)["names"],
                         '"for 8 seconds"')
        self.assertEqual(E.normalize({"names": "magic damage", "reason": "x"}, "small", RID)["names"],
                         '"magic damage"')
        self.assertNotIn("reason", E.normalize({"names": "x", "reason": "y"}, "small", RID))


class Stats(unittest.TestCase):
    def test_clopper_pearson(self):
        lo, hi = E.clopper_pearson(10, 10)
        self.assertAlmostEqual(lo, 0.6915, places=3)
        self.assertEqual(hi, 1.0)
        self.assertAlmostEqual(E.clopper_pearson(12, 12)[0], 0.7354, places=3)
        lo, hi = E.clopper_pearson(5, 10)
        self.assertAlmostEqual(lo, 0.1871, places=3)
        self.assertAlmostEqual(hi, 0.8129, places=3)
        self.assertEqual(E.clopper_pearson(0, 0), (0.0, 1.0))

    def test_mcnemar(self):
        self.assertAlmostEqual(E.mcnemar_exact(5, 0), 0.0625)  # 5 discordant pairs can't reach 0.05
        self.assertAlmostEqual(E.mcnemar_exact(6, 0), 0.03125)
        self.assertEqual(E.mcnemar_exact(0, 0), 1.0)
        self.assertEqual(E.mcnemar_exact(3, 3), 1.0)
        self.assertLess(E.mcnemar_exact(37, 12), 0.001)

    def test_binom_large_n(self):
        self.assertAlmostEqual(E.binom_cdf(1000, 2000, 0.5), 0.5089, places=3)


class Judge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cases = [{"id": "t-1", "record_id": RID, "set": "planted", "group": "stat_ratio", "answer": "A1"},
                      {"id": "t-2", "record_id": RID2, "set": "planted", "group": "drop_term", "answer": "A2"}]

    def tearDown(self):
        self.tmp.cleanup()

    def methods(self):
        good = {"id": "t-1", "flags": [{"names": "@TotalDamage@", "reason": "r"}]}
        miss = {"id": "t-1", "flags": [{"names": "@Other@", "reason": "r"}]}
        other_record = {"id": "t-2", "flags": [{"names": "@TotalDamage@", "reason": "r"}]}  # different error
        return {
            "strong": [[good], [good, other_record], [miss]],  # t-1 on 2 of 3 runs; t-2 on 1 of 3
            "small": [[good], [miss], [miss]],                  # t-1 on 1 of 3 only
            "baseline": [[{"id": RID, "planted_id": "t-1", "names": "@TotalDamage@ shows 1/2/3"},
                          {"id": RID2, "planted_id": "t-2", "names": "@Other@ shows 1"}]],
        }

    def test_majority_and_pooling(self):
        fake = FakeJudge()
        cache = E.Cache(self.dir / "c.jsonl")
        res = E.judge(self.cases, self.methods(), cache, post=fake)
        by = {c["id"]: c["methods"] for c in res["cases"]}
        self.assertEqual(by["t-1"]["strong"]["runs"], [True, True, False])
        self.assertTrue(by["t-1"]["strong"]["caught"])
        self.assertFalse(by["t-1"]["small"]["caught"])
        self.assertTrue(by["t-1"]["baseline"]["caught"])
        self.assertFalse(by["t-2"]["strong"]["caught"])
        self.assertFalse(by["t-2"]["baseline"]["caught"])
        # identical (answer, flag) pairs are judged once: (A1, TotalDamage), (A1, Other), (A2, TotalDamage), (A2, Other)
        self.assertEqual(len(fake.calls), 4)
        body = fake.calls[0]
        self.assertEqual(body["model"], "anthropic/claude-opus-5.5")
        self.assertEqual(body["messages"][0]["content"], E.CATCH_RUBRIC)
        self.assertNotIn("reason", body["messages"][1]["content"])
        # the cache makes a second run free
        fake2 = FakeJudge()
        E.judge(self.cases, self.methods(), E.Cache(self.dir / "c.jsonl"), post=fake2)
        self.assertEqual(fake2.calls, [])

    def test_real_bug_joins_on_record_id(self):
        cases = [{"id": "11.8-corki-E", "record_id": RID, "set": "real", "group": "tooltip_calc", "answer": "B"}]
        methods = {"strong": [[{"id": RID, "flags": [{"names": "@TotalDamage@", "reason": "r"}]},
                               {"id": RID2, "flags": [{"names": "@Other@", "reason": "r"}]}]],
                   "baseline": [[{"id": RID, "planted_id": RID, "names": "@TotalDamage@ shows 1"},
                                 {"id": RID2, "planted_id": RID2, "names": "@Other@ shows 1"}]]}
        res = E.judge(cases, methods, E.Cache(self.dir / "c.jsonl"), post=FakeJudge())
        m = res["cases"][0]["methods"]
        self.assertEqual((m["strong"]["flags"], m["baseline"]["flags"]), ([1], [1]))  # the other record isn't counted
        self.assertTrue(m["strong"]["caught"] and m["baseline"]["caught"])
        self.assertEqual({j["set"] for j in res["judgments"]}, {"real"})
        self.assertEqual(res["failed_calls"], {"real": {"strong": {"records_by_run": [2], "failed_by_run": [0]}}})

    def test_last_line_per_id_and_failed_calls(self):
        run = self.dir / "strong1.jsonl"
        run.write_text("".join(json.dumps(o) + "\n" for o in [
            {"id": "t-1", "flags": [], "failed": True},
            {"id": "t-2", "flags": [], "failed": True},
            {"id": "t-1", "flags": [{"names": "@TotalDamage@", "reason": "r"}], "failed": False}]))
        base = self.dir / "base.jsonl"
        base.write_text("".join(json.dumps({"id": RID, "planted_id": "t-1", "names": n}) + "\n"
                                for n in ("@A@ shows 1", "@B@ shows 2")))
        methods = E.parse_methods([f"strong={run}", f"baseline={base}"])
        self.assertEqual([o["failed"] for o in methods["strong"][0]], [False, True])
        self.assertEqual(len(methods["baseline"][0]), 2)  # every script flag is kept
        res = E.judge(self.cases, methods, E.Cache(self.dir / "c.jsonl"), post=FakeJudge())
        self.assertTrue(res["cases"][0]["methods"]["strong"]["caught"])
        rep = E.report(res, None, self.dir / "spot.csv")
        self.assertEqual(rep["failed_calls"]["planted"]["strong"]["failed_by_run"], [1])
        self.assertIn("failed calls, planted runs, strong: [1] of [2] records", E.table(rep))

    def test_judge_caps_tokens(self):
        body = E.judge_body(E.CATCH_RUBRIC, {"answer": "a", "flag": {}}, "catch", E.CATCH_SCHEMA)
        self.assertEqual(body["max_tokens"], E.JUDGE_MAX_TOKENS)

    def test_dry_run_makes_no_call(self):
        fake = FakeJudge()
        self.assertIsNone(E.judge(self.cases, self.methods(), E.Cache(self.dir / "c.jsonl"), dry_run=True, post=fake))
        self.assertEqual(fake.calls, [])

    def test_retry_then_stop(self):
        E.time.sleep, sleep = (lambda s: None), E.time.sleep
        try:
            v, _ = E.call_judge({"messages": [{}, {"content": json.dumps({"answer": "a", "flag": {"names": "@TotalDamage@"}})}]},
                                "catch", "k", FakeJudge(fail_first=3))
            self.assertTrue(v)
            with self.assertRaises(RuntimeError):
                E.call_judge({}, "catch", "k", FakeJudge(fail_first=4))
        finally:
            E.time.sleep = sleep

    def test_report_mcnemar_and_recall(self):
        res = E.judge(self.cases, self.methods(), E.Cache(self.dir / "c.jsonl"), post=FakeJudge())
        rep = E.report(res, None, self.dir / "spot.csv")
        t = rep["tests"]["primary"]
        self.assertEqual((t["model_only"], t["script_only"], t["both"], t["neither"]), (0, 0, 1, 1))
        self.assertEqual(t["p"], 1.0)
        self.assertEqual(rep["tests"]["secondary"]["script_only"], 1)
        self.assertEqual(rep["planted_recall"]["strong"]["by_rule"]["stat_ratio"]["k"], 1)
        self.assertEqual(rep["planted_recall"]["strong"]["all"]["caught_by_run"], [1, 2, 0])


class Label(unittest.TestCase):
    def test_sample_labels_precision_and_spot_check(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inputs = [{"id": f"16.19:en_us:c{i}:S{i}:keyTooltip", "text": "t"} for i in range(300)]
            strong = [{"id": o["id"], "flags": [{"names": "@TotalDamage@" if i % 2 else "@X@", "reason": "r"}],
                       "model": "deepseek/deepseek-v4-pro-0813", "pinned": "nextbit/fp8", "cost": 0.002,
                       "prompt_tokens": 1000, "cached_tokens": 400, "completion_tokens": 100, "failed": False}
                      for i, o in enumerate(inputs)]
            base = [{"id": inputs[0]["id"], "names": "@TotalDamage@ shows 1"}]
            fake = FakeJudge()
            res = E.label(inputs, {"strong": [strong, strong[:10]], "baseline": [base]},
                          E.Cache(d / "c.jsonl"), post=fake)
            s = res["methods"]["strong"]
            self.assertEqual(len(s["drawn"]), 200)
            self.assertEqual(s["flags_by_run"], [300, 10])
            # 300 calls of 600 input, 400 cached and 100 output tokens at nextbit/fp8's prices
            self.assertAlmostEqual(s["cost_run1"], 300 * (600 * 1.056 + 400 * 0.035 + 100 * 3.168) / 1e6)
            self.assertAlmostEqual(s["billed_cost_run1"], 0.6)
            self.assertEqual(s["lines_without_tokens_run1"], 0)
            # the labeler sees the record's input
            self.assertEqual(json.loads(fake.calls[0]["messages"][1]["content"])["record"]["text"], "t")
            # without a planted set's judgments the spot checks are skipped and no CSV is written
            rep = E.report(None, res, d / "spot.csv")
            self.assertIn("spot_check_skipped", rep)
            self.assertFalse((d / "spot.csv").exists())
            self.assertIn("OpenRouter billed $0.60", E.table(rep))
            p = rep["false_alarms"]["strong"]["precision"]
            self.assertEqual(p["n"], 200)
            self.assertEqual(rep["false_alarms"]["strong"]["flags_per_1000"], 1000.0)
            self.assertEqual(rep["false_alarms"]["baseline"]["precision"]["k"], 1)
            # with both, the first report writes the draws: catches from the planted set only
            planted = [{"id": "t-1", "record_id": RID, "set": "planted", "group": "stat_ratio", "answer": "A1"}]
            real = [{"id": "bug-1", "record_id": RID2, "set": "real", "group": "tooltip_calc", "answer": "B1"}]
            runs = {"strong": [[{"id": "t-1", "flags": [{"names": "@TotalDamage@", "reason": "r"}]},
                                {"id": RID2, "flags": [{"names": "@Y@", "reason": "r"}]}]]}
            jp = E.judge(planted, runs, E.Cache(d / "c.jsonl"), post=fake)
            jr = E.judge(real, runs, E.Cache(d / "c.jsonl"), post=fake)
            judged = {**jp, "cases": jp["cases"] + jr["cases"], "judgments": jp["judgments"] + jr["judgments"]}
            E.report(judged, res, d / "spot.csv")
            with open(d / "spot.csv", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([r["check"] for r in rows], ["catch"] + ["label"] * 10)
            self.assertEqual(rows[0]["answer"], "A1")
            labels = {o["key"]: o["label"] for o in res["labels"]}
            rows = rows[1:]
            for r in rows:
                r["author"] = labels[r["key"]]
            rows[0]["author"] = "cant_tell"
            with open(d / "spot.csv", "w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            sc = E.report(judged, res, d / "spot.csv")["spot_check"]["label"]
            self.assertEqual((sc["k"], sc["n"]), (9, 10))

    def test_draw_is_seeded(self):
        flags = list(range(500))
        self.assertEqual(E.rng("label-draw:strong").sample(flags, 200), E.rng("label-draw:strong").sample(flags, 200))


class Cases(unittest.TestCase):
    def test_answer_key_confirmed_rows(self):
        root = Path(__file__).resolve().parent.parent
        cases = E.load_cases(root / "answer_key" / "confirmations.csv")
        self.assertEqual(len(cases), 12)
        nami = next(c for c in cases if c["id"] == "10.21-nami-W")
        self.assertEqual(nami["record_id"], "10.20:en_us:nami:Characters/Nami/Spells/NamiW:keyTooltip")
        self.assertEqual(nami["group"], "tooltip_calc")
        self.assertIn("1.5", nami["answer"])


if __name__ == "__main__":
    unittest.main()
