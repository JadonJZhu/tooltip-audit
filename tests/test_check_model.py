"""Tests for scripts/check_model.py (no network: the HTTP layer is replaced). Run from the project root:

    python3 -m unittest tests.test_check_model
"""

import contextlib
import http.client
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_model as C  # noqa: E402

KEY = "sk-test-secret-key"
ID = "16.18:en_us:ahri:Characters/Ahri/Spells/AhriQAbility/AhriQ:keyTooltip"


def inp(id_=ID, text="Deals @TotalDamage@ magic damage."):
    return {"id": id_, "champion": "Ahri", "slot": "Q", "text_field": "keyTooltip", "text": text,
            "placeholders": {"TotalDamage": {"kind": "calc", "value": "40/65/90"}}}


def response(flags=None, content=None, provider="Nextbit"):
    if content is None:
        content = json.dumps({"flags": flags or []})
    return {"provider": provider, "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 30, "cost": 0.0012,
                      "prompt_tokens_details": {"cached_tokens": 600}}}


class Fake:
    """Stands in for post_json: returns or raises each item of `script` in turn, then repeats the last."""

    def __init__(self, *script):
        self.script, self.bodies, self.keys = list(script), [], []

    def __call__(self, body, key):
        self.bodies.append(body)
        self.keys.append(key)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


@contextlib.contextmanager
def patched(fake):
    with unittest.mock.patch.object(C, "post_json", fake), unittest.mock.patch.object(C.time, "sleep"), \
            unittest.mock.patch.dict(C.os.environ, {C.KEY_VAR: KEY}):
        yield


class TestPrompt(unittest.TestCase):
    def test_id_left_out_and_compact(self):
        s = C.render(inp())
        self.assertNotIn(ID, s)
        self.assertNotIn('"id"', s)
        self.assertNotIn(", ", s.replace("Deals @TotalDamage@ magic damage.", ""))
        self.assertEqual(json.loads(s)["champion"], "Ahri")

    def test_planted_id_never_shown(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "dev.jsonl"
            p.write_text(json.dumps({"id": "dev-001", "kind": "tooltip_calc", "answer": "secret answer",
                                     "input": inp()}) + "\n")
            (rid, record), = C.read_records(p)
        self.assertEqual(rid, "dev-001")
        body = json.dumps(C.request_body(record, "strong"))
        for hidden in ("dev-001", "secret answer", ID):
            self.assertNotIn(hidden, body)

    def test_wrapped_lines_unwrap_with_their_own_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "realbugs.jsonl"
            p.write_text(json.dumps({"id": ID, "kind": "real", "bug": "9.10-ahri-Q", "own_record": True,
                                     "input": inp()}) + "\n" + json.dumps({"id": "x", "input": inp(id_="y")}) + "\n")
            got = C.read_records(p)
        self.assertEqual([(rid, r["id"]) for rid, r in got], [(ID, ID), ("x", "y")])
        self.assertNotIn("bug", got[0][1])

    def test_instructions_first_and_identical(self):
        a = C.request_body(inp(), "small")
        b = C.request_body(inp(id_="other", text="Heals @X@."), "small")
        self.assertEqual(a["messages"][0], {"role": "system", "content": C.PROMPT})
        self.assertEqual(a["messages"][0], b["messages"][0])
        self.assertEqual(a["messages"][1]["role"], "user")
        self.assertLess(len(C.PROMPT.split()), 400)

    def test_request_settings(self):
        b = C.request_body(inp(), "strong")
        self.assertEqual(b["model"], "deepseek/deepseek-v4-pro-0813")
        self.assertEqual(b["temperature"], 1.0)
        self.assertEqual(b["max_tokens"], 32000)
        self.assertEqual(b["reasoning"], {"effort": "low"})
        self.assertEqual(b["provider"], {"order": ["coreweave/fp8"], "allow_fallbacks": False,
                                         "require_parameters": True})
        self.assertEqual(b["usage"], {"include": True})
        self.assertEqual(b["response_format"]["type"], "json_schema")
        self.assertEqual(b["response_format"]["json_schema"]["schema"]["required"], ["flags"])
        self.assertEqual(C.request_body(inp(), "strong", backup=True)["provider"]["order"], ["nebius/fp8"])
        s = C.request_body(inp(), "small")
        self.assertEqual(s["model"], "qwen/qwen3.8-27b")
        self.assertEqual((s["temperature"], s["max_tokens"], s["reasoning"]), (0, 32000, {"enabled": True}))
        self.assertEqual(s["provider"]["order"], ["deepinfra/bf16"])
        self.assertEqual(C.request_body(inp(), "small", backup=True)["provider"]["order"], ["parasail/fp8"])


class TestCall(unittest.TestCase):
    def test_success_logs_everything(self):
        fake = Fake(response([{"names": "@TotalDamage@", "reason": "Ratio differs."}]))
        with patched(fake):
            out = C.check_record("dev-001", inp(), "strong", 2, KEY)
        self.assertEqual(out["flags"], [{"names": "@TotalDamage@", "reason": "Ratio differs."}])
        self.assertFalse(out["failed"])
        self.assertEqual(out["attempts"], 1)
        self.assertEqual((out["provider"], out["prompt_version"], out["run"]), ("Nextbit", C.PROMPT_VERSION, 2))
        self.assertEqual((out["prompt_tokens"], out["completion_tokens"], out["cached_tokens"], out["cost"]),
                         (900, 30, 600, 0.0012))
        self.assertEqual(out["model"], "deepseek/deepseek-v4-pro-0813")
        self.assertTrue(out["time"].endswith("+00:00"))
        self.assertNotIn("error", out)

    def test_retries_then_succeeds_with_same_body(self):
        http = urllib.error.HTTPError(C.URL, 502, "bad gateway", {}, None)
        fake = Fake(http, TimeoutError("timed out"), response(content="not json"), response([]))
        with patched(fake):
            out = C.check_record(ID, inp(), "small", 1, KEY)
        self.assertEqual((out["attempts"], out["failed"], out["flags"]), (4, False, []))
        self.assertTrue(all(b == fake.bodies[0] for b in fake.bodies))

    def test_any_error_is_retried_and_usage_summed(self):
        billed = response(content="not json")  # billed even though it can't be parsed
        fake = Fake(http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b""), billed, response([]))
        with patched(fake):
            out = C.check_record(ID, inp(), "strong", 1, KEY, backup=True)
        self.assertEqual((out["attempts"], out["failed"]), (4, False))
        self.assertEqual((out["prompt_tokens"], out["completion_tokens"], out["cached_tokens"]), (1800, 60, 1200))
        self.assertAlmostEqual(out["cost"], 0.0024)
        self.assertEqual(out["pinned"], "nebius/fp8")

    def test_gives_up_after_three_retries(self):
        fake = Fake(response(content='{"flags": [{"names": 1}]}'))
        with patched(fake):
            out = C.check_record(ID, inp(), "small", 1, KEY)
        self.assertEqual((out["attempts"], out["failed"], out["flags"]), (4, True, []))
        self.assertEqual(len(fake.bodies), 4)
        self.assertIn("unparseable", out["error"])

    def test_http_failure_has_no_stale_provider(self):
        fake = Fake(response(content="x"), urllib.error.HTTPError(C.URL, 429, "rate", {}, None))
        with patched(fake):
            out = C.check_record(ID, inp(), "small", 1, KEY)
        self.assertTrue(out["failed"])
        self.assertIsNone(out["provider"])
        self.assertEqual(out["error"], "HTTP 429")


class TestMain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = Path(self.dir.name)
        self.src = self.d / "in.jsonl"
        self.src.write_text("".join(json.dumps(inp(id_=f"r{i}")) + "\n" for i in range(5)))
        self.out = self.d / "runs" / "x.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def run_main(self, fake, *extra):
        buf = io.StringIO()
        with patched(fake), contextlib.redirect_stdout(buf):
            C.main([str(self.src), "--model", "strong", "--run", "1", "--out", str(self.out), *extra])
        return buf.getvalue()

    def lines(self):
        return [json.loads(l) for l in self.out.read_text().splitlines()]

    def test_resume_skips_done_ids_and_key_never_written(self):
        self.out.parent.mkdir()
        self.out.write_text(json.dumps({"id": "r1", "failed": False, "flags": []}) + "\n")
        fake = Fake(response([]))
        printed = self.run_main(fake, "--workers", "3")
        self.assertEqual(len(fake.bodies), 4)
        self.assertEqual(sorted(o["id"] for o in self.lines()), ["r0", "r1", "r2", "r3", "r4"])
        self.assertEqual(set(fake.keys), {KEY})
        self.assertNotIn(KEY, self.out.read_text())
        self.assertNotIn(KEY, printed)
        self.assertIn("failed: 0 (0.0%)", printed)
        self.assertNotIn("WARNING", printed)

    def test_resume_calls_failed_records_again(self):
        self.out.parent.mkdir()
        self.out.write_text("".join(json.dumps({"id": f"r{i}", "failed": i == 1, "flags": []}) + "\n" for i in range(5)))
        fake = Fake(response([]))
        printed = self.run_main(fake)
        self.assertEqual(len(fake.bodies), 1)
        self.assertEqual([o["id"] for o in self.lines()], ["r0", "r1", "r2", "r3", "r4", "r1"])
        self.assertIn("records: 5", printed)
        self.assertIn("failed: 0 (0.0%)", printed)  # the last line of r1 counts

    def test_limit_and_failure_warning(self):
        fake = Fake(response(content="garbage"))
        printed = self.run_main(fake, "--limit", "2")
        self.assertEqual(len(self.lines()), 2)
        self.assertIn("failed: 2 (100.0%)", printed)
        self.assertIn("WARNING", printed)

    def test_dry_run_makes_no_call(self):
        fake = Fake(AssertionError("no call allowed"))
        printed = self.run_main(fake, "--dry-run")
        self.assertEqual(fake.bodies, [])
        self.assertFalse(self.out.exists())
        self.assertEqual(json.loads(printed)["messages"][0]["content"], C.PROMPT)
        self.assertNotIn(KEY, printed)

    def test_key_from_env_file(self):
        env = self.d / ".env"
        env.write_text(f"OTHER=1\n{C.KEY_VAR}='{KEY}'\n")
        with unittest.mock.patch.object(C, "ENV_FILE", env), unittest.mock.patch.dict(C.os.environ, clear=True):
            self.assertEqual(C.load_key(), KEY)


if __name__ == "__main__":
    unittest.main()
