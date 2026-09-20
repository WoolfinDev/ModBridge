"""Small platform/network/file helpers shared across the app."""

import re
import sys
import os
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Upper bound for a single mod .jar (Modrinth mods are ~1-50 MB).
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


def sanitize_filename(name: str, fallback: str = "mod.jar") -> str:
    """Strip directories / unsafe chars; never empty, never '.'/'..'."""
    base = Path(str(name or "")).name.strip()
    base = base.replace("\x00", "")
    # Windows-forbidden + URL-dangerous chars.
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    base = base.strip(" .")
    if not base or base in (".", ".."):
        return fallback
    # Must look like a file, keep extension if any.
    if len(base) > 128:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:120] + dot + ext[:10]) if dot else base[:128]
    return base or fallback


def sanitize_version_text(text: str, fallback: str = "unknown") -> str:
    """Safe folder/file fragment for user-typed MC versions."""
    t = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip())
    t = t.strip("._")[:32]
    return t or fallback


def download_url_to_file(
    url: str,
    dest: Path,
    session: Optional[requests.Session] = None,
    timeout: int = 30,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    expected_sha1: Optional[str] = None,
    expected_size: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """Stream a https URL to dest (atomic tmp+replace) with size/hash checks."""
    if not url or not url.lower().startswith("https://"):
        return False, "unsafe URL (https required)"
    client = session or requests
    try:
        resp = client.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
    except Exception as e:
        return False, str(e)
    try:
        length = resp.headers.get("Content-Length")
        if length is not None:
            try:
                if int(length) > max_bytes:
                    return False, f"file too large ({length} bytes)"
            except ValueError:
                pass
        tmp = dest.with_name(dest.name + ".part")
        h = hashlib.sha1()
        total = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    try:
                        f.close()
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return False, f"file too large (>{max_bytes} bytes)"
                f.write(chunk)
                h.update(chunk)
        if expected_size is not None and total != int(expected_size):
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return False, f"size mismatch (got {total}, expected {expected_size})"
        if expected_sha1 and h.hexdigest().lower() != str(expected_sha1).lower():
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return False, "sha1 mismatch"
        tmp.replace(dest)
        return True, None
    except Exception as e:
        logger.error("Download of %s failed: %s", dest.name, e)
        return False, str(e)
    finally:
        try:
            resp.close()
        except Exception:
            pass


def fetch_minecraft_release_version_ids() -> frozenset:
    """Release version ids, as a set (for membership checks)."""
    return frozenset(fetch_minecraft_release_versions_ordered())


def fetch_minecraft_release_versions_ordered() -> list:
    """Release versions in Mojang manifest order (newest first)."""
    response = requests.get(
        "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return [v["id"] for v in data["versions"] if v.get("type") == "release"]


def get_modrinth_profiles_path():
    """Windows/Linux Modrinth App profiles dir, or None if absent."""
    if sys.platform == 'win32':
        appdata = os.getenv('APPDATA')
        if appdata:
            path = Path(appdata) / 'ModrinthApp' / 'profiles'
            if path.exists():
                return path
    else:
        path = Path.home() / '.local' / 'share' / 'ModrinthApp' / 'profiles'
        if path.exists():
            return path
    return None


def get_user_data_dir(app_name: str = "ModBridge") -> Path:
    """Writable per-user data dir (config/downloads when exe dir is read-only)."""
    if sys.platform == 'win32':
        base = Path(os.getenv('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.getenv('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    d = base / app_name
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def resolve_config_file(app_path: Path, filename: str = "config.json") -> Path:
    """User-writable config path; migrates legacy exe-dir config once."""
    if not getattr(sys, 'frozen', False):
        return app_path / filename
    user_cfg = get_user_data_dir() / filename
    legacy = app_path / filename
    try:
        if not user_cfg.exists() and legacy.exists():
            user_cfg.write_bytes(legacy.read_bytes())
    except Exception:
        pass
    return user_cfg


def resolve_writable_base(app_path: Path) -> Path:
    """Base dir for output folders; falls back to user data dir if needed."""
    try:
        probe = app_path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return app_path
    except Exception:
        fallback = get_user_data_dir()
        # Downloads are more discoverable on desktop, but may not exist.
        downloads = Path.home() / "Downloads"
        try:
            if downloads.exists():
                return downloads
        except Exception:
            pass
        return fallback


def open_folder(path: Path):
    """Reveal a folder in the OS file manager (best effort)."""
    try:
        path_str = str(path)
        if sys.platform == 'win32':
            os.startfile(path_str)
        else:
            subprocess.Popen(
                ['xdg-open', path_str],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except Exception as e:
        logger.error(f"Failed to open folder: {e}")


def sha1_of_file(path: Path) -> str:
    """Streaming SHA1 of a file (used for Modrinth version_file lookup)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def normalize_authors(raw) -> List[str]:
    """Normalize author metadata to a name list.

    Accepts a string, a list of strings, a list of {'name': ...} dicts,
    or a {"Name": contact} dict (Forge TOML style).
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        return [k for k in raw.keys() if isinstance(k, str)]
    if isinstance(raw, Iterable):
        out: List[str] = []
        for a in raw:
            if isinstance(a, str):
                out.append(a)
            elif isinstance(a, dict):
                if 'name' in a and isinstance(a['name'], str):
                    out.append(a['name'])
        return out
    return []


def authors_match(local_authors: List[str], remote_authors: List[str]) -> bool:
    """True if at least one author name overlaps (case-insensitive)."""
    if not local_authors or not remote_authors:
        return False
    a = {x.strip().lower() for x in local_authors if x and x.strip()}
    b = {x.strip().lower() for x in remote_authors if x and x.strip()}
    return bool(a & b)