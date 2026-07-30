"""
core/plugin_store.py – the plugin store: read a list of GitHub URLs, pull
each plugin's metadata, download and install it, and spot updates.

The catalogue is a plain list of GitHub links in ``config/plugins.json``
next to the app, so adding a plugin to the store means pasting one URL::

    {
      "sources": [
        "https://github.com/yakuda-stack/Dream-Chatbox-Plugins/tree/main/plugins/world_stats"
      ]
    }

Everything else – name, version, author, description and the preview
image – is read from the plugin's own ``plugin.json``, the same file the
author already maintains. Two extra keys are used by the store only:

    "image":   "logo.png"           file in the plugin folder, or a URL
    "summary": "one-line teaser"    falls back to "description"

If ``image`` is missing or points at a file that isn't there, a handful of
conventional names are tried before giving up, so a plugin folder with a
``logo.png`` in it just works.

Hitting Refresh in the store always pulls the current catalogue from
``self_url`` on GitHub and caches it in ``<config>/plugins.json``. No
version number has to be bumped for that – whatever is on GitHub wins.

Writing into the config folder rather than back into the project folder
is what makes this work everywhere: inside an AppImage the project
folder is a read-only squashfs mount, an AUR install has it root-owned
under /usr, and a git checkout would end up dirty and break the next
``git pull --ff-only``. The config folder is writable in all three cases,
so AppImage users get new plugins exactly like everyone else.

``version`` is optional and only decides one thing: if a later app
version ships a catalogue with a strictly higher version than the cached
one, the shipped file wins and the stale cache is dropped. Ties go to
the cache, so an unversioned catalogue simply always uses the download.

Anything the user adds to ``<config>/plugins_sources.json`` is merged in,
so an update can't wipe their own entries.

No GitHub API calls: that endpoint allows 60 unauthenticated requests per
hour per IP, which a store view would burn through in one refresh. We use
raw.githubusercontent.com for manifests and codeload for downloads, both
of which are plain file fetches.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from core.constants import (
    CONFIG_DIR, GITHUB_REPO, STORE_SOURCES_FILE, VERSION)

RAW_HOST = "https://raw.githubusercontent.com"
# where to look for a newer catalogue when plugins.json names no self_url
DEFAULT_CATALOGUE_URL = (f"{RAW_HOST}/{GITHUB_REPO}/main/config/plugins.json")
CODELOAD = "https://codeload.github.com"
USER_AGENT = f"OSC-DreamChatbox/{VERSION.lstrip('v')}"
TIMEOUT = 15
MAX_MANIFEST = 256 * 1024          # a plugin.json is a couple of kB
MAX_IMAGE = 4 * 1024 * 1024
MAX_ARCHIVE = 32 * 1024 * 1024
IMAGE_CACHE = CONFIG_DIR / "store_cache"
# tried in order when "image" is absent or 404s
IMAGE_FALLBACKS = ("logo.png", "preview.png", "icon.png", "banner.png",
                   "screenshot.png", "logo.jpg", "preview.jpg")
# user-maintained additions, merged on top of the shipped plugins.json
USER_SOURCES_FILE = CONFIG_DIR / "plugins_sources.json"
# downloaded catalogue updates land here, next to the user's own config
CACHED_SOURCES_FILE = CONFIG_DIR / "plugins.json"


class StoreError(Exception):
    """Network or metadata problem while talking to the store."""


# --------------------------------------------------------------------
# GitHub URL handling
# --------------------------------------------------------------------
@dataclass
class Source:
    owner: str
    repo: str
    ref: str = "main"
    path: str = ""          # folder inside the repo, "" = repo root

    @property
    def key(self):
        return f"{self.owner}/{self.repo}/{self.ref}/{self.path}".rstrip("/")

    def raw(self, filename):
        parts = [p for p in (self.path, filename) if p]
        return f"{RAW_HOST}/{self.owner}/{self.repo}/{self.ref}/" \
               + "/".join(parts)

    @property
    def tarball(self):
        return f"{CODELOAD}/{self.owner}/{self.repo}/tar.gz/refs/heads/" \
               f"{self.ref}"

    @property
    def web_url(self):
        base = f"https://github.com/{self.owner}/{self.repo}"
        return f"{base}/tree/{self.ref}/{self.path}" if self.path else base


def parse_github_url(url):
    """Accepts what you get from the address bar:

        .../owner/repo
        .../owner/repo/tree/<ref>/<path>
        .../owner/repo/blob/<ref>/<path>/plugin.json

    Returns a Source, or raises StoreError for anything else. Keeping this
    forgiving matters – the whole point is pasting a link without thinking
    about its shape.
    """
    text = str(url).strip().rstrip("/")
    if not text:
        raise StoreError("empty URL")
    text = re.sub(r"^(https?://)?(www\.)?github\.com/", "", text)
    parts = [p for p in text.split("/") if p]
    if len(parts) < 2:
        raise StoreError(f"not a GitHub project URL: {url}")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    ref, path = "main", ""
    if len(parts) > 2:
        if parts[2] in ("tree", "blob") and len(parts) > 3:
            ref = parts[3]
            path = "/".join(parts[4:])
        else:
            path = "/".join(parts[2:])
    # a link straight to the manifest still means "this folder"
    if path.endswith("/plugin.json"):
        path = path[: -len("/plugin.json")]
    elif path == "plugin.json":
        path = ""
    return Source(owner=owner, repo=repo, ref=ref, path=path)


# --------------------------------------------------------------------
# tiny fetch helpers
# --------------------------------------------------------------------
def _get(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise StoreError(f"HTTP {e.code} for {url}")
    except Exception as e:
        raise StoreError(f"{type(e).__name__}: {e}")
    if len(data) > limit:
        raise StoreError(f"response larger than {limit // 1024} kB: {url}")
    return data


def compare_versions(a, b):
    """Returns 1 if a > b, -1 if a < b, 0 if equal.

    Numeric parts are compared as numbers so 1.10.0 beats 1.9.0; a version
    with a suffix (1.2.0-alpha) sorts BELOW the plain one, which is what
    you want for pre-releases.
    """
    def parts(v):
        v = str(v).strip().lstrip("vV")
        nums = re.findall(r"\d+", v.split("-")[0])
        return [int(n) for n in nums] or [0], ("-" in v)

    na, pre_a = parts(a)
    nb, pre_b = parts(b)
    for x, y in zip(na + [0] * len(nb), nb + [0] * len(na)):
        if x != y:
            return 1 if x > y else -1
    if pre_a != pre_b:
        return -1 if pre_a else 1
    return 0


# --------------------------------------------------------------------
# store entries
# --------------------------------------------------------------------
@dataclass
class StoreEntry:
    source: Source
    pid: str = ""
    name: str = ""
    version: str = "?"
    author: str = ""
    description: str = ""
    summary: str = ""
    image_url: str = ""
    image_path: Path = None
    error: str = ""
    # filled in against the installed set
    installed_version: str = ""
    has_update: bool = False

    @property
    def installed(self):
        return bool(self.installed_version)


class PluginStore:
    def __init__(self, log=print, sources_file=STORE_SOURCES_FILE):
        self.log = log
        self.sources_file = Path(sources_file)
        self.entries = []          # list[StoreEntry], last refresh result
        self.last_error = ""
        # catalogue self-update state
        self.catalogue_version = "0"
        self.catalogue_url = ""
        self.remote_version = ""
        self.catalogue_update = False
        self._remote_data = None

    # ------------------------------------------------- catalogue files
    def _read_catalogue(self, path):
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            self.log(f"Store: {path.name} is not valid JSON ({e})")
            return None
        if isinstance(data, list):          # bare list of URLs is fine too
            return {"sources": data, "version": "0"}
        if not isinstance(data, dict):
            self.log(f"Store: {path.name} must contain an object or a list")
            return None
        return data

    def _active_catalogue(self):
        """The shipped catalogue, or the downloaded one when that carries a
        higher version. Returns (data, path)."""
        shipped = self._read_catalogue(self.sources_file) or {}
        cached = self._read_catalogue(CACHED_SOURCES_FILE)
        if cached is not None:
            sv = str(shipped.get("version", "0"))
            cv = str(cached.get("version", "0"))
            # ties go to the cache: it is the freshest download, and an
            # unversioned catalogue would otherwise never be used
            if compare_versions(cv, sv) >= 0:
                return cached, CACHED_SOURCES_FILE
            # only a strictly newer shipped file beats it - that is an app
            # update having overtaken the cache, which would shadow it
            try:
                CACHED_SOURCES_FILE.unlink()
                self.log("Store: dropped the outdated catalogue cache")
            except OSError:
                pass
        return shipped, self.sources_file

    # ------------------------------------------------------- catalogue
    def load_sources(self):
        """Effective catalogue plus the user's own file, de-duplicated while
        keeping the order. Also records the catalogue version and the URL to
        check for updates."""
        active, path = self._active_catalogue()
        self.catalogue_version = str(active.get("version", "0"))
        self.catalogue_url = str(active.get("self_url") or DEFAULT_CATALOGUE_URL)
        urls = []
        blocks = [(active, path)]
        user = self._read_catalogue(USER_SOURCES_FILE)
        if user is not None:
            blocks.append((user, USER_SOURCES_FILE))
        for data, path in blocks:
            raw = data.get("sources")
            if not isinstance(raw, list):
                self.log(f"Store: {path.name} has no 'sources' list")
                continue
            for item in raw:
                # allow both "url" and {"url": ..., "ref": ...}
                url = item.get("url") if isinstance(item, dict) else item
                if isinstance(url, str) and url.strip() \
                        and url.strip() not in urls:
                    urls.append(url.strip())
        return urls

    # ----------------------------------------------- catalogue update
    def sync_catalogue(self):
        """Downloads the current catalogue and caches it in the config
        folder. Called on every store refresh, so an AppImage user gets new
        plugins without a new AppImage.

        Never raises and never destroys what is already there: on a network
        error or a malformed answer the existing catalogue keeps working.
        Returns (changed, version, error).
        """
        if not self.catalogue_url:
            self.load_sources()
        # pin it: load_sources() below re-reads it from disk, which would
        # otherwise overwrite the URL we are actually talking to
        url = self.catalogue_url
        try:
            raw = _get(url, MAX_MANIFEST)
            data = json.loads(raw.decode("utf-8"))
        except StoreError as e:
            self.log(f"Store: plugin list not fetched ({e}) – using the "
                     f"local copy")
            return (False, self.catalogue_version, str(e))
        except Exception as e:
            self.log(f"Store: remote plugin list is not valid JSON ({e})")
            return (False, self.catalogue_version, str(e))
        if not isinstance(data, dict) or not isinstance(data.get("sources"),
                                                        list):
            msg = "remote plugin list has no 'sources' list"
            self.log(f"Store: {msg}")
            return (False, self.catalogue_version, msg)

        before = list(self.load_sources())
        shipped = self._read_catalogue(self.sources_file) or {}
        data = dict(data)
        # an unversioned download must not lose against the shipped file
        if "version" not in data:
            data["version"] = str(shipped.get("version", "0"))
        # remember where this copy came from, otherwise the next refresh
        # falls back to the default URL and a catalogue hosted elsewhere
        # would only ever be fetched once
        data.setdefault("self_url", url)
        try:
            CACHED_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHED_SOURCES_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError as e:
            self.log(f"Store: could not cache the plugin list: {e}")
            return (False, self.catalogue_version, str(e))

        after = list(self.load_sources())
        self.catalogue_update = False
        self._remote_data = None
        self.remote_version = ""
        changed = after != before
        if changed:
            self.log(f"Store: plugin list updated from GitHub "
                     f"(v{self.catalogue_version}, {len(after)} entries)")
        return (changed, self.catalogue_version, "")

    def check_catalogue_update(self):
        """Asks GitHub whether a newer catalogue exists. Only sets the flag –
        downloading is the user's decision. Returns True when there is one."""
        self.catalogue_update = False
        self.remote_version = ""
        self._remote_data = None
        if not self.catalogue_url:
            self.load_sources()
        try:
            raw = _get(self.catalogue_url, MAX_MANIFEST)
            data = json.loads(raw.decode("utf-8"))
        except StoreError as e:
            self.log(f"Store: catalogue check failed ({e})")
            return False
        except Exception as e:
            self.log(f"Store: remote catalogue is not valid JSON ({e})")
            return False
        if not isinstance(data, dict) or not isinstance(data.get("sources"),
                                                        list):
            self.log("Store: remote catalogue has no 'sources' list")
            return False
        remote = str(data.get("version", "0"))
        if compare_versions(remote, self.catalogue_version) <= 0:
            return False
        self.remote_version = remote
        self._remote_data = data
        self.catalogue_update = True
        self.log(f"Store: catalogue v{remote} available "
                 f"(local v{self.catalogue_version})")
        return True

    def apply_catalogue_update(self):
        """Writes the newer catalogue into the config folder – deliberately
        NOT into the project folder, which may be root-owned (AUR) or a git
        checkout. Returns the new version, or "" when nothing was pending."""
        if not self.catalogue_update or self._remote_data is None:
            return ""
        data = dict(self._remote_data)
        try:
            CACHED_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHED_SOURCES_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError as e:
            self.log(f"Store: could not save the catalogue: {e}")
            return ""
        version = str(data.get("version", "0"))
        self.catalogue_update = False
        self._remote_data = None
        self.log(f"Store: catalogue updated to v{version} "
                 f"({CACHED_SOURCES_FILE})")
        self.load_sources()
        return version

    # --------------------------------------------------------- refresh
    def refresh(self, installed=None):
        """Fetches every source's plugin.json. Runs on a worker thread –
        one unreachable entry must not hide the rest, so failures are
        stored per entry instead of raising."""
        installed = installed or {}
        entries = []
        self.last_error = ""
        self.sync_catalogue()          # always take the newest list first
        urls = self.load_sources()
        if not urls:
            self.last_error = ("No sources configured. Add GitHub links to "
                               "plugins.json next to the app.")
        for url in urls:
            try:
                src = parse_github_url(url)
            except StoreError as e:
                self.log(f"Store: skipping '{url}': {e}")
                continue
            entry = StoreEntry(source=src)
            try:
                self._load_manifest(entry)
            except StoreError as e:
                entry.error = str(e)
                entry.name = entry.name or src.path.split("/")[-1] or src.repo
                self.log(f"Store: {src.key}: {e}")
            self._mark_installed(entry, installed)
            entries.append(entry)
        self.entries = entries
        return entries

    def _load_manifest(self, entry):
        data = json.loads(_get(entry.source.raw("plugin.json"),
                               MAX_MANIFEST).decode("utf-8"))
        if not isinstance(data, dict):
            raise StoreError("plugin.json does not contain an object")
        entry.pid = str(data.get("id", "")).strip().lower()
        entry.name = str(data.get("name") or entry.pid or "?")
        entry.version = str(data.get("version") or "?")
        entry.author = str(data.get("author") or "unknown")
        entry.description = str(data.get("description") or "")
        entry.summary = str(data.get("summary") or entry.description)
        image = str(data.get("image") or "").strip()
        if image:
            entry.image_url = image if image.startswith(("http://", "https://")) \
                else entry.source.raw(image)

    def _mark_installed(self, entry, installed):
        cur = installed.get(entry.pid)
        if not cur:
            return
        entry.installed_version = cur
        entry.has_update = (entry.version != "?"
                            and compare_versions(entry.version, cur) > 0)

    # ----------------------------------------------------------- image
    def fetch_image(self, entry):
        """Downloads the preview into a local cache. Returns a Path or
        None – a missing image is cosmetic, never an error.

        Tries the declared "image" first, then the conventional file names.
        That covers the common case of a manifest saying preview.png while
        the folder actually holds a logo.png.
        """
        candidates = []
        if entry.image_url:
            candidates.append(entry.image_url)
        for name in IMAGE_FALLBACKS:
            url = entry.source.raw(name)
            if url not in candidates:
                candidates.append(url)

        stem = entry.pid or entry.source.repo
        for url in candidates:
            suffix = Path(url).suffix.lower()
            if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
                suffix = ".png"
            target = IMAGE_CACHE / f"{stem}{suffix}"
            if target.exists() and target.stat().st_size > 0:
                entry.image_url = url
                entry.image_path = target
                return target
            try:
                data = _get(url, MAX_IMAGE)
            except StoreError:
                continue
            try:
                IMAGE_CACHE.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            except OSError as e:
                self.log(f"Store: could not cache the image for "
                         f"{entry.name}: {e}")
                return None
            entry.image_url = url
            entry.image_path = target
            return target
        return None

    # --------------------------------------------------------- install
    def build_zip(self, entry, workdir):
        """Downloads the repository archive and repacks just this plugin's
        folder into a .zip, so the existing install path (with all its
        validation and its configs/ preservation) can be reused.

        GitHub has no 'download one subfolder' endpoint, and doing it file
        by file through the API would hit the 60/hour limit, so grabbing
        the tarball once is both simpler and kinder to the rate limit.
        """
        src = entry.source
        workdir = Path(workdir)
        tar_path = workdir / "repo.tar.gz"
        data = _get(src.tarball, MAX_ARCHIVE)
        tar_path.write_bytes(data)

        extract = workdir / "src"
        extract.mkdir()
        try:
            shutil.unpack_archive(str(tar_path), str(extract))
        except Exception as e:
            raise StoreError(f"archive could not be unpacked ({e})")

        # the tarball has a single <repo>-<ref>/ top level folder
        tops = [p for p in extract.iterdir() if p.is_dir()]
        if not tops:
            raise StoreError("archive is empty")
        root = tops[0] / src.path if src.path else tops[0]
        if not (root / "plugin.json").is_file():
            raise StoreError(f"no plugin.json at '{src.path or '/'}' "
                             f"in {src.owner}/{src.repo}")

        folder_name = entry.pid or root.name
        staged = workdir / folder_name
        shutil.move(str(root), str(staged))
        zip_path = workdir / f"{folder_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in sorted(staged.rglob("*")):
                if item.is_file():
                    zf.write(item, f"{folder_name}/"
                                   f"{item.relative_to(staged)}")
        return zip_path

    def install(self, entry, manager):
        """Downloads and installs through PluginManager, which keeps all
        the zip validation and preserves configs/ on an update."""
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = self.build_zip(entry, tmp)
            plugin = manager.install_plugin_zip(zip_path, overwrite=True)
        if plugin is not None:
            entry.installed_version = plugin.version
            entry.has_update = False
        return plugin

    # --------------------------------------------------------- updates
    def check_updates(self, installed):
        """Refreshes the catalogue and returns the entries that are
        installed and have a newer version upstream."""
        self.refresh(installed)
        return [e for e in self.entries if e.has_update]
