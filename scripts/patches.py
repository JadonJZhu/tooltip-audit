#!/usr/bin/env python3
"""Map Riot's patch notes names to CommunityDragon patch folders, and champion names to folders.

Riot's patch notes and CommunityDragon number the same patches differently:

  notes name                         game version (CommunityDragon folder)
  10.1 to 14.24                      the same number
  25.S1.1, 25.S1.2, 2025.S1.3        15.1, 15.2, 15.3
  25.04 to 25.24                     15.4 to 15.24 (leading zero dropped)
  26.1 and on                        16.1 and on

For each notes page this gives two folders:
  cdragon_patch  the first folder whose game files include the changes on that page
  prefix_patch   the folder just before it in CommunityDragon's list, so the last one
                 without those changes

Both come from CommunityDragon's live patch list, so patch numbers it skips come out right:
there is no 10.17, 12.24 or 13.2 folder, the folder before 11.1 is 10.25 and the folder
before 13.1 is 12.23.

Two notes pages describe a release that got no game version of its own: 'Patch 10.17' (page
slug patch-10-16b-notes, 2020-08-19) shipped as a 10.16 build, and '13.1B' (2023-01-24) as a
13.1 build. CommunityDragon's folders hold a build from around release day: the 10.16 folder
holds build 10.16.3309186 (files dated 2020-08-05) and the 13.1 folder build 13.1.4893737
(dated 2023-01-14), both checked on 2026-10-05. So the changes on those two pages first appear
in the next folder, 10.18 and 13.3. The rule in code: a lettered name (13.1B, 10.16B), or a
number with no folder of its own (10.17), maps to the next folder after that number.

Lines in a page's 'Mid-Patch Updates' section shipped during that patch, in a later build.
Their cdragon_patch is still that patch, and its folder may or may not hold the fix; their
prefix_patch is unaffected, so comparing against it is safe either way.

Run from the project root to print the mapping for every notes name in a CSV:
  python3 scripts/patches.py                      # answer_key/candidates.csv
  python3 scripts/patches.py other.csv --offline  # use the saved patch list
"""

import argparse
import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cdragon"
PATCH_LIST_CACHE = CACHE / "patches.json"
SUMMARY_CACHE = CACHE / "champion-summary.json"
BASE = "https://raw.communitydragon.org"
SUMMARY_URL = f"{BASE}/latest/plugins/rcp-be-lol-game-data/global/default/v1/champion-summary.json"
USER_AGENT = "tooltip-audit/0.1 (research script; python urllib)"

FOLDER_RE = re.compile(r"^\d+\.\d+$")
# 10.25, 13.1B, 25.S1.2, 2025.S1.3, 25.04, 26.19 (case of the letter and of 'S1' ignored)
NOTES_NAME_RE = re.compile(r"^(\d{1,4})\.(?:S1\.)?(\d+)([A-Za-z])?$", re.I)
# Real champion ids are below 1000 so far; the summary also lists id -1 ('None') and, from
# 2026, mode variants with ids from 60001 (aliases like 'Jade_Ahri'). fetch_cdragon.py uses
# the same bound.
MAX_CHAMPION_ID = 10000


def folder_key(folder):
    major, minor = folder.split(".")
    return int(major), int(minor)


def parse_notes_name(name):
    """(game version 'major.minor', letter) for a notes name, or None if it is not one.

    The year part of 2025 and later names (25, 2025, 26) becomes 15 and 16, the game's own
    major version. Leading zeros are dropped.
    """
    m = NOTES_NAME_RE.match(name.strip())
    if not m:
        return None
    major = int(m.group(1))
    if major >= 2000:
        major %= 100
    if major >= 25:
        major -= 10
    return f"{major}.{int(m.group(2))}", (m.group(3) or "").upper()


def map_notes_name(name, folders):
    """(cdragon_patch, prefix_patch, problem) for a notes name, given CommunityDragon's folders.

    problem is None when both folders were found, else the reason one is missing (the other
    may still be set).
    """
    parsed = parse_notes_name(name)
    if parsed is None:
        return None, None, f"'{name}' is not a patch notes name this rule knows"
    version, letter = parsed
    ordered = sorted((f for f in folders if FOLDER_RE.match(f)), key=folder_key)
    if not ordered:
        return None, None, "the CommunityDragon patch list is empty"
    key = folder_key(version)
    if letter or version not in ordered:
        later = [f for f in ordered if folder_key(f) > key]
    else:
        later = [f for f in ordered if folder_key(f) >= key]
    if not later:
        return None, ordered[-1], (
            f"CommunityDragon has no folder for {version}{letter} or later yet (newest is {ordered[-1]})")
    shipped = later[0]
    i = ordered.index(shipped)
    if i == 0:
        return shipped, None, f"{shipped} is the oldest folder on CommunityDragon"
    return shipped, ordered[i - 1], None


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _cached_json(url, cache, offline):
    """JSON from url, saved to cache; offline (or when the download fails) the saved copy."""
    if not offline:
        try:
            body = _get(url)
            data = json.loads(body)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(body)
            return data
        except (OSError, ValueError) as e:
            if not cache.exists():
                raise RuntimeError(f"can't read {url} and no saved copy at {cache}: {e}") from e
            print(f"warning: {url} failed ({e}); using the copy saved at {cache}", file=sys.stderr)
    if not cache.exists():
        raise RuntimeError(f"no saved copy at {cache}; run once without --offline")
    return json.loads(cache.read_text(encoding="utf-8"))


def cdragon_folders(offline=False):
    """CommunityDragon's live patch folders (10.1, 10.2, ...), oldest first. PBE is left out."""
    listing = _cached_json(f"{BASE}/json/", PATCH_LIST_CACHE, offline)
    return sorted((e["name"] for e in listing if FOLDER_RE.match(e.get("name", ""))), key=folder_key)


def champion_folders(offline=False):
    """{champion display name, lower case: CommunityDragon folder} from the latest champion-summary.json.

    The folder is the summary's alias in lower case: Wukong is 'monkeyking', Nunu & Willump
    'nunu', Renata Glasc 'renata'. Mode variants (Jade_ aliases) and the 'None' entry are left out.
    """
    summary = _cached_json(SUMMARY_URL, SUMMARY_CACHE, offline)
    return {c["name"].lower(): c["alias"].lower() for c in summary if 0 < c["id"] < MAX_CHAMPION_ID}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", type=Path, default=ROOT / "answer_key" / "candidates.csv",
                    help="CSV with a patch_name column (default answer_key/candidates.csv)")
    ap.add_argument("--offline", action="store_true",
                    help="use the patch list saved under data/cdragon/, no network")
    args = ap.parse_args()
    try:
        folders = cdragon_folders(args.offline)
    except RuntimeError as e:
        sys.exit(f"error: {e}")
    with open(args.csv, encoding="utf-8") as f:
        names = {r["patch_name"] for r in csv.DictReader(f)}
    names = sorted(names, key=lambda n: folder_key(parse_notes_name(n)[0]) if parse_notes_name(n) else (0, 0))
    bad = 0
    for n in names:
        shipped, prefix, problem = map_notes_name(n, folders)
        print(f"{n:>10}  ->  {shipped or '-':>6}  prefix {prefix or '-':>6}" + (f"  ({problem})" if problem else ""))
        bad += problem is not None
    print(f"{len(names)} names, {bad} not fully mapped; {len(folders)} CommunityDragon folders "
          f"({folders[0]} to {folders[-1]})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
