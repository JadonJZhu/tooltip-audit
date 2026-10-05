#!/usr/bin/env python3
"""Download per-patch League of Legends game data from CommunityDragon.

For each live patch this saves, under <out>/<patch>/ with the remote path kept:
  - content-metadata.json, which names the CommunityDragon build the files came from
  - the string table (tooltip text) for each requested locale
  - champion-summary.json (the champion list)
  - every playable champion's game data, game/data/characters/<id>/<id>.bin.json, and for
    patches before 11.1 also the binary game/data/characters/<id>/<id>.bin, because the JSON
    exports of those patches leave out the class names that the resolver needs
  - manifest.json: build, files, sizes, failures, timing

CommunityDragon sometimes rewrites a patch folder with a later build. So every run first
reads the patch's content-metadata.json from the server and compares its version with
the one saved at the first download. If they match, files already on disk are checked
and reused. If they differ, the run stops for that patch, because reusing the old files
would mix two builds. --refresh deletes that patch's folder and downloads it again.

PBE is never fetched.

Examples (run from the project root):
  python3 scripts/fetch_cdragon.py --list
  python3 scripts/fetch_cdragon.py --patches latest 15.1
  python3 scripts/fetch_cdragon.py --since 15.1
  python3 scripts/fetch_cdragon.py --patches 16.19 --locales all
  python3 scripts/fetch_cdragon.py --patches 16.19 --refresh
"""

import argparse
import gzip
import http.client
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://raw.communitydragon.org"
USER_AGENT = "tooltip-audit/0.1 (research script; python urllib)"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "data" / "raw"

PATCH_RE = re.compile(r"^\d+\.\d+$")
LOCALE_RE = re.compile(r"^[a-z]{2}_[a-z]{2}$")
CONTENT_METADATA = "content-metadata.json"
CHAMPION_SUMMARY = "plugins/rcp-be-lol-game-data/global/default/v1/champion-summary.json"

# Where the string table lives. Boundaries checked against the CommunityDragon
# listings on 2026-10-05 (each side of every boundary was listed):
#   14.15 and later : game/<locale>/data/menu/en_us/lol.stringtable.json
#   14.4 to 14.14   : game/<locale>/data/menu/en_us/main.stringtable.json
#   12.23 to 14.3   : game/data/menu/main_<locale>.stringtable.json
#   11.1 to 12.22   : game/data/menu/fontconfig_<locale>.txt.json
#   10.25 and older : game/data/menu/fontconfig_<locale>.txt only
# The inner "en_us" folder is the same for every locale; the outer folder sets the language.
# The four .json forms share one shape, {"entries": {key: text}}. In the fontconfig .json,
# about a third of the keys are hashes like "{0000097eae}" because CommunityDragon could not
# recover their names; on 12.22 it holds the same 78,740 strings as the binary .txt.
# The bare .txt is Riot's binary string table ("RST" header, every key hashed). It is saved
# as is; reading it needs a decoder for that format.
STRINGTABLE_LAYOUTS = [
    ("lol", "game/{loc}/data/menu/en_us/lol.stringtable.json"),
    ("main", "game/{loc}/data/menu/en_us/main.stringtable.json"),
    ("main_locale", "game/data/menu/main_{loc}.stringtable.json"),
    ("fontconfig", "game/data/menu/fontconfig_{loc}.txt.json"),
    ("fontconfig", "game/data/menu/fontconfig_{loc}.txt"),
]

# First patch of each layout above, newest first, as indexes into STRINGTABLE_LAYOUTS.
LAYOUT_STARTS = [((14, 15), 0), ((14, 4), 1), ((12, 23), 2), ((11, 1), 3), ((0, 0), 4)]

# Real champion ids are below 1000 so far. The summary also lists id -1 ("None") and,
# from 2026, mode-specific variants with ids from 60001 (aliases like "Jade_Ahri").
MAX_CHAMPION_ID = 10000

# Patches before this one also get each champion's binary .bin saved.
BIN_BEFORE = (11, 1)

# Facts about the first download of a build. A later run with the same build keeps them,
# but only when they describe a complete first download (see first_download_is_complete).
FIRST_DOWNLOAD_KEYS = ("fetched_at", "seconds", "downloaded_bytes", "http_requests")

# A champion's game data file, e.g. game/data/characters/ahri/ahri.bin.json.
CHAMPION_BIN_RE = re.compile(r"^game/data/characters/([^/]+)/\1\.bin(\.json)?$")


class BuildMismatch(Exception):
    """The server now holds a different build than the one saved on disk."""


class Fetcher:
    """HTTP GET with gzip, retries with backoff, and a pause between requests."""

    def __init__(self, delay=0.2, retries=4, timeout=60):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.requests = 0
        self._last = 0.0

    def fetch(self, url):
        """Return (body bytes, Last-Modified header), or (None, None) on 404.

        Raises after repeated failures. A cut-off transfer (gzip EOFError or
        http.client.IncompleteRead) is retried like a network error.
        """
        last_err = None
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body, resp.headers.get("Last-Modified")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None, None
                if e.code not in (429, 500, 502, 503, 504):
                    raise
                last_err = e
            except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                    ConnectionError, EOFError, OSError) as e:
                last_err = e
            if attempt < self.retries:
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"giving up on {url}: {last_err}")

    def get(self, url):
        return self.fetch(url)[0]

    def get_json(self, url):
        body = self.get(url)
        return None if body is None else json.loads(body)

    def listing(self, path):
        """Directory listing as {name: entry}, or None if the folder does not exist."""
        path = path.strip("/")
        data = self.get_json(f"{BASE}/json/{path}/" if path else f"{BASE}/json/")
        return None if data is None else {e["name"]: e for e in data}


def patch_key(p):
    major, minor = p.split(".")
    return (int(major), int(minor))


def layout_order(patch):
    """STRINGTABLE_LAYOUTS reordered so the layout expected for this patch comes first.

    The rest follow in their usual order, so a layout that turns up outside its known
    range is still found.
    """
    key = patch_key(patch)
    first = next(i for start, i in LAYOUT_STARTS if key >= start)
    return [STRINGTABLE_LAYOUTS[first]] + [x for i, x in enumerate(STRINGTABLE_LAYOUTS) if i != first]


def entry_hash(name):
    """The key CommunityDragon writes for an entry whose name it could not recover:
    the 32-bit FNV-1a hash of the lowercased name, as "{xxxxxxxx}"."""
    h = 0x811C9DC5
    for byte in name.lower().encode("utf-8"):
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return "{%08x}" % h


def check_body(path, body, expected_size=None):
    """Return None if the body looks like the file it claims to be, else the reason."""
    if not body:
        return "empty body"
    if expected_size is not None and len(body) != expected_size:
        return f"size {len(body)} differs from listed size {expected_size}"
    champ = CHAMPION_BIN_RE.match(path)
    if champ and not champ.group(2):
        # Riot's property bin format starts with "PROP", or "PTCH" for a patch bin.
        if not body.startswith((b"PROP", b"PTCH")):
            return "binary .bin does not start with 'PROP' or 'PTCH'"
        return None
    if path.endswith(".json"):
        try:
            data = json.loads(body)
        except ValueError as e:
            return f"not valid JSON: {e}"
        if "stringtable" in path or path.endswith(".txt.json"):
            if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
                return "string table has no 'entries' object"
        elif path.endswith("champion-summary.json"):
            if not isinstance(data, list):
                return "champion list is not a JSON list"
        elif path == CONTENT_METADATA:
            if not isinstance(data, dict) or not data.get("version"):
                return "content-metadata.json has no version"
        elif not isinstance(data, dict):
            return "expected a JSON object"
        elif champ:
            # Every champion export from 10.1 to 16.19 has this entry. The case of the name
            # can differ from the folder name, and where CommunityDragon could not recover
            # the name (Senna, Aphelios and Sett in 10.1) the key is its hash instead.
            # Checked on 2026-10-05 for every champion in 10.1, 15.1 and 16.19.
            want = f"characters/{champ.group(1)}/characterrecords/root"
            if entry_hash(want) not in data and not any(k.lower() == want for k in data):
                return f"champion data has no Characters/{champ.group(1)}/CharacterRecords/Root entry"
    elif path.endswith(".txt") and not body.startswith(b"RST"):
        return "binary string table does not start with 'RST'"
    return None


def stored_build(patch_dir, old_manifest):
    """The build version recorded for the files on disk, or None if none is recorded."""
    meta = patch_dir / CONTENT_METADATA
    if meta.exists():
        try:
            return json.loads(meta.read_text(encoding="utf-8")).get("version")
        except ValueError:
            return None
    # Manifests written before content-metadata.json was saved carry the version here.
    return (old_manifest or {}).get("cdragon_version")


def has_cached_files(patch_dir):
    if not patch_dir.exists():
        return False
    return any(p.is_file() and p.name != "manifest.json" for p in patch_dir.rglob("*"))


def plan_run(remote_version, stored_version, has_cache, refresh):
    """Decide how to treat the files on disk: 'first', 'recheck' or 'refresh'.

    Raises BuildMismatch when reuse would mix builds and --refresh was not given.
    """
    if refresh and has_cache:
        return "refresh"
    if not has_cache:
        return "first"
    if stored_version is None:
        raise BuildMismatch(
            "files are on disk but no build version is recorded for them, so they can't be "
            "checked against the server. Re-run with --refresh to download the patch again."
        )
    if stored_version != remote_version:
        raise BuildMismatch(
            f"the files on disk are build {stored_version}, but CommunityDragon now serves "
            f"build {remote_version}. Reusing them would mix two builds. Re-run with "
            f"--refresh to delete this patch's folder and download it again."
        )
    return "recheck"


def first_download_is_complete(old):
    """True if the old manifest's first-download facts come from one complete run.

    A complete run started from an empty folder, ran to the end and had no failures.
    Manifests written before the first_download_complete field existed count as complete
    only if they downloaded something, reused nothing and list no failures.
    """
    if not old:
        return False
    if "first_download_complete" in old:
        return bool(old["first_download_complete"])
    if old.get("last_run") and old["last_run"].get("mode") not in ("first", "refresh"):
        return False
    if old.get("failures"):
        return False
    files = old.get("files", [])
    return bool(old.get("downloaded_bytes")) and not any(f.get("status") == "cached" for f in files)


def merge_manifest(old, run, mode):
    """Combine this run's results with the previous manifest of the same build.

    The first-download facts (fetched_at, seconds, downloaded_bytes, http_requests) are
    filled in only when they describe one complete download of the build; otherwise they
    are null and first_download_complete is false. Every run's own numbers are in last_run.
    A 'first' or 'refresh' run is the first download of its build. It is complete only if
    it had no failures, because a later run that fills the gaps would make its numbers
    cover only part of the files.
    A 'recheck' run keeps each file's first-download entry and records itself under
    last_checked and last_run. It keeps the old first-download facts only if the old
    manifest records a complete first download. Otherwise (an incomplete first run, a
    resumed interrupted download, or an old manifest written by a run that reused files)
    those facts stay unknown.
    A file that failed in this run loses its old entry, since it may no longer be on disk.
    """
    run_facts = {k: run[k] for k in FIRST_DOWNLOAD_KEYS}
    failed = {x["path"] for x in run["failures"]}
    files = {}
    if mode == "recheck" and old:
        for f in old.get("files", []):
            if f["path"] in failed:
                continue
            entry = {k: v for k, v in f.items() if k != "status"}
            files[entry["path"]] = entry
    for f in run["files"]:
        if f["status"] == "downloaded" or f["path"] not in files:
            files[f["path"]] = {k: v for k, v in f.items() if k != "status"}
    layouts, st_paths = {}, {}
    if mode == "recheck" and old:
        layouts.update(old.get("stringtable_layout", {}))
        st_paths.update(old.get("stringtable_path", {}))
    layouts.update({k: v for k, v in run["stringtable_layout"].items() if v})
    st_paths.update({k: v for k, v in run["stringtable_path"].items() if v})
    if mode == "recheck":
        complete = first_download_is_complete(old)
        source = old
    else:
        complete = not run["failures"]
        source = run_facts
    first = {k: source.get(k) if complete else None for k in FIRST_DOWNLOAD_KEYS}
    file_list = sorted(files.values(), key=lambda x: x["path"])
    return {
        "patch": run["patch"],
        "cdragon_version": run["cdragon_version"],
        **first,
        "first_download_complete": complete,
        "last_checked": run["fetched_at"],
        "last_run": {"mode": mode, **{k: run_facts[k] for k in ("seconds", "downloaded_bytes", "http_requests")}},
        "stringtable_layout": layouts,
        "stringtable_path": st_paths,
        "champions": run["champions"],
        "file_count": len(file_list),
        "total_bytes": sum(x["bytes"] for x in file_list),
        "failures": run["failures"],
        "files": file_list,
    }


def discover_patches(f):
    root = f.listing("")
    return sorted((n for n in root if PATCH_RE.match(n)), key=patch_key)


def resolve_latest(f):
    meta = f.get_json(f"{BASE}/latest/{CONTENT_METADATA}")
    version = meta["version"]  # e.g. "16.19.8230722+branch.releases-16-19.content.release"
    return ".".join(version.split(".")[:2])


MENU_LOCALE_RE = re.compile(r"^(?:main|fontconfig)_([a-z]{2}_[a-z]{2})\.(?:stringtable\.json|txt(?:\.json)?)$")


def locales_from_listings(game, menu):
    """Locales found in a patch's game/ and game/data/menu/ listings (name -> entry)."""
    found = {n for n, e in (game or {}).items() if LOCALE_RE.match(n) and e.get("type") == "directory"}
    for n in menu or {}:
        m = MENU_LOCALE_RE.match(n)
        if m:
            found.add(m.group(1))
    return sorted(found)


def discover_locales(f, patch):
    return locales_from_listings(f.listing(f"{patch}/game"), f.listing(f"{patch}/game/data/menu"))


class PatchRun:
    def __init__(self, f, patch, out_root, refresh=False):
        self.f = f
        self.patch = patch
        self.dir = out_root / patch
        self.refresh = refresh
        self.use_cache = True
        self.old_files = {}
        self.listings = {}
        self.files = []
        self.failures = []

    def listing(self, path):
        if path not in self.listings:
            self.listings[path] = self.f.listing(f"{self.patch}/{path}")
        return self.listings[path]

    def save(self, remote_path, expected_size=None):
        """Download one file unless a good copy is on disk. Returns True if it exists after."""
        dest = self.dir / remote_path
        bad_cache = None
        if self.use_cache and dest.exists():
            body = dest.read_bytes()
            known = self.old_files.get(remote_path, {}).get("bytes", expected_size)
            bad_cache = check_body(remote_path, body, known)
            if bad_cache is None:
                self.files.append({"path": remote_path, "bytes": len(body), "status": "cached"})
                return True
            # Remove the bad copy first, so a failed download can't leave it in place.
            dest.unlink()
        try:
            body, last_modified = self.f.fetch(f"{BASE}/{self.patch}/{remote_path}")
        except Exception as e:  # noqa: BLE001 (record and keep going)
            self.failures.append({"path": remote_path, "error": str(e)})
            return False
        if body is None:
            if bad_cache:
                self.failures.append({"path": remote_path,
                                      "error": f"copy on disk was bad ({bad_cache}), removed; server returns 404"})
            return False
        problem = check_body(remote_path, body, expected_size)
        if problem:
            self.failures.append({"path": remote_path, "error": f"bad download, not saved: {problem}"})
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(body)
        tmp.replace(dest)
        self.files.append({
            "path": remote_path,
            "bytes": len(body),
            "last_modified": last_modified,
            "downloaded_at": now_iso(),
            "status": "downloaded",
        })
        return True

    def stringtable(self, locale):
        """Save the locale's string table. Returns (layout, path) or (None, None)."""
        tried = []
        for layout, template in layout_order(self.patch):
            path = template.format(loc=locale)
            folder, name = path.rsplit("/", 1)
            tried.append(path)
            entry = (self.listing(folder) or {}).get(name)
            if entry is None:
                continue
            if self.save(path, entry.get("size")):
                return layout, path
            if any(x["path"] == path for x in self.failures):
                return None, None
        self.failures.append({"path": f"string table for {locale}", "error": "not found at " + ", ".join(tried)})
        return None, None

    def champions(self):
        if not self.save(CHAMPION_SUMMARY):
            if not any(x["path"] == CHAMPION_SUMMARY for x in self.failures):
                self.failures.append({"path": CHAMPION_SUMMARY, "error": "champion list not found"})
            return {}
        summary = json.loads((self.dir / CHAMPION_SUMMARY).read_text(encoding="utf-8"))
        playable = [c for c in summary if 0 < c["id"] < MAX_CHAMPION_ID]
        excluded = sorted(c["alias"] for c in summary if not 0 < c["id"] < MAX_CHAMPION_ID)

        # No size check for champion files: the sizes are only in each champion folder's
        # listing, which would add one request per champion (about 170 per patch). A cut-off
        # transfer is already caught by http.client (IncompleteRead against Content-Length)
        # or by gzip, files are written through a .part rename, and check_body requires the
        # champion's CharacterRecords/Root entry (or the binary's header).
        folders = self.listing("game/data/characters") or {}
        with_bin = patch_key(self.patch) < BIN_BEFORE
        unmapped, saved, bin_saved = [], 0, 0
        for c in playable:
            folder = c["alias"].lower()
            if folder not in folders:
                unmapped.append(c["alias"])
                continue
            base = f"game/data/characters/{folder}/{folder}.bin"
            for path in [base + ".json"] + ([base] if with_bin else []):
                if self.save(path):
                    if path == base:
                        bin_saved += 1
                    else:
                        saved += 1
                elif not any(x["path"] == path for x in self.failures):
                    self.failures.append({"path": path, "error": "404"})
        for alias in unmapped:
            self.failures.append({"path": f"champion {alias}", "error": "no matching character folder"})
        result = {
            "playable": len(playable),
            "saved": saved,
            "unmapped": unmapped,
            "excluded_from_summary": excluded,
        }
        if with_bin:
            result["bin_saved"] = bin_saved
        return result

    def run(self, locales):
        start = time.monotonic()
        requests_before = self.f.requests
        meta_body, _ = self.f.fetch(f"{BASE}/{self.patch}/{CONTENT_METADATA}")
        problem = "not found" if meta_body is None else check_body(CONTENT_METADATA, meta_body)
        if problem:
            raise BuildMismatch(f"can't read the server's {CONTENT_METADATA}: {problem}")
        remote_version = json.loads(meta_body)["version"]

        manifest_path = self.dir / "manifest.json"
        old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
        mode = plan_run(remote_version, stored_build(self.dir, old), has_cached_files(self.dir), self.refresh)

        if locales == ["all"]:
            locales = discover_locales(self.f, self.patch)
        if mode == "refresh":
            # Keep every locale the old download had, then start the folder from nothing.
            locales = sorted(set(locales) | set((old or {}).get("stringtable_layout", {})))
            shutil.rmtree(self.dir)
            old = None
        self.old_files = {x["path"]: x for x in (old or {}).get("files", [])}

        # The build file goes in first: if the run stops partway, the files already saved
        # are still labeled with the build they came from.
        self.dir.mkdir(parents=True, exist_ok=True)
        meta_dest = self.dir / CONTENT_METADATA
        if not meta_dest.exists():
            meta_dest.write_bytes(meta_body)

        layouts, st_paths = {}, {}
        for loc in locales:
            layouts[loc], st_paths[loc] = self.stringtable(loc)
        champs = self.champions()
        if old:
            # Keep only old entries for files still on disk.
            old = {**old, "files": [x for x in old.get("files", []) if (self.dir / x["path"]).exists()]}
        run = {
            "patch": self.patch,
            "cdragon_version": remote_version,
            "fetched_at": now_iso(),
            "stringtable_layout": layouts,
            "stringtable_path": st_paths,
            "champions": champs,
            "downloaded_bytes": sum(x["bytes"] for x in self.files if x["status"] == "downloaded"),
            "http_requests": self.f.requests - requests_before,
            "seconds": round(time.monotonic() - start, 1),
            "failures": self.failures,
            "files": self.files,
        }
        manifest = merge_manifest(old, run, mode)
        tmp = manifest_path.with_name("manifest.json.part")
        tmp.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        tmp.replace(manifest_path)
        return manifest


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patches", nargs="+", metavar="P", help="patches to fetch, e.g. 15.1 16.19 latest")
    ap.add_argument("--since", metavar="P", help="fetch every live patch from P to the newest, e.g. 15.1")
    ap.add_argument("--locales", default="en_us",
                    help="comma-separated locales (e.g. en_us,fr_fr,ja_jp) or 'all'. Default: en_us")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output root (default: {DEFAULT_OUT})")
    ap.add_argument("--refresh", action="store_true",
                    help="delete each requested patch's folder and download it again (needed when "
                         "CommunityDragon now serves a different build than the one on disk)")
    ap.add_argument("--delay", type=float, default=0.2, help="seconds between requests (default 0.2)")
    ap.add_argument("--list", action="store_true", help="list available live patches and locales, then exit")
    args = ap.parse_args()

    f = Fetcher(delay=args.delay)
    available = discover_patches(f)

    if args.list:
        latest = resolve_latest(f)
        print(f"{len(available)} live patches: {available[0]} .. {available[-1]} (latest = {latest})")
        print(" ".join(available))
        print("locales in latest:", ",".join(discover_locales(f, latest)))
        return 0

    if not args.patches and not args.since:
        ap.error("give --patches or --since (or --list)")

    wanted = []
    for p in args.patches or []:
        if p.lower() == "pbe":
            ap.error("pbe is unreleased content and is never fetched")
        wanted.append(resolve_latest(f) if p.lower() == "latest" else p)
    if args.since:
        if not PATCH_RE.match(args.since):
            ap.error(f"--since needs a version like 15.1, got {args.since}")
        wanted += [p for p in available if patch_key(p) >= patch_key(args.since)]
    wanted = sorted(set(wanted), key=patch_key)
    missing = [p for p in wanted if p not in available]
    if missing:
        ap.error(f"not on CommunityDragon: {', '.join(missing)}")

    locales = ["all"] if args.locales == "all" else [x.strip() for x in args.locales.split(",") if x.strip()]
    bad = [x for x in locales if x != "all" and not LOCALE_RE.match(x)]
    if bad:
        ap.error(f"bad locale(s): {', '.join(bad)}")

    exit_code = 0
    for patch in wanted:
        try:
            m = PatchRun(f, patch, args.out, refresh=args.refresh).run(locales)
        except BuildMismatch as e:
            print(f"{patch}: STOPPED, {e}")
            exit_code = 1
            continue
        except Exception as e:  # noqa: BLE001 (one patch's outage must not stop the others)
            print(f"{patch}: FAILED, {e}")
            exit_code = 1
            continue
        c, r = m["champions"], m["last_run"]
        bins = f" (binaries {c['bin_saved']})" if "bin_saved" in c else ""
        print(f"{patch}: build {m['cdragon_version']} ({r['mode']}), {m['file_count']} files, "
              f"{m['total_bytes'] / 1e6:.1f} MB ({r['downloaded_bytes'] / 1e6:.1f} MB new), "
              f"champions {c.get('saved', 0)}/{c.get('playable', 0)}{bins}, "
              f"string tables {m['stringtable_layout']}, {len(m['failures'])} failures, {r['seconds']}s")
        for fail in m["failures"]:
            print(f"  FAILED {fail['path']}: {fail['error']}")
        if m["failures"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
