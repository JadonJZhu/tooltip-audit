#!/usr/bin/env python3
"""Mine Riot's League of Legends patch notes for tooltip and text corrections.

Downloads the official English patch notes pages (cached under data/patch_notes/),
pulls out every line that reports a tooltip, ability description or other text
correction, and writes them to answer_key/candidates.csv for hand review.

Each line also gets the CommunityDragon folders to compare (patches.py has the rule), and
for champion lines each champion's CommunityDragon folder and, where the line or its
heading names one, that champion's ability slot (P, Q, W, E or R). answer_key/README.md
describes the columns.

Each line gets a confidence:
  high       a fix whose subject is a tooltip / description / displayed value
  borderline mentions tooltip-like text but may be a balance change, a non-ability
             text, a game-mode-only item, or otherwise needs a human look

Run from the project root:
  python3 scripts/mine_patch_notes.py                 # 2020 to now
  python3 scripts/mine_patch_notes.py --from-year 2024
  python3 scripts/mine_patch_notes.py --offline       # re-extract from cache only
"""

import argparse
import csv
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import patches as cdragon

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "patch_notes"
DD_CACHE = ROOT / "data" / "ddragon"
OUT = ROOT / "answer_key" / "candidates.csv"

BASE = "https://www.leagueoflegends.com/en-us/news/game-updates/"
LISTING = BASE
UA = "tooltip-audit research script (patch notes reader; contact via GitHub)"
DELAY = 1.0  # seconds between live requests


# ---------------------------------------------------------------- fetching

_last_request = [0.0]


def fetch(url, retries=4):
    """GET a URL politely. Returns (status, text). 404 is returned, not raised."""
    for attempt in range(retries):
        wait = DELAY - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return e.code, ""
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            err = e
        backoff = 2 ** attempt * 2
        print(f"  retry {attempt + 1} for {url} after {err}; waiting {backoff}s", file=sys.stderr)
        time.sleep(backoff)
    raise RuntimeError(f"failed to fetch {url}")


def next_data(page_html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, re.S)
    return json.loads(m.group(1)) if m else None


def parse_article(page_html):
    """Return {title, published, body} for a patch notes page, or None."""
    d = next_data(page_html)
    if not d:
        return None
    page = d.get("props", {}).get("pageProps", {}).get("page") or {}
    blades = page.get("blades") or []
    body = [b for b in blades if b.get("type") == "patchNotesRichText"]
    if not body:
        return None
    mast = [b for b in blades if b.get("type") == "articleMasthead"]
    return {
        "title": page.get("title") or "",
        "published": (mast[0].get("publishDate") if mast else None) or "",
        "body": body[0]["richText"]["body"],
    }


# ---------------------------------------------------------------- discovery

# Patches whose page slug follows no pattern (found by web search, title checked).
# 13.1B took the place of 13.2, which has no page.
ODD_SLUGS = {(2020, 17): ["patch-10-16b-notes"], (2023, 2): ["patch-13-1b-notes"]}


def candidate_slugs(year, n):
    """URL slugs Riot has used for League patch notes, newest pattern first.

    Observed: 2024 patch-14-10-notes; 2025 patch-25-s1-1-notes, patch-2025-s1-3-notes,
    patch-25-04-notes; 2026 patch-26-1-notes, league-of-legends-patch-26-19-notes.
    One-offs such as lol-patch-14-13-notes are tried last for every year.
    """
    yy = year % 100
    major = yy if year >= 2025 else yy - 10  # 2024 -> 14, 2023 -> 13
    if year >= 2026:
        slugs = [f"league-of-legends-patch-{yy}-{n}-notes", f"patch-{yy}-{n}-notes",
                 f"patch-{yy}-{n:02d}-notes"]
    elif year == 2025 and n <= 3:
        slugs = [f"patch-25-s1-{n}-notes", f"patch-2025-s1-{n}-notes"]
    elif year == 2025:
        slugs = [f"patch-25-{n:02d}-notes", f"patch-25-{n}-notes"]
    else:
        slugs = [f"patch-{major}-{n}-notes"]
    return list(dict.fromkeys(slugs + [f"lol-patch-{major}-{n}-notes"] + ODD_SLUGS.get((year, n), [])))


def slugs_from_listing():
    """Slugs of League (not TFT) patch notes linked from the game-updates listing."""
    status, text = fetch(LISTING)
    if status != 200:
        return []
    found = set(re.findall(r"game-updates/((?:league-of-legends-)?patch-[a-z0-9-]*?notes)", text))
    return sorted(found)


def load_index():
    p = CACHE / "_index.json"
    if p.exists():
        idx = json.loads(p.read_text())
        idx.setdefault("missing", [])
        idx.setdefault("unparsed", [])
        return idx
    return {"found": {}, "missing": [], "unparsed": []}


def save_index(idx):
    (CACHE / "_index.json").write_text(json.dumps(idx, indent=1, sort_keys=True))


def get_slug(slug, idx, offline, recheck_missing):
    """Return the cached article for a slug, downloading it if needed.

    A 404 goes in idx["missing"] and is not asked for again unless recheck_missing.
    A page that loads but can't be parsed goes in idx["unparsed"] and is asked for
    again on every run, because it may be a real patch page in a new layout.
    """
    path = CACHE / f"{slug}.json"
    if path.exists():
        return json.loads(path.read_text())
    if offline or (slug in idx["missing"] and not recheck_missing):
        return None
    url = BASE + slug + "/"
    status, text = fetch(url)
    art = parse_article(text) if status == 200 else None
    if not art:
        bucket, other = ("unparsed", "missing") if status == 200 else ("missing", "unparsed")
        if slug not in idx[bucket]:
            idx[bucket].append(slug)
        if slug in idx[other]:
            idx[other].remove(slug)
        return None
    art["slug"] = slug
    art["url"] = url
    path.write_text(json.dumps(art))
    for bucket in ("missing", "unparsed"):
        if slug in idx[bucket]:
            idx[bucket].remove(slug)
    return art


def patch_key(title):
    """Sort key and normalized name from a title like 'Patch 25.S1.2 Notes'.

    A lettered patch such as 13.1B keeps its letter: key (2023, 1, "b") sorts after
    13.1, key (2023, 1, ""), without merging with it.
    """
    m = re.search(r"(\d{1,4})\.(S1\.)?(\d+)([a-z])?(?![a-z0-9])", title, re.I)
    if not m:
        return None, title
    major = int(m.group(1)) % 100
    year = 2000 + major if major >= 25 else 2010 + major
    minor = int(m.group(3))
    letter = (m.group(4) or "").lower()
    return (year, minor, letter), m.group(1) + "." + (m.group(2) or "") + m.group(3) + letter.upper()


def discover(from_year, to_year, offline, recheck_missing):
    CACHE.mkdir(parents=True, exist_ok=True)
    idx = load_index()
    articles = {}
    extra = [] if offline else slugs_from_listing()
    for year in range(to_year, from_year - 1, -1):
        misses_in_a_row = 0
        for n in range(1, 26):
            art = None
            for slug in candidate_slugs(year, n):
                art = get_slug(slug, idx, offline, recheck_missing)
                if art:
                    break
            if art:
                articles[art["slug"]] = art
                misses_in_a_row = 0
            else:
                # a page that loaded but didn't parse may be the live patch in a new
                # layout, so it must not end the search
                if not any(sl in idx["unparsed"] for sl in candidate_slugs(year, n)):
                    misses_in_a_row += 1
                # the newest year ends at the live patch; stop probing past it
                if year == to_year and misses_in_a_row >= 3:
                    break
        save_index(idx)
    for slug in extra:
        if slug in articles:
            continue
        art = get_slug(slug, idx, offline, recheck_missing)
        if art:
            key, _ = patch_key(art["title"])
            if key and from_year <= key[0] <= to_year:
                articles[slug] = art
    save_index(idx)
    # drop duplicates that resolve to the same patch (keep first slug seen)
    by_patch = {}
    for art in articles.values():
        key, name = patch_key(art["title"])
        if key is None:
            continue
        art["patch_name"] = name
        art["key"] = key
        by_patch.setdefault(key, art)
    return [by_patch[k] for k in sorted(by_patch, reverse=True)], sorted(idx["unparsed"])


# ---------------------------------------------------------------- names

def dd_get(path):
    local = DD_CACHE / path.replace("/", "_")
    if local.exists():
        return json.loads(local.read_text())
    status, text = fetch("https://ddragon.leagueoflegends.com/" + path)
    if status != 200:
        print(f"warning: Data Dragon {path} returned {status}", file=sys.stderr)
        return None
    DD_CACHE.mkdir(parents=True, exist_ok=True)
    local.write_text(text)
    return json.loads(text)


# First words of champion names that are ordinary words, so not safe as a short name.
NOT_SHORT_NAMES = {"dr.", "master", "miss", "twisted"}


def version_picks(versions):
    """The latest Data Dragon version and the first of each year back to 2020 (10.1)."""
    picks = [versions[0]] if versions else []
    for major in range(int(versions[0].split(".")[0]) if versions else 0, 9, -1):
        v = next((v for v in versions if v.startswith(f"{major}.1.")), None)
        if v and v not in picks:
            picks.append(v)
    return picks


def load_names(offline):
    """Champion, item, rune and summoner spell names from Data Dragon (several versions).

    The latest version plus the first version of each year from 2020 on, so that
    runes and items removed since (Spellbinder, Ravenous Hunter, Predator) are known.
    Offline, only versions already saved under data/ddragon are read.
    """
    names = {}  # lower-case alias -> (display name, area)
    try:
        if offline and not (DD_CACHE / "api_versions.json").exists():
            print("warning: no saved Data Dragon version list", file=sys.stderr)
            return names
        versions = dd_get("api/versions.json") or []
    except RuntimeError as e:
        print(f"warning: Data Dragon unreachable: {e}", file=sys.stderr)
        return names
    for v in version_picks(versions):
        files = {}
        for kind in ("champion", "item", "runesReforged", "summoner"):
            path = f"cdn/{v}/data/en_US/{kind}.json"
            if offline and not (DD_CACHE / path.replace("/", "_")).exists():
                print(f"warning: {path} not saved; run once without --offline", file=sys.stderr)
                files[kind] = None
                continue
            try:
                files[kind] = dd_get(path)
            except RuntimeError as e:
                print(f"warning: {e}", file=sys.stderr)
                files[kind] = None
        champs, items, runes, spells = (files[k] for k in ("champion", "item", "runesReforged", "summoner"))
        for c in (champs or {}).get("data", {}).values():
            names.setdefault(c["name"].lower(), (c["name"], "champion"))
            names.setdefault(c["id"].lower(), (c["name"], "champion"))
        for it in (items or {}).get("data", {}).values():
            nm = re.sub(r"<[^>]+>", "", it.get("name", "")).strip()
            if len(nm) > 3:
                names.setdefault(nm.lower(), (nm, "item"))
        for tree in runes or []:
            for slot in tree["slots"]:
                for r in slot["runes"]:
                    names.setdefault(r["name"].lower(), (r["name"], "rune"))
        for s in (spells or {}).get("data", {}).values():
            names.setdefault(s["name"].lower(), (s["name"], "summoner spell"))
    # Data Dragon calls Wukong MonkeyKing; Nunu & Willump is usually just Nunu in notes
    names.pop("monkeyking", None)
    add_short_names(names)
    return names


def load_abilities(offline):
    """{champion name, lower case: {ability name: set of slots}} from Data Dragon's championFull.

    Read for the same versions as load_names, so ability names changed by a rework are known
    under both. A name that has sat in two slots of the same champion keeps both, and
    parse_slots then takes no slot from it.
    """
    out = {}
    versions = dd_get("api/versions.json") if not offline or (DD_CACHE / "api_versions.json").exists() else None
    for v in version_picks(versions or []):
        path = f"cdn/{v}/data/en_US/championFull.json"
        if offline and not (DD_CACHE / path.replace("/", "_")).exists():
            print(f"warning: {path} not saved; run once without --offline", file=sys.stderr)
            continue
        try:
            full = dd_get(path)
        except RuntimeError as e:
            print(f"warning: {e}", file=sys.stderr)
            continue
        for c in (full or {}).get("data", {}).values():
            table = out.setdefault(c["name"].lower(), {})
            for slot, spell in zip("QWER", c.get("spells") or []):
                table.setdefault(spell["name"].replace("’", "'"), set()).add(slot)
            if c.get("passive", {}).get("name"):
                table.setdefault(c["passive"]["name"].replace("’", "'"), set()).add("P")
    return out


def add_short_names(names):
    """Short forms the notes use: Jarvan for Jarvan IV, Jak'Sho for Jak'Sho, The Protean.

    A champion's first word is added only when no other name starts with it and it
    isn't an ordinary word (Miss, Master). An item is also known by its name up to
    the first comma.
    """
    first = {}
    for alias, (name, area) in names.items():
        if area == "champion" and " " in name:
            first.setdefault(name.split()[0].lower(), set()).add(name)
    for word, owners in first.items():
        if len(owners) == 1 and word not in NOT_SHORT_NAMES and word not in names:
            names[word] = (next(iter(owners)), "champion")
    for alias, (name, area) in list(names.items()):
        if area == "item" and "," in alias:
            names.setdefault(alias.split(",")[0].strip(), (name, area))


# A champion's ability named after "<Champion>'s", up to the word tooltip, description or
# name: "Sona's E - Song of Celerity's tooltip", "Kindred's Passive - Mark of the Kindred's".
ABILITY_PHRASE = re.compile(
    r"'s?\s+(?:(?:Passive|[QWER])\s*[-\u2013:]\s*)?"
    r"(?:[A-Z][\w'!-]*|of|the|de|and)(?:\s+(?:[A-Z][\w'!-]*|of|the|de|and))*?"
    r"(?:'s?)?\s+(?:tool ?tips?|descriptions?|names?)\b")


def find_subjects(text, names):
    """Known names in the text as whole words, in order of appearance.

    A name inside a longer match is dropped (Blade of the Ruined King is not Ruined King).
    An item, rune or spell name inside a champion's possessive ability phrase is dropped
    too: in "Sona's E - Song of Celerity's tooltip" Celerity is Sona's ability, not the
    rune, and in "Kindred's Passive - Mark of the Kindred" Mark is not the summoner spell.
    Returns [(name, area)].
    """
    text = text.replace("’", "'")
    low = text.lower()
    hits = []
    for alias, (name, area) in names.items():
        if len(alias) < 3:
            continue
        i = low.find(alias)
        while i != -1:
            before = low[i - 1] if i > 0 else " "
            after = low[i + len(alias)] if i + len(alias) < len(low) else " "
            # names are proper nouns: skip "clarity" or "heal" written as ordinary words
            if not before.isalnum() and not after.isalnum() and not text[i].islower():
                hits.append((i, i + len(alias), name, area))
            i = low.find(alias, i + 1)
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    ability_spans = []
    for start, stop, name, area in hits:
        if area == "champion":
            m = ABILITY_PHRASE.match(text, stop)
            if m:
                ability_spans.append((stop, m.end()))
    out, end = [], -1
    for start, stop, name, area in hits:
        if start < end:
            continue  # overlaps an earlier, longer match
        if area != "champion" and any(a <= start < b for a, b in ability_spans):
            continue  # part of a champion's ability name
        end = stop
        if (name, area) not in out:
            out.append((name, area))
    # "Sona's Song of Celerity": a champion's own ability can share a rune/item word
    champs = [h for h in out if h[1] == "champion"]
    if champs and re.search(r"(?:'|’)s\b", text):
        out = champs + [h for h in out if h[1] != "champion"]
    return out


# ---------------------------------------------------------------- parsing

class NotesParser(HTMLParser):
    """Turn patch notes HTML into lines with their heading context.

    Layouts seen:
      2019-2022: h2 section > h3.change-title subject > h4 ability > div.attribute-change
                 (span.attribute label, span.attribute-before, span.attribute-after)
      2022-2024: h2 section > h3.change-title subject > h4 ability > ul/li
      2025 on:   h2 section > h4 category > <p><strong>Subject</strong></p> > ul/li
    Designer context (blockquote) is kept but marked, because it sometimes says a
    tooltip will lag a change ("tooltip will be updated next patch").
    """

    BLOCK = {"li", "p", "h2", "h3", "h4", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.ctx = {"section": "", "category": "", "subject": "", "ability": ""}
        self.stack = []  # open block elements: [tag, text parts, has_strong_only]
        self.quote_depth = 0
        self.strong_text = []
        self.in_strong = 0
        self.divs = []   # True for each open div that is an attribute-change line
        self.spans = []  # class of each open span

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if tag == "blockquote":
            self.quote_depth += 1
        if tag == "div":
            is_attr = "attribute-change" in cls.split()
            self.divs.append(is_attr)
            if is_attr:
                self.stack.append(["div", [], cls])
        if tag == "span":
            self.spans.append(cls)
        if tag in self.BLOCK:
            if tag == "li" and self.stack and self.stack[-1][0] == "li":
                # nested list: flush the parent text so far as its own line
                self._emit(self.stack[-1], partial=True)
            self.stack.append([tag, [], dict(attrs).get("class", "")])
        if tag == "strong" or tag == "b":
            self.in_strong += 1
        if tag == "br" and self.stack:
            self.stack[-1][1].append(" ")

    def handle_endtag(self, tag):
        if tag == "div" and self.divs and self.divs.pop():
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == "div":
                    self._emit(self.stack.pop(i))
                    break
        if tag == "span" and self.spans:
            if self.spans.pop().split() == ["attribute"] and self.stack:
                self.stack[-1][1].append(": ")
        if tag == "strong" or tag == "b":
            self.in_strong = max(0, self.in_strong - 1)
        if tag in self.BLOCK:
            # close the innermost matching element
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    el = self.stack.pop(i)
                    self._close(el)
                    break
        if tag == "blockquote":
            self.quote_depth = max(0, self.quote_depth - 1)

    def handle_data(self, data):
        # "new" / "updated" / "removed" badges in old notes are not part of the sentence
        if self.spans and set(self.spans[-1].split()) & {"new", "updated", "removed", "change-indicator"}:
            if "change-indicator" in self.spans[-1] and self.stack:
                self.stack[-1][1].append(" ⇒ ")
            return
        if self.stack:
            self.stack[-1][1].append(data)
            if self.in_strong:
                self.strong_text.append(data)

    def _text(self, el):
        return re.sub(r"\s+", " ", "".join(el[1])).strip()

    def _emit(self, el, partial=False):
        t = self._text(el)
        if partial:
            el[1].clear()
        if t:
            self.lines.append(dict(self.ctx, text=t, tag=el[0], quote=bool(self.quote_depth)))

    def _close(self, el):
        tag, cls = el[0], el[2]
        t = self._text(el)
        strong = re.sub(r"\s+", " ", "".join(self.strong_text)).strip()
        self.strong_text = []
        if tag == "h2":
            self.ctx = {"section": t, "category": "", "subject": "", "ability": ""}
        elif tag == "h3":
            # 2024 layout: a champion/item heading ends the previous sub-heading
            self.ctx.update(subject=t, ability="", category="")
        elif tag == "h4":
            if ("ability-title" in cls or re.match(r"^(Passive|[QWER])\s*[-\u2013:]", t)
                    or re.match(r"^(base )?stats$", t, re.I)):
                self.ctx["ability"] = t
            else:
                self.ctx.update(category=t, ability="")
        elif tag == "p" and t and strong == t and len(t) < 80 and not self.quote_depth:
            if re.match(r"^(Passive|[QWER])\s*[-\u2013:]", t) or re.match(r"^(Passive|[QWER])$", t):
                self.ctx["ability"] = t
            else:
                self.ctx.update(subject=t, ability="")
        elif tag in ("li", "p", "blockquote"):
            self._emit(el)


def extract_lines(body):
    p = NotesParser()
    p.feed(body)
    p.close()
    return p.lines


# ---------------------------------------------------------------- classification

# A line must hit one of these to be considered at all.
TEXT_HINT = re.compile(
    r"tool ?tips?|descriptions?\b|\btext\b|typo|now correctly (?:display|show|state|list|say|read|reflect)"
    r"|displays? the (?:correct|right)|incorrectly (?:display|show|state|list|say|said|read|reflect)"
    r"|(?:was|were|is) (?:displaying|showing|listing|stating|saying)"
    r"|display(?:ed|ing)? (?:the )?(?:wrong|incorrect|inaccurate)|(?:wrong|incorrect|inaccurate) (?:value|number|damage|information|info)"
    r"|(?:correctly|accurately) (?:display|show|state|list|say|read|reflect)"
    r"|translation|translated (?:text|tooltip)|locali[sz]ation|misspell|spelled|wording|reworded|clarif"
    r"|debug strings?|outdated information|no longer states|did not display its",
    re.I)

# Things that mention text but are not ability/item/rune/spell text.
NOT_GAME_TEXT = re.compile(
    r"\bvfx\b|\bsfx\b|particle|animation|voice ?(?:line|over)|\bvo\b|splash|chroma|emote|icon\b|(?<!second )\bskins?\b|skin line"
    r"|loading screen|\bclient\b|\bstore\b|profile|mission|event pass|battle pass|pass purchase|\btoken|\bhonor|chat\b|lobby"
    r"|champ select|\bclash\b|ranked|replay|spectat|match history|post-?game|end of game|\bcollections?\b"
    r"|eternals|mastery|challenge|\btitle\b|banner|crest|summoner icon|\bhextech crafting|loot|item shop ui|shop (?:page|ui|window)"
    r"|settings|hotkey|key ?bind|scoreboard|\bkill feed|announcer|subtitle|closed caption|\bfont\b|text chat"
    r"|floating text|combat text|nameplate|health ?bar|\bminimap|\bping|recommended|item set|practice tool"
    r"|champion select|death recap|champion details|\bmodal\b|home ?page",
    re.I)

# Game modes whose content is not in the Summoner's Rift champion/item/rune data.
MODE = re.compile(r"\barena\b|\baram\b|\burf\b|swarm|brawl|nexus blitz|one for all|ultbook|ultimate spellbook"
                  r"|\btft\b|teamfight tactics|doom bots|augment|\bmayhem\b|\bheist\b"
                  r"|demacia rising", re.I)

# The line is about a text being wrong, rather than mentioning text in passing.
FIX_SIGNAL = re.compile(
    r"fixed|\bfix\b|bug|incorrect|wrong|inaccurate|correctly|accurate|properly|scaling unchanged|duration unchanged"
    r"|(?:actual|functionality is entirely) \w* ?unchanged|only (?:the )?tooltip|only (?:affected|reflected in) (?:the |his |her |its )?tooltip"
    r"|was (?:missing|displaying|showing|stating|saying|listing)|typo|misspell|didn't|did not|wasn't|was not"
    r"|no longer (?:blank|displays debug)|debug text|mismatch|outdated|out of date|now matches", re.I)

# A tooltip rewritten for clarity or to show more numbers: an improvement, not a fixed mismatch.
IMPROVEMENT = re.compile(r"clarif|more clearly|for clarity|improve|now shows|now displays|added .* to .*tooltip"
                         r"|tooltip (?:has been )?updated(?! to (?:reflect|match))|updated (?:the )?tooltip|styling|formatting"
                         r"|spacing|capitali[sz]", re.I)
BUG_WORDS = re.compile(r"\bbug|fixed|\bfix\b|unchanged|only reflected|incorrect|wrong|inaccurate|did not|didn't|wasn't|omitted|missing|debug", re.I)

# Balance-change line: "Damage: 60 ⇒ 80" style.
BALANCE = re.compile(r"⇒|=>|→|\s->\s|\b(?:increased|decreased|reduced|lowered|raised) from \d"
                     r"|no longer (?:increases|decreases|grants|gives|deals|reduces|applies)", re.I)

# Reasons a line that reads like a text fix is still not a static text mismatch.
# Each keeps the line out of "high" and writes its note.
NOT_STATIC_TEXT = [
    (re.compile(r"as (?:her|his|its|their|the) tooltips? (?:states?|says?|describes?)"
                r"|match(?:es|ed)? (?:the|its|his|her|their) (?:(?:ability|item|spell|rune)(?:['’]s)? )?tooltips?"
                r"|(?:in)?consistent with (?:the |its |his |her |their )?(?:values? (?:in|of) )?"
                r"(?:the |its |his |her |their )?(?:(?:ability|item|spell|rune)(?:['’]s)? )?tooltips?"
                r"|as (?:stated|described|listed) in (?:its|the|his|her|their) tooltip|mentioned in", re.I),
     "game behavior fixed to match the text (text was right)"),
    (re.compile(r"\bhover|missing (?:its |their |his |her |the )?tooltips?\b|not display (?:its |their |the )?tooltips?\b"
                r"|tooltips? (?:would not|wouldn't|did not|didn't) (?:appear|show up)", re.I),
     "tooltip not appearing, not wrong text"),
    (re.compile(r"(?:would not|wouldn't|did not|didn't|not) update\b[^.]{0,30}\b(?:when|while|during)"
                r"|properly updates|updat\w* (?:in real time|dynamically)", re.I),
     "display not updating during play, not static text"),
    (re.compile(r"\btrack|counter\b|\bcount\b|(?:actual|current) number of|currently (?:have|placed)|already claimed"
                r"|(?:damage|healing|shielding) (?:done|blocked|prevented)|blocked damage", re.I),
     "live stat tracker, not static text"),
    (re.compile(r"\bcollections? tab", re.I), "Collection tab text, not in-game text"),
    (re.compile(r"tooltips? will be updated|will be updated (?:next|in a future) patch", re.I),
     "designer note: tooltip lags a change"),
]

# The text the line is about belongs to an item, even if a champion is named too:
# "Bloodward's item description", "Ornn's forgeable items having debug strings".
ITEM_TEXT = re.compile(r"\bitem(?:['’]s)?\s+(?:descriptions?|tool ?tips?|text|names?)\b|\binventory tool ?tip"
                       r"|\bitems\s+(?:having|that|showing|displaying|stating)\b", re.I)

NUMBER_HINT = re.compile(
    r"\d|value|number|amount|cooldown|duration|second|percent|ratio|scaling|\bAD\b|\bAP\b|range|cost"
    r"|damage (?:value|number|amount)|stats?\b|\bmana\b|\bhealth\b|\barmor\b|\bheal", re.I)
WORDING_HINT = re.compile(
    r"magic damage|physical damage|true damage|bonus|total|said|stated|stating|saying|wording|clarif|mention"
    r"|missing|omit|didn't (?:mention|include|say)|reword|describ|explain|incorrectly (?:said|stated)"
    r"|refer|typo|misspell|spelled", re.I)
TRANSLATION_HINT = re.compile(r"translation|translated|locali[sz]|languages\b|non-english|chinese|korean|japanese|french"
                              r"|german|spanish|portuguese|russian|turkish|polish|italian|vietnamese|\bthai\b"
                              r"|\bin (?:some|certain|several) "
                              r"(?:regions|locales)", re.I)


def quote_for(text, names, limit=300):
    """The quote column: the whole line, or for a long line the sentences about the text.

    A text sentence that names nobody ("(tooltip also now correctly reflects ...)")
    keeps the sentence before it, so the quote still says what it is about.
    """
    if len(text) > 200:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        keep = set()
        for i, x in enumerate(sentences):
            if TEXT_HINT.search(x):
                keep.add(i)
                if i and not find_subjects(x, names):
                    keep.add(i - 1)
        text = " ... ".join(sentences[i] for i in sorted(keep))
    return text if len(text) <= limit else text[:limit - 3] + "..."


def subject_with_ability(subject, ability):
    """Add the ability heading to the first subject unless it repeats a name already there."""
    if not ability:
        return subject
    parts = [x for x in subject.split("; ") if x]
    if ability.lower() in (x.lower() for x in parts):
        return subject
    if parts:
        parts[0] = f"{parts[0]} {ability}"
        return "; ".join(parts)
    return ability


SLOT_ORDER = "PQWER"
# An ability heading: "Q - Baleful Strike", "Passive: Soul Siphon", "R".
HEADING_SLOT = re.compile(r"^(Passive|[QWER])(?:\s*[-\u2013:]|$)")
# A slot letter standing alone: "Anivia's Q tooltip", "Bushwhack/Pounce (W)", "Q's tooltip".
LETTER_SLOT = re.compile(r"(?<![\w'’&-])([QWER])(?![\w&-])")
# The passive: "Passive - Mark of the Kindred", "the Passive Shield", "Nocturne's passive tooltip".
# A lower-case "passive" elsewhere ("Nilah's Q passive shield") is a part of another ability.
PASSIVE_SLOT = re.compile(r"\bPassive\b|['’]s?\s+passive\b")


def champion_subjects(subject, names):
    """Champion names at the start of each ';'-separated part of the subject column."""
    champs = sorted({n for n, area in names.values() if area == "champion"}, key=len, reverse=True)
    out = []
    for part in (x for x in subject.split("; ") if x):
        for name in champs:
            if part == name or part.startswith(name + " "):
                if name not in out:
                    out.append(name)
                break
    return out


def champion_aliases(champ_names, names):
    """{champion name: the lower-case names it is written as in notes} ("Jarvan" for Jarvan IV)."""
    out = {c: {c.lower()} for c in champ_names}
    for alias, (name, area) in names.items():
        if area == "champion" and name in out:
            out[name].add(alias)
    return out


def slot_owners(text, end, aliases):
    """Champions whose name ends at position end of text.

    "Mel's W" belongs to Mel. A list that shares one possessive, "Zac, Gangplank, and
    Nocturne's passive", belongs to every champion in it. Returns [] when no champion name
    comes directly before end.
    """
    low = text[:end].lower()
    owners, joiner = [], ""
    while True:
        best = None
        for champ, forms in aliases.items():
            for form in forms:
                m = re.search(r"(?<![\w'])" + re.escape(form) + joiner + "$", low)
                if m and (best is None or m.start() < best[1]):  # the longest name wins
                    best = (champ, m.start())
        if best is None:
            return owners
        if best[0] not in owners:
            owners.append(best[0])
        low = low[:best[1]]
        joiner = r"(?:,\s*and|,|\s+and|\s*&)\s+"


def parse_slots(text, ability_heading, champ_names, abilities, aliases=None):
    """Ability slots (P, Q, W, E, R) a line names for each champion, aligned with champ_names.

    Returns one entry per champion: its slots in P, Q, W, E, R order joined by '+', or ""
    when none is named for it. The ability heading above the line decides the first
    champion's slot (the heading belongs to that champion's block). Otherwise slot letters
    and the word Passive in the line are used, and failing those, the champion's ability
    names from Data Dragon ("Sona's Song of Celerity" is E). An ability name that has sat in
    two slots of that champion gives no slot.

    With one champion, every slot in the line is that champion's. With several, a slot
    counts only when a champion's name comes just before it ("Mel's W", "Zac, Gangplank,
    and Nocturne's passive"); a slot that can't be tied to a champion is left out.
    """
    text = text.replace("’", "'")
    aliases = aliases or {c: {c.lower()} for c in champ_names}
    found = {c: set() for c in champ_names}
    m = HEADING_SLOT.match(ability_heading or "")
    if m and champ_names:
        found[champ_names[0]].add("P" if m.group(1) == "Passive" else m.group(1))
    else:
        tokens = [(t.start(1), t.group(1)) for t in LETTER_SLOT.finditer(text)]
        tokens += [(t.start(), "P") for t in PASSIVE_SLOT.finditer(text)]
        for start, slot in tokens:
            if len(champ_names) == 1:
                found[champ_names[0]].add(slot)
                continue
            before = text[:start].rstrip()  # "Mel's W", "Aphelios' R", "Nocturne's passive"
            before = before[:-2] if before.endswith("'s") else before.rstrip("'")
            for champ in slot_owners(text, len(before), aliases):
                found[champ].add(slot)
        for champ in champ_names:
            if found[champ]:
                continue
            for ability, slots in (abilities or {}).get(champ.lower(), {}).items():
                if (len(ability) >= 4 and len(slots) == 1
                        and re.search(r"(?<![\w'])" + re.escape(ability) + r"(?![\w])", text)):
                    found[champ] |= slots
    return ["+".join(x for x in SLOT_ORDER if x in found[c]) for c in champ_names]


def classify(line, names, champs=None):
    """Return a candidate dict or None. Every signal reads the full line.

    champs, when given, is {"folders": {champion name, lower case: CommunityDragon folder},
    "abilities": the output of load_abilities}, used for the champion_folder and slot columns.
    """
    text = line["text"]
    if len(text) < 12 or not TEXT_HINT.search(text):
        return None
    where = " ".join([line["section"], line["category"], line["subject"]])
    names_text = re.search(r"tool ?tip|description", text, re.I)
    notes = []
    if line.get("quote"):
        if not names_text:
            return None
        notes.append("designer context, not a change line")

    if NOT_GAME_TEXT.search(text):
        # "tooltip" lines that also mention a VFX are still worth a look, the rest are not
        if not names_text:
            return None
        notes.append("mentions non-ability text or visuals")

    mode = MODE.search(where) or MODE.search(text)
    if mode:
        notes.append(f"game mode: {mode.group(0)}")

    is_fix = bool(FIX_SIGNAL.search(text))
    in_bugfix = bool(re.search(r"bug ?fix|bugs", where, re.I))
    is_balance = bool(BALANCE.search(text))

    # subject: structural heading first, else a name found in the text
    subject, area = "", ""
    struct_subj = line["subject"]
    if in_bugfix:
        # bugfix lists put the name in the sentence; sticky headings there are unreliable
        struct_subj = ""
    if struct_subj and not re.search(r"bug|fix|quality|qol|change|update|adjust", struct_subj, re.I):
        subject = struct_subj
        area = (names.get(struct_subj.lower()) or ("", ""))[1]
    found = find_subjects(text, names)
    if found and (not subject or not area):
        if not subject:
            subject = "; ".join(n for n, _ in found)
        area = found[0][1]
    if in_bugfix and not found and line["subject"].lower() in names:
        # the sentence names nobody ("Fixed Q - Baleful Strike's tooltip ..."), so the
        # heading above it is the only lead; trust it only when it is a known name
        subject, area = names[line["subject"].lower()]
    subject = subject_with_ability(subject, line["ability"])

    strong_text = re.search(r"tool ?tip|description|typo|translat|locali[sz]|now correctly (?:display|show|state)"
                            r"|displays? the correct|incorrectly (?:display|show|state|said)"
                            r"|no longer states|debug strings?|outdated information|did not display its", text, re.I)

    improvement = bool(IMPROVEMENT.search(text)) and not BUG_WORDS.search(text)
    cosmetic = (bool(re.search(r"spacing|capitali[sz]|text colou?r|formatting|styling|syntax", text, re.I))
                and not re.search(r"omit|missing|value|duration|damage|stated|did not show|incorrect (?!spacing)",
                                  text, re.I))
    if improvement:
        notes.append("tooltip improvement or clarification, not a stated bug")
    if cosmetic:
        notes.append("formatting only")
    for pattern, reason in NOT_STATIC_TEXT:
        if pattern.search(text):
            notes.append(reason)
    if is_balance:
        notes.append("balance change line")

    # every note so far is a reason the line is not a plain text fix
    confidence = "high" if (strong_text and (is_fix or in_bugfix) and not notes and area) else "borderline"

    if not strong_text:
        notes.append("weak text signal")
    if not is_fix and not in_bugfix:
        notes.append("not phrased as a fix")
    if not area and not mode:
        notes.append("subject not identified")

    if TRANSLATION_HINT.search(text):
        kind = "translation"
    elif re.search(r"magic damage|physical damage|true damage|bonus (?:ad|ap|attack damage|health|armor)|"
                   r"total (?:ad|ap|attack damage)|damage type", text, re.I):
        kind = "wording"
    elif NUMBER_HINT.search(text) and not re.search(r"clarif|describ", text, re.I):
        kind = "typed_number"
    elif WORDING_HINT.search(text):
        kind = "wording"
    else:
        kind = "other"

    champ_names = champion_subjects(subject, names)
    if champ_names and ITEM_TEXT.search(text):
        # "Bloodward's item description ... upgraded by Ornn": the text is the item's
        notes.append("item text mentioning a champion")
        confidence = "borderline"
        champ_names = []
    folders = [(champs or {}).get("folders", {}).get(n.lower(), "") for n in champ_names]
    unmapped = [n for n, f in zip(champ_names, folders) if not f]
    champ_names = [n for n, f in zip(champ_names, folders) if f]
    champion_folder = ";".join(f for f in folders if f)
    slots = parse_slots(text, line["ability"], champ_names, (champs or {}).get("abilities"),
                        champion_aliases(champ_names, names))
    slot = ";".join(slots) if any(slots) else ""

    return {
        "section": " / ".join(x for x in (line["section"], line["category"]) if x),
        "subject": subject,
        "champion_folder": champion_folder,
        "slot": slot,
        "_champions_unmapped": unmapped,
        "quote": quote_for(text, names),
        "kind_guess": kind,
        "confidence": confidence,
        "notes": "; ".join(notes),
        "_area": area,
    }


# ---------------------------------------------------------------- main

MIN_NAMES = 100  # far fewer means Data Dragon failed, not that the game shrank


def coverage_gaps(patches):
    """Per year, patch numbers missing between 1 and the highest one found."""
    seen = {}
    for art in patches:
        year, minor, letter = art["key"]
        # a lettered patch (13.1B) stands in for the next number (13.2 has no page)
        seen.setdefault(year, set()).add(minor + 1 if letter else minor)
    return {y: gaps for y in sorted(seen) if (gaps := sorted(set(range(1, max(seen[y]) + 1)) - seen[y]))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    now = datetime.date.today().year
    ap.add_argument("--from-year", type=int, default=2020,
                    help="oldest year to include (default 2020; 2019 pages exist only in part)")
    ap.add_argument("--to-year", type=int, default=now, help=f"newest year to include (default {now})")
    ap.add_argument("--offline", action="store_true", help="use cached pages only, no network")
    ap.add_argument("--recheck-missing", action="store_true",
                    help="re-request URLs that returned 404 before (e.g. a new patch is out)")
    ap.add_argument("--out", type=Path, default=OUT, help="CSV to write")
    args = ap.parse_args()

    patches, unparsed = discover(args.from_year, args.to_year, args.offline, args.recheck_missing)
    names = load_names(args.offline)
    if len(names) < MIN_NAMES:
        # without names nothing can reach "high", and the CSV would look valid
        sys.exit(f"error: only {len(names)} names loaded from Data Dragon (need {MIN_NAMES}); "
                 "run once without --offline to download them")
    print(f"patches covered: {len(patches)} "
          f"({patches[-1]['patch_name']} to {patches[0]['patch_name']})" if patches else "no patches found")
    for year, gaps in coverage_gaps(patches).items():
        print(f"  {year}: no page for patch number {', '.join(map(str, gaps))}")
    if unparsed:
        print(f"warning: {len(unparsed)} page(s) loaded but could not be read (new layout?): "
              f"{', '.join(unparsed)}", file=sys.stderr)

    try:
        folders = cdragon.cdragon_folders(args.offline)
        champs = {"folders": cdragon.champion_folders(args.offline), "abilities": load_abilities(args.offline)}
    except RuntimeError as e:
        sys.exit(f"error: {e}")

    rows = []
    unmapped_patches = {}
    for art in patches:
        shipped, prefix, problem = cdragon.map_notes_name(art["patch_name"], folders)
        if problem:
            unmapped_patches[art["patch_name"]] = problem
        seen = set()
        for line in extract_lines(art["body"]):
            c = classify(line, names, champs)
            if not c or c["quote"] in seen:
                continue
            seen.add(c["quote"])
            c["patch_name"] = art["patch_name"]
            c["cdragon_patch"] = shipped or ""
            c["prefix_patch"] = prefix or ""
            c["notes_url"] = art["url"]
            c["_year"] = art["key"][0]
            rows.append(c)
    for name, problem in unmapped_patches.items():
        print(f"warning: patch {name} not mapped to CommunityDragon: {problem}", file=sys.stderr)
    no_folder = sorted({n for r in rows for n in r["_champions_unmapped"]})
    if no_folder:
        print(f"warning: no CommunityDragon folder for champion(s): {', '.join(no_folder)}", file=sys.stderr)

    cols = ["patch_name", "cdragon_patch", "prefix_patch", "notes_url", "section", "subject",
            "champion_folder", "slot", "quote", "kind_guess", "confidence", "notes"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    def count(key):
        out = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items()))

    high = [r for r in rows if r["confidence"] == "high"]
    print(f"candidates: {len(rows)}  high: {len(high)}  borderline: {len(rows) - len(high)}")
    print("per year (all):", count("_year"))
    print("per year (high):", {y: sum(1 for r in high if r["_year"] == y) for y in sorted({r['_year'] for r in rows})})
    print("per kind (all):", count("kind_guess"))
    champ_rows = [r for r in rows if r["champion_folder"]]
    print(f"champion rows: {len(champ_rows)} with a folder, {sum(1 for r in champ_rows if r['slot'])} also with a slot "
          f"(high: {sum(1 for r in champ_rows if r['confidence'] == 'high')} and "
          f"{sum(1 for r in champ_rows if r['confidence'] == 'high' and r['slot'])})")
    print("per kind (high):", {k: sum(1 for r in high if r["kind_guess"] == k) for k in sorted({r['kind_guess'] for r in rows})})
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")


if __name__ == "__main__":
    main()
