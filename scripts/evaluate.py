#!/usr/bin/env python3
"""Scoring (PLAN.md, "Keeping the test honest", "Tests", "False alarms").

Three steps, each a subcommand:

  judge   For each planted error (a planted set) or real bug (answer_key/confirmations.csv,
          confirmed rows), every method's flags on its record are reduced to the common format,
          pooled, shuffled and judged blind by the judge model: does this flag name the
          mismatched value or claim? A method catches an error on a run if any of its flags on
          the record is judged a catch. A model catches it if it does so on a majority of its
          runs (2 of 3); the script runs once.
  label   From the false-alarm sweep, up to LABEL_SAMPLE flags per method are drawn from run 1
          (all of them if there are that many or fewer), pooled, shuffled and labeled blind:
          real_mismatch, not_a_mismatch or cant_tell. The labeler sees the reduced flag and the
          input of its record.
  report  Primary and secondary McNemar tests, recall by rule (planted) and by kind (real bugs),
          precision, flags per 1,000 checked records, failed calls on every run, the cost of
          the sweep's run 1, Clopper-Pearson 95% intervals, and the author's spot checks.
          Given both a planted set's judgments and the sweep labels, the first report writes
          the spot-check CSV (SPOT_CHECK catch judgments from the planted set and SPOT_CHECK
          labels); fill in its "author" column and run report again. Without both it skips the
          spot checks and says so.

Methods are named on the command line as NAME=file[,file...]: one file per run, in run order.
A model run file is check_model.py's output, read as the last line of each id (a resumed run
appends a new line for each record it calls again); the script's file is baseline.py's output
and its method must be named "baseline". The primary test is strong against baseline, the
secondary small against baseline (TESTS).

A planted error is found by its planted id. A real bug is found by its record's id: the id of
each line of data/inputs/realbugs.jsonl, which check_model.py writes as "id" and baseline.py
as "planted_id".

The cost of run 1 is worked out from the logged token counts at the pinned provider's prices
(check_model.PRICES; cached prompt tokens at the cache-read price), with OpenRouter's billed
cost beside it.

Every flag is reduced to {record_id, text_field, names}, with the reason and the method's
wording removed. "names" keeps only the @Placeholder@ tokens the flag names, or else a few
quoted words (at most NAME_WORDS) with any HTML tags taken out. A baseline typed-number flag
('the typed number 50% in "ces the Cooldown by 50%."') keeps the number and up to two whole
words of the same sentence on each side, without tags, so it reads like a short quote
('"Cooldown by 50%"'): a word cut off at the edge of the script's window is dropped.

Judgments and labels are cached in --cache (one JSON line each), keyed by what the judge sees,
so an identical pair is judged once and a stopped run resumes. A judge call is retried up to
3 times; if it still fails the command stops, and running it again picks up from the cache.
--dry-run prints the count of calls still to make and the first request body, and makes no call.
"""

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_model  # noqa: E402  (OpenRouter URL, key loading and the HTTP call)

# ------------------------------------------------------------------ fixed settings
SEED = 20261006  # every random draw: shuffles, the label sample and the spot checks
LABEL_SAMPLE = 200
SPOT_CHECK = 10
NAME_WORDS = 8
TESTS = {"primary": ("strong", "baseline"), "secondary": ("small", "baseline")}
SCRIPT = "baseline"

JUDGE_MODEL = "anthropic/claude-opus-5.5"
# PLAN.md says temperature 0, but Claude Opus 5.5 rejects sampling parameters (temperature,
# top_p, top_k) and cannot turn thinking off; effort is its only setting, so it is pinned here.
JUDGE_EFFORT = "medium"
# The judge's thinking counts toward max_tokens. Its answer is a few tokens of JSON, so this
# leaves room for medium-effort thinking (16000 is the usual cap for a call that isn't streamed).
JUDGE_MAX_TOKENS = 16000
RETRIES = 3
LABELS = ["real_mismatch", "not_a_mismatch", "cant_tell"]

CATCH_RUBRIC = """You judge whether one flag raised by a tooltip checker catches one known error in a League of Legends ability tooltip.

The user message is JSON with two parts:
- "answer": the known error. It says which value or claim of the tooltip is wrong and what the data shows instead.
- "flag": the checker's flag, reduced to the record it is on (record_id), the text field, and "names": the placeholder (@Name@) or the quoted words the flag points at. The checker's reasoning has been removed.

catch is true only if the flag names the mismatched value or claim the answer describes: the same placeholder, or quoted words that hold the wrong value or claim. When the answer says which names count as a catch, follow it. A flag on the right tooltip that names a different value or claim is not a catch. Judge only what the flag names, not whether the checker could have known why.

Answer only with JSON of the form {"catch": true} or {"catch": false}."""

LABEL_RUBRIC = """You label one flag raised by a tooltip checker on a League of Legends ability tooltip.

The user message is JSON with two parts:
- "flag": the record it is on (record_id), the text field, and "names": the placeholder (@Name@) or the quoted words the flag points at. The checker's reasoning has been removed.
- "record": everything the checker saw: the text with its placeholders, the text as shown, the value each placeholder shows and the formula behind it, the numbers typed into the text, and the spell's data, level-up list and related spells.

Labels:
- real_mismatch: what the text shows at the named placeholder or words disagrees with the data in the record, and you can point to the value in the record that shows it. For example: a ratio, base value, multiplier or part that differs from the spell's coefficients, its level-up list or the matching gameplay value; a placeholder that reads the wrong value; a typed number the data contradicts; a word that contradicts the data, such as the wrong damage type.
- not_a_mismatch: the named placeholder or words agree with the data, or the only difference is rounding, style or wording that says the same thing.
- cant_tell: the record does not hold what you would need to decide, for example the value is unresolved or depends on game code the record does not show.

Decide from the record alone. Answer only with JSON of the form {"label": "real_mismatch"}, {"label": "not_a_mismatch"} or {"label": "cant_tell"}."""

CATCH_SCHEMA = {"type": "object", "properties": {"catch": {"type": "boolean"}},
                "required": ["catch"], "additionalProperties": False}
LABEL_SCHEMA = {"type": "object", "properties": {"label": {"type": "string", "enum": LABELS}},
                "required": ["label"], "additionalProperties": False}


def rng(purpose):
    """A random.Random for one named draw, seeded from SEED (str seeds are stable across runs)."""
    return random.Random(f"{SEED}:{purpose}")


# ------------------------------------------------------------------ the common flag format
PLACEHOLDER = re.compile(r"@[^@\s]+@")
QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
TYPED = re.compile(r'^the typed number (\S+) in "(.*)"$', re.S)


TAG = re.compile(r"<[^<>]*>")
BREAK = re.compile(r"</?(?:br|li|ul|ol|p|hr|rules)\b[^<>]*>", re.I)  # tags that separate words
WINDOW = 20  # baseline.py quotes a typed number with up to 20 characters of text on each side
SENTENCE_END = re.compile(r"[.!?]$")


def strip_tags(s):
    """The text without its HTML tags (a tag that separates words, such as a line break or a list
    item, becomes a space)."""
    return TAG.sub("", BREAK.sub(" ", s))


def _trim(s):
    """Surrounding spaces and punctuation off, but not the '.' that starts a number ('.5')."""
    s = s.strip(" ,;:")
    s = re.sub(r"[.,;:]+$", "", s)
    return re.sub(r"^\.+(?!\d)", "", s).strip()


def _words(s):
    s = re.sub(r"<[^<>]*$", "", re.sub(r"^[^<>]*>", "", strip_tags(s)))  # a tag cut off at either end
    w = s.split()[:NAME_WORDS]
    return '"' + _trim(" ".join(w)) + '"'


def reduce_names(names):
    """The @Placeholder@ tokens a flag names (in order, once each), or else its quoted words."""
    names = names or ""
    ph = list(dict.fromkeys(PLACEHOLDER.findall(names)))
    if ph:
        return " ".join(ph)
    quoted = [a or b for a, b in QUOTED.findall(names)]
    return _words(" ".join(quoted) if quoted else names)


def _typed_words(raw, snippet, start=None):
    """The typed number with up to two whole words of its own sentence on each side, no tags.

    snippet is baseline.py's window: up to WINDOW characters of the text on each side of the
    number, stripped of surrounding spaces. Its first word is cut off when the window began
    inside the text (start > WINDOW) and no space was stripped there; its last word when a full
    WINDOW of characters follows the number. Without start, both edge words count as cut. A cut
    word is dropped, except for the part of it beyond a tag boundary, which is whole."""
    toks = [(m.start(), m.group()) for m in re.finditer(r"\S+", snippet)]
    hits = [i for i, (p, t) in enumerate(toks) if raw in t]
    if not hits:
        return f'"{raw}"'
    expect = min(start, WINDOW) if isinstance(start, int) else 0
    at = min(hits, key=lambda i: abs(toks[i][0] + toks[i][1].find(raw) - expect))
    pos = toks[at][0] + toks[at][1].find(raw)
    cut_left = (start is None or (start > WINDOW and pos == WINDOW)) and at > 0
    cut_right = (start is None or len(snippet) - pos - len(raw) >= WINDOW) and at < len(toks) - 1
    words = [t for _, t in toks]
    if cut_left:  # keep what follows the last tag end of the cut word
        words[0] = words[0].rsplit(">", 1)[1] if ">" in words[0] else ""
    if cut_right:  # keep what comes before the last tag start of the cut word
        words[-1] = words[-1].rsplit("<", 1)[0] if "<" in words[-1] else ""
    left = [w for t in words[:at] for w in strip_tags(t).split()]
    mid = strip_tags(words[at]).split()
    right = [w for t in words[at + 1:] for w in strip_tags(t).split()]
    num = next((i for i, w in enumerate(mid) if raw in w), 0)
    left, right = left + mid[:num], mid[num + 1:] + right
    number = mid[num] if mid else raw
    for i in range(len(left) - 1, -1, -1):  # the same sentence only
        if SENTENCE_END.search(left[i]):
            left = left[i + 1:]
            break
    if not SENTENCE_END.search(number):
        for i, w in enumerate(right):
            if SENTENCE_END.search(w):
                right = right[:i + 1]
                break
    else:
        right = []
    return '"' + " ".join(left[-2:] + [number] + right[:2]) + '"'


def normalize(flag, method, record_id=None):
    """A flag in the common format {record_id, text_field, names}, with the reason removed.

    flag is one baseline line or one item of a model line's "flags"; record_id is the checked
    record it is on (a baseline line carries its own)."""
    rid = record_id or flag.get("id")
    names = flag.get("names") or ""
    m = TYPED.match(names) if method == SCRIPT else None
    if m:  # the quote stands as it is, even beside a placeholder: the flag names the number
        reduced = _words(_typed_words(m.group(1), m.group(2), flag.get("start"))[1:-1])
    else:
        reduced = reduce_names(names)
    return {"record_id": rid, "text_field": rid.rsplit(":", 1)[-1], "names": reduced}


# ------------------------------------------------------------------ inputs
def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def load_cases(path):
    """Planted errors from a planted set, or confirmed real bugs from the answer key CSV."""
    path = Path(path)
    if path.suffix == ".csv":
        out = []
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r["status"] != "confirmed":
                    continue
                rid = f"{r['prefix_patch']}:{r['locale']}:{r['champion_folder']}:{r['spell_path']}:{r['text_field']}"
                answer = (f"In {r['champion_folder']} {r['slot']} ({r['text_field']}, {r['locale']}), "
                          f"the text says: {r['text_says']}. The data says: {r['data_says']}.")
                out.append({"id": r["unit_id"], "record_id": rid, "set": "real", "group": r["mechanism"],
                            "answer": answer})
        return out
    return [{"id": o["id"], "record_id": o["record_id"], "set": "planted", "group": o["rule"],
             "answer": o["answer"]} for o in read_jsonl(path)]


def parse_methods(specs):
    """{"strong": [run1, run2, run3], ...} from NAME=file[,file...] arguments. A model run keeps
    the last line of each id; the script's lines are all kept (one line per flag)."""
    out = {}
    for s in specs:
        name, sep, files = s.partition("=")
        if not sep or not files:
            sys.exit(f"--run takes NAME=file[,file...], got {s!r}")
        runs = [read_jsonl(f) for f in files.split(",")]
        out[name] = runs if name == SCRIPT else [check_model.last_lines(r) for r in runs]
    return out


def flags_on_case(case, lines, method):
    """The method's reduced flags on the case's own record, from one run's lines. A planted error
    is matched by its planted id, a real bug by its record's id (a line's "planted_id" when it
    has one, which baseline.py writes for a wrapped input, else its "id")."""
    want = case["record_id"] if case["set"] == "real" else case["id"]
    out = []
    for ln in lines:
        if ln.get("planted_id", ln.get("id")) != want:
            continue
        items = [ln] if method == SCRIPT else ln.get("flags") or []
        out.extend(normalize(f, method, case["record_id"]) for f in items)
    return out


def sweep_flags(lines, method):
    """Every reduced flag in one sweep run (lines keyed by record id)."""
    out = []
    for ln in lines:
        items = [ln] if method == SCRIPT else ln.get("flags") or []
        out.extend(normalize(f, method, ln["id"]) for f in items)
    return out


def failed_calls(methods):
    """For each model method, its records and failed calls on each run (last line of each id)."""
    return {m: {"records_by_run": [len(r) for r in runs],
                "failed_by_run": [sum(1 for ln in r if ln.get("failed")) for r in runs]}
            for m, runs in methods.items() if m != SCRIPT}


def price_of(ln):
    """The pinned provider's prices for one model line."""
    pinned = ln.get("pinned")
    if pinned is None:  # a line written before "pinned" was logged: the model's main provider
        pinned = next(v["order"][0] for v in check_model.MODELS.values() if v["model"] == ln.get("model"))
    return check_model.PRICES[pinned]


def cost_at_prices(lines):
    """USD for these lines from their token counts at the pinned provider's prices, and the number
    of lines that logged no token counts (left out of the sum)."""
    total, missing = 0.0, 0
    for ln in lines:
        if ln.get("prompt_tokens") is None or ln.get("completion_tokens") is None:
            missing += 1
            continue
        p = price_of(ln)
        cached = ln.get("cached_tokens") or 0
        total += ((ln["prompt_tokens"] - cached) * p["input"] + cached * p["cache_read"]
                  + ln["completion_tokens"] * p["output"]) / 1e6
    return total, missing


# ------------------------------------------------------------------ the judge model
def _key(kind, *parts):
    return hashlib.sha256(json.dumps([kind, *parts], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def judge_body(rubric, user, schema_name, schema):
    return {
        "model": JUDGE_MODEL,
        "messages": [{"role": "system", "content": rubric},
                     {"role": "user", "content": json.dumps(user, ensure_ascii=False, separators=(",", ":"))}],
        "reasoning": {"effort": JUDGE_EFFORT},
        "max_tokens": JUDGE_MAX_TOKENS,
        "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        "usage": {"include": True},
    }


def call_judge(body, field, key, post=None):
    """The judge's answer (the value of field) and its usage; raises after RETRIES failed retries."""
    post = post or check_model.post_json
    error = None
    for attempt in range(RETRIES + 1):
        try:
            resp = post(body, key)
            value = json.loads(resp["choices"][0]["message"]["content"])[field]
            if field == "catch" and not isinstance(value, bool) or field == "label" and value not in LABELS:
                raise ValueError(f"bad {field}: {value!r}")
            usage = resp.get("usage") or {}
            return value, {"provider": resp.get("provider"), "prompt_tokens": usage.get("prompt_tokens"),
                           "completion_tokens": usage.get("completion_tokens"), "cost": usage.get("cost")}
        except Exception as e:  # noqa: BLE001  (any failure is retried the same way)
            error = f"{type(e).__name__}: {str(e)[:200]}"
            if attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"judge call failed after {RETRIES} retries: {error}")


class Cache:
    def __init__(self, path):
        self.path = Path(path)
        self.items = {}
        if self.path.exists():
            for o in read_jsonl(self.path):
                self.items[o["key"]] = o

    def add(self, item):
        self.items[item["key"]] = item
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def run_jobs(jobs, cache, field, dry_run, post=None):
    """Judge every job (key, body, record) not in the cache, in the given (shuffled) order."""
    todo = [j for j in dict((j[0], j) for j in jobs).values() if j[0] not in cache.items]
    if dry_run:
        print(f"{len(todo)} judge calls to make ({len(jobs)} items, {len(jobs) - len(todo)} cached or repeated)")
        if todo:
            print(json.dumps(todo[0][1], ensure_ascii=False, indent=1)[:4000])
        return False
    key = check_model.load_key() if todo else None
    if todo and not key:
        sys.exit(f"{check_model.KEY_VAR} is not set and not in {check_model.ENV_FILE}")
    for i, (k, body, rec) in enumerate(todo, 1):
        value, usage = call_judge(body, field, key, post)
        cache.add({"key": k, **rec, field: value, **usage})
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}")
    return True


# ------------------------------------------------------------------ judge
def judge(cases, methods, cache, dry_run=False, post=None):
    per = []  # (case, method, run, [flags])
    for c in cases:
        for m, runs in methods.items():
            for r, lines in enumerate(runs):
                per.append((c, m, r, flags_on_case(c, lines, m)))
    jobs = []
    for c, m, r, flags in per:
        for f in flags:
            jobs.append((_key("catch", c["answer"], f),
                         judge_body(CATCH_RUBRIC, {"answer": c["answer"], "flag": f}, "catch", CATCH_SCHEMA),
                         {"check": "catch", "answer": c["answer"], "flag": f}, c["set"]))
    rng("judge-pool").shuffle(jobs)
    if not run_jobs([j[:3] for j in jobs], cache, "catch", dry_run, post):
        return None
    out = {c["id"]: {"id": c["id"], "record_id": c["record_id"], "set": c["set"], "group": c["group"],
                     "methods": {}} for c in cases}
    for c, m, r, flags in per:
        caught = any(cache.items[_key("catch", c["answer"], f)]["catch"] for f in flags)
        d = out[c["id"]]["methods"].setdefault(m, {"runs": [], "flags": []})
        d["runs"].append(caught)
        d["flags"].append(len(flags))
    for c in out.values():
        for d in c["methods"].values():
            d["caught"] = 2 * sum(d["runs"]) > len(d["runs"])
    keys = sorted({j[0] for j in jobs})
    set_of = {j[0]: j[3] for j in jobs}
    sets = sorted({c["set"] for c in cases})
    return {"seed": SEED, "judge_model": JUDGE_MODEL, "judge_effort": JUDGE_EFFORT, "cases": list(out.values()),
            "judgments": [{**cache.items[k], "set": set_of[k]} for k in keys],
            "failed_calls": {s: failed_calls(methods) for s in sets}}


# ------------------------------------------------------------------ label
def label(inputs, methods, cache, dry_run=False, post=None):
    by_id = {o["id"]: o for o in inputs}
    summary, pool = {}, []
    for m, runs in methods.items():
        run1 = runs[0]
        flags = sweep_flags(run1, m)
        drawn = flags if len(flags) <= LABEL_SAMPLE else rng(f"label-draw:{m}").sample(flags, LABEL_SAMPLE)
        pool.extend((m, f) for f in drawn)
        s = {"records": len(inputs), "flags_run1": len(flags),
             "flags_by_run": [len(sweep_flags(r, m)) for r in runs], "drawn": [_key("label", f) for f in drawn]}
        if m != SCRIPT:
            s["calls_run1"] = len(run1)
            s["failed_by_run"] = [sum(1 for ln in r if ln.get("failed")) for r in runs]
            for k in ("prompt_tokens", "completion_tokens", "cached_tokens"):
                s[f"{k}_run1"] = sum(ln.get(k) or 0 for ln in run1)
            s["cost_run1"], s["lines_without_tokens_run1"] = cost_at_prices(run1)
            s["billed_cost_run1"] = sum(ln.get("cost") or 0 for ln in run1)
            s["lines_without_billed_cost_run1"] = sum(1 for ln in run1 if ln.get("cost") is None)
        summary[m] = s
    rng("label-pool").shuffle(pool)
    jobs = [(_key("label", f),
             judge_body(LABEL_RUBRIC, {"flag": f, "record": by_id[f["record_id"]]}, "label", LABEL_SCHEMA),
             {"check": "label", "flag": f}) for _, f in pool]
    if not run_jobs(jobs, cache, "label", dry_run, post):
        return None
    keys = sorted({j[0] for j in jobs})
    return {"seed": SEED, "judge_model": JUDGE_MODEL, "judge_effort": JUDGE_EFFORT, "methods": summary,
            "labels": [cache.items[k] for k in keys]}


# ------------------------------------------------------------------ statistics (standard library)
def binom_cdf(k, n, p):
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(1.0, sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
                        for i in range(k + 1)))


def _bisect(f, lo=0.0, hi=1.0):
    """The root of f on [lo, hi], f(lo) < 0 < f(hi)."""
    for _ in range(100):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(k, n, alpha=0.05):
    """Exact two-sided (1 - alpha) interval for k successes in n."""
    if n == 0:
        return (0.0, 1.0)
    lo = 0.0 if k == 0 else _bisect(lambda p: (1 - binom_cdf(k - 1, n, p)) - alpha / 2)
    hi = 1.0 if k == n else _bisect(lambda p: alpha / 2 - binom_cdf(k, n, p))
    return (lo, hi)


def mcnemar_exact(b, c):
    """Exact two-sided McNemar p: binomial on the b + c discordant pairs."""
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * binom_cdf(min(b, c), n, 0.5))


# ------------------------------------------------------------------ report
def _share(k, n):
    lo, hi = clopper_pearson(k, n)
    return {"k": k, "n": n, "share": k / n if n else None, "ci95": [lo, hi]}


def recall(cases, method, key):
    groups = {}
    for c in cases:
        d = c["methods"].get(method)
        if d is None:
            continue
        g = groups.setdefault(c[key] if key else "all", {"k": 0, "n": 0, "runs": [0] * len(d["runs"])})
        g["n"] += 1
        g["k"] += d["caught"]
        g["runs"] = [a + b for a, b in zip(g["runs"], d["runs"])]
    return {g: {**_share(v["k"], v["n"]), "caught_by_run": v["runs"]} for g, v in sorted(groups.items())}


def spot_check(judged, labeled, path):
    """Write the spot-check CSV if it is missing; otherwise score the author's filled-in rows.
    Catches are drawn from the planted set's judgments only."""
    path = Path(path)
    jl = {o["key"]: o for o in (judged or {}).get("judgments", []) if o.get("set") == "planted"}
    ll = {o["key"]: o for o in (labeled or {}).get("labels", [])}
    if not path.exists():
        rows = []
        for check, items, field in (("catch", jl, "answer"), ("label", ll, None)):
            keys = sorted(items)
            for k in rng(f"spot:{check}").sample(keys, min(SPOT_CHECK, len(keys))):
                f = items[k]["flag"]
                rows.append({"check": check, "key": k, "record_id": f["record_id"], "text_field": f["text_field"],
                             "names": f["names"], "answer": items[k].get(field, "") if field else "",
                             "author": ""})
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["check", "key", "record_id", "text_field", "names", "answer", "author"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {path}: fill in 'author' (catch: yes or no; label: {', '.join(LABELS)}), then run report again")
        return None
    out = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            a = r["author"].strip().lower()
            if not a:
                continue
            if r["check"] == "catch" and r["key"] in jl:
                agree = (a == "yes") == jl[r["key"]]["catch"]
            elif r["check"] == "label" and r["key"] in ll:
                agree = a == ll[r["key"]]["label"]
            else:
                continue
            o = out.setdefault(r["check"], [0, 0])
            o[0] += agree
            o[1] += 1
    return {c: _share(k, n) for c, (k, n) in out.items()}


def report(judged, labeled, spot_path):
    rep = {"seed": SEED}
    if judged:
        planted = [c for c in judged["cases"] if c["set"] == "planted"]
        real = [c for c in judged["cases"] if c["set"] == "real"]
        methods = sorted({m for c in judged["cases"] for m in c["methods"]})
        tests = {}
        for name, (a, b) in TESTS.items():
            pairs = [(c["methods"][a]["caught"], c["methods"][b]["caught"]) for c in planted
                     if a in c["methods"] and b in c["methods"]]
            if not pairs:
                continue
            nb = sum(1 for x, y in pairs if x and not y)
            nc = sum(1 for x, y in pairs if y and not x)
            tests[name] = {"model": a, "script": b, "errors": len(pairs), "model_only": nb, "script_only": nc,
                           "both": sum(1 for x, y in pairs if x and y), "neither": sum(1 for x, y in pairs if not x and not y),
                           "p": mcnemar_exact(nb, nc), "significant_for_model": mcnemar_exact(nb, nc) < 0.05 and nb > nc}
        rep["tests"] = tests
        rep["failed_calls"] = judged.get("failed_calls", {})
        rep["planted_recall"] = {m: {"all": recall(planted, m, None).get("all"), "by_rule": recall(planted, m, "group")}
                                 for m in methods if planted}
        if real:
            rep["real_bug_recall"] = {m: {"all": recall(real, m, None).get("all"), "by_kind": recall(real, m, "group")}
                                      for m in methods}
    if labeled:
        labels = {o["key"]: o["label"] for o in labeled["labels"]}
        fa = {}
        for m, s in labeled["methods"].items():
            got = [labels[k] for k in s["drawn"]]
            real_n, cant = got.count("real_mismatch"), got.count("cant_tell")
            d = {"precision": _share(real_n, len(got)), "cant_tell": cant,
                 "precision_without_cant_tell": _share(real_n, len(got) - cant),
                 "flags_run1": s["flags_run1"], "flags_by_run": s["flags_by_run"],
                 "flags_per_1000": 1000 * s["flags_run1"] / s["records"] if s["records"] else None}
            if m != SCRIPT:
                d.update({k: s[k] for k in ("calls_run1", "failed_by_run", "prompt_tokens_run1",
                                            "completion_tokens_run1", "cached_tokens_run1", "cost_run1",
                                            "lines_without_tokens_run1", "billed_cost_run1",
                                            "lines_without_billed_cost_run1")})
            fa[m] = d
        rep["false_alarms"] = fa
    if judged and labeled and any(o.get("set") == "planted" for o in judged["judgments"]):
        sc = spot_check(judged, labeled, spot_path)
        if sc is not None:
            rep["spot_check"] = sc
    else:
        rep["spot_check_skipped"] = "needs both a planted set's judgments (--judged) and the sweep labels (--labels)"
        print(f"spot checks skipped: {rep['spot_check_skipped']}")
    return rep


def _pct(s):
    if not s or s.get("share") is None:
        return "-"
    return f"{s['k']}/{s['n']} {100 * s['share']:.0f}% [{100 * s['ci95'][0]:.0f}, {100 * s['ci95'][1]:.0f}]"


def table(rep):
    out = []
    for name, t in rep.get("tests", {}).items():
        out.append(f"{name}: {t['model']} vs {t['script']} on {t['errors']} errors: model only {t['model_only']}, "
                   f"script only {t['script_only']}, both {t['both']}, neither {t['neither']}, exact McNemar p = {t['p']:.4g}")
    for title, key, sub in (("planted recall", "planted_recall", "by_rule"), ("real-bug recall", "real_bug_recall", "by_kind")):
        for m, r in rep.get(key, {}).items():
            out.append(f"{title}, {m}: {_pct(r['all'])}")
            out.extend(f"  {g}: {_pct(v)}  (by run {v['caught_by_run']})" for g, v in r[sub].items())
    for s, per in rep.get("failed_calls", {}).items():
        for m, d in per.items():
            out.append(f"failed calls, {s} runs, {m}: {d['failed_by_run']} of {d['records_by_run']} records")
    for m, d in rep.get("false_alarms", {}).items():
        extra = ""
        if "cost_run1" in d:
            extra = (f", failed calls by run {d['failed_by_run']}, cost of run 1 ${d['cost_run1']:.2f} at the pinned "
                     f"provider's prices (OpenRouter billed ${d['billed_cost_run1']:.2f})")
        out.append(f"false alarms, {m}: precision {_pct(d['precision'])}, can't tell {d['cant_tell']}, "
                   f"{d['flags_per_1000']:.1f} flags per 1,000 records (runs {d['flags_by_run']}){extra}")
    for c, s in rep.get("spot_check", {}).items():
        out.append(f"spot check, {c}: author agrees {_pct(s)}")
    return "\n".join(out)


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge", help="judge each method's flags on each planted error or real bug")
    j.add_argument("cases", help="a planted set (data/planted/<set>.jsonl) or answer_key/confirmations.csv")
    j.add_argument("--run", action="append", required=True, metavar="NAME=FILE[,FILE...]")
    j.add_argument("--cache", default="data/eval/judge_cache.jsonl")
    j.add_argument("--out", required=True)
    j.add_argument("--dry-run", action="store_true")
    lb = sub.add_parser("label", help="label a sample of each method's sweep flags (run 1)")
    lb.add_argument("inputs", help="the sweep's inputs file (data/inputs/<patch>.en_us.jsonl)")
    lb.add_argument("--run", action="append", required=True, metavar="NAME=FILE[,FILE...]")
    lb.add_argument("--cache", default="data/eval/judge_cache.jsonl")
    lb.add_argument("--out", required=True)
    lb.add_argument("--dry-run", action="store_true")
    rp = sub.add_parser("report", help="tests, recall, precision, cost and spot checks")
    rp.add_argument("--judged", action="append", default=[], help="judge output (planted set, real bugs)")
    rp.add_argument("--labels")
    rp.add_argument("--spot-check", default="data/eval/spot_check.csv")
    rp.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd in ("judge", "label"):
        methods = parse_methods(a.run)
        cache = Cache(a.cache)
        if a.cmd == "judge":
            res = judge(load_cases(a.cases), methods, cache, a.dry_run)
        else:
            res = label(read_jsonl(a.inputs), methods, cache, a.dry_run)
        if res is not None:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"wrote {a.out}")
        return 0

    judged = None
    for p in a.judged:  # a planted set and the real bugs can be judged separately and reported together
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        judged = d if judged is None else {**judged, "cases": judged["cases"] + d["cases"],
                                           "judgments": judged["judgments"] + d["judgments"],
                                           "failed_calls": {**judged.get("failed_calls", {}),
                                                            **d.get("failed_calls", {})}}
    labeled = json.loads(Path(a.labels).read_text(encoding="utf-8")) if a.labels else None
    rep = report(judged, labeled, a.spot_check)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(table(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
