#!/usr/bin/env python3
"""The model checker (PLAN.md, "The experiment", step 4).

Sends each record of an inputs file (data/inputs/<patch>.<locale>.jsonl) or a planted set
(data/planted/<set>.jsonl, where each line holds its input under "input") to a language model
through OpenRouter, one record per call, and writes one line per call to the --out file.

Each call sends the fixed instructions (PROMPT, the same bytes on every call) and then the
record as compact JSON. The record's "id" is left out, so the model never sees a planted id.
The model answers in JSON: {"flags": [{"names": ..., "reason": ...}]}.

Settings are fixed in MODELS and request_body(): temperature 0, reasoning off, one pinned
provider with fallbacks off. --backup uses the backup provider instead.

A call that fails (any error, or output that can't be parsed into flags) is retried up to 3
times with the same settings. After that the record is written with flags [] and failed true.
Running the same command again skips the ids whose last line in the --out file has failed
false and calls the rest again, appending a new line; readers take the last line of each id.

Each output line holds: id, model, pinned (the provider asked for), provider (the one that
served the call), prompt_version, run, time (UTC), prompt_tokens, completion_tokens,
cached_tokens and cost (each summed over every attempt that returned usage), flags, failed,
attempts, and on a failed call the last error. PRICES gives each provider's price, for
evaluate.py's cost at the pinned provider's prices.

The key is read from the environment variable OPEN_ROUTER_API_KEY, or from the .env file of
the parent folder when it is not set. --dry-run prints the first request body and makes no call.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://openrouter.ai/api/v1/chat/completions"
KEY_VAR = "OPEN_ROUTER_API_KEY"
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
RETRIES = 3
TIMEOUT = 180
MAX_TOKENS = 4000  # a cap on each answer, so a runaway answer stops and is retried rather than billed at length
FAIL_SHARE = 0.05  # PLAN.md "Keeping the test honest": more than 5% failed calls reruns the session

MODELS = {
    "strong": {"model": "deepseek/deepseek-v4-pro-0813", "order": ["nextbit/fp8"], "backup": ["coreweave/fp8"]},
    "small": {"model": "qwen/qwen3.8-27b", "order": ["deepinfra/bf16"], "backup": ["parasail/fp8"]},
}

# USD per million tokens at each provider (2026-10-06). A cached prompt token is billed at
# cache_read instead of input.
PRICES = {
    "nextbit/fp8": {"input": 1.056, "output": 3.168, "cache_read": 0.035},
    "coreweave/fp8": {"input": 1.31, "output": 3.96, "cache_read": 0.044},
    "deepinfra/bf16": {"input": 0.15, "output": 1.875, "cache_read": 0.0375},
    "parasail/fp8": {"input": 0.24, "output": 2.2, "cache_read": 0.05},
}

PROMPT_VERSION = "v1"
PROMPT = """You check one League of Legends ability tooltip text against the game data behind it.

The user message is one JSON record:
- text: the tooltip text as written, with placeholders like @Name@. filled: the same text with each placeholder replaced by the value the game shows.
- placeholders: for each placeholder, the value it shows (one value per rank, joined by /) and, for a calculation, the formula it comes from: its data values, coefficients, stats and multipliers.
- typed_numbers: numbers typed directly into the text.
- spell: the record's own spell, with its data values, effect amounts, coefficients, cooldown, cost, the calculations no placeholder shows, and its level-up list (each row's label, the value it reads and the value it shows).
- ability and referenced: the other spells of the same ability, and any other spell the record reads.
- english: only for a translation, the English text and filled text of the same tooltip.

List every place where what the text shows disagrees with the data. That can be:
- a placeholder whose value or formula disagrees with the rest of the data, such as a different ratio, base value, multiplier or part than the spell's coefficients, level-up list or matching gameplay value show;
- a placeholder that reads the wrong value;
- a number typed into the text that the data does not support;
- a word that contradicts the data, such as the wrong damage type, stat or unit, or a translation that says something different from the English.

Report only disagreements you can point to in the record. Do not report style, formatting, missing explanations, or anything the record gives you no way to check. If nothing disagrees, return an empty list.

For each flag, "names" is the placeholder as @Name@, exactly as written in text, or a short quote of the words the flag is about. "reason" is one sentence saying what the text shows and what the data says instead.

Answer only with JSON of the form {"flags": [{"names": "...", "reason": "..."}]}."""

SCHEMA = {
    "type": "object",
    "properties": {
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"names": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["names", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["flags"],
    "additionalProperties": False,
}


def read_records(path):
    """(id, input) for each line: a wrapped line (planted or real bug) gives its own id and its
    "input"; a plain input gives its id and itself."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                o = json.loads(line)
                out.append((o["id"], o["input"] if "input" in o else o))
    return out


def render(inp):
    """The record as compact JSON, without its id."""
    return json.dumps({k: v for k, v in inp.items() if k != "id"}, ensure_ascii=False, separators=(",", ":"))


def request_body(inp, model_key, backup=False):
    m = MODELS[model_key]
    return {
        "model": m["model"],
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": render(inp)}],
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "reasoning": {"enabled": False},
        "provider": {"order": m["backup" if backup else "order"], "allow_fallbacks": False,
                     "require_parameters": True},
        "response_format": {"type": "json_schema", "json_schema": {"name": "flags", "strict": True, "schema": SCHEMA}},
        "usage": {"include": True},
    }


def load_key():
    key = os.environ.get(KEY_VAR)
    if key:
        return key
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip().removeprefix("export ").strip() == KEY_VAR:
                return value.strip().strip("'\"")
    except OSError:
        pass
    return None


def post_json(body, key):
    req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_flags(resp):
    """The flags in a response, or ValueError if it holds none in the expected form."""
    try:
        content = resp["choices"][0]["message"]["content"]
        flags = json.loads(content)["flags"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"unparseable output: {type(e).__name__}") from None
    if not isinstance(flags, list) or not all(
            isinstance(f, dict) and isinstance(f.get("names"), str) and isinstance(f.get("reason"), str)
            for f in flags):
        raise ValueError("unparseable output: flags not in the expected form")
    return [{"names": f["names"], "reason": f["reason"]} for f in flags]


USAGE = ("prompt_tokens", "completion_tokens", "cached_tokens", "cost")


def usage_of(resp):
    """The usage numbers of one response, or None for each one it lacks."""
    u = (resp.get("usage") if isinstance(resp, dict) else None) or {}
    return {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"), "cost": u.get("cost")}


def check_record(rid, inp, model_key, run, key, backup=False):
    """Call the model for one record, with retries; return its log line."""
    body = request_body(inp, model_key, backup)
    resp, flags, error, attempts = None, None, None, 0
    total = dict.fromkeys(USAGE)
    while attempts <= RETRIES:
        attempts += 1
        resp = None
        try:
            resp = post_json(body, key)
            for k, v in usage_of(resp).items():  # a call that returned usage was billed, parsed or not
                if v is not None:
                    total[k] = (total[k] or 0) + v
            flags = parse_flags(resp)
            break
        except urllib.error.HTTPError as e:
            error = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001  (any failure is retried the same way)
            error = f"{type(e).__name__}: {str(e)[:200]}"
        if attempts <= RETRIES:
            time.sleep(2 * attempts)
    if not isinstance(resp, dict):
        resp = {}
    m = MODELS[model_key]
    out = {
        "id": rid,
        "model": m["model"],
        "pinned": m["backup" if backup else "order"][0],
        "provider": resp.get("provider"),
        "prompt_version": PROMPT_VERSION,
        "run": run,
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        **total,
        "flags": flags if flags is not None else [],
        "failed": flags is None,
        "attempts": attempts,
    }
    if flags is None:
        out["error"] = error
    return out


def done_lines(path):
    lines = []
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh if l.strip()]
    return lines


def last_lines(lines):
    """The last line of each id, in the order each id first appears."""
    out = {}
    for o in lines:
        out[o["id"]] = o
    return list(out.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path, help="an inputs file or a planted set")
    ap.add_argument("--model", required=True, choices=sorted(MODELS))
    ap.add_argument("--run", required=True, type=int, help="run number, written on every line")
    ap.add_argument("--backup", action="store_true", help="use the backup provider")
    ap.add_argument("--out", required=True, type=Path, help="output file, e.g. runs/<name>.jsonl")
    ap.add_argument("--limit", type=int, help="only the first K records of the input file")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true", help="print the first request body and make no call")
    a = ap.parse_args(argv)

    records = read_records(a.path)[:a.limit] if a.limit else read_records(a.path)
    if a.dry_run:
        print(json.dumps(request_body(records[0][1], a.model, a.backup), ensure_ascii=False, indent=1))
        return 0
    key = load_key()
    if not key:
        sys.exit(f"{KEY_VAR} is not set and not in {ENV_FILE}")

    done = {o["id"] for o in last_lines(done_lines(a.out)) if not o.get("failed")}
    todo = [(rid, inp) for rid, inp in records if rid not in done]
    print(f"{len(records)} records, {len(records) - len(todo)} already in {a.out}, {len(todo)} to call")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "a", encoding="utf-8") as fh, \
            concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(check_record, rid, inp, a.model, a.run, key, a.backup) for rid, inp in todo]
        for fut in concurrent.futures.as_completed(futures):
            fh.write(json.dumps(fut.result(), ensure_ascii=False) + "\n")
            fh.flush()

    lines = last_lines(done_lines(a.out))
    failed = sum(1 for o in lines if o["failed"])
    share = failed / len(lines) if lines else 0.0
    print(f"records: {len(lines)} in {a.out} (last line of each); failed: {failed} ({share:.1%})")
    if share > FAIL_SHARE:
        print(f"WARNING: more than {FAIL_SHARE:.0%} of calls failed; PLAN.md says rerun on the backup providers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
