"""Read mod metadata straight from a .jar file.

Supports fabric.mod.json (Fabric), quilt.mod.json (Quilt) and
META-INF/{neoforge.,}mods.toml (NeoForge/Forge). Returns
{"mod_id", "name", "authors", "loader"} or None when unrecognized.
"""

import json
import logging
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any

from .utils import normalize_authors

logger = logging.getLogger(__name__)


# tomllib ships with Python 3.11+; tomli is the fallback for older versions.
try:
    import tomllib  # type: ignore
    _TOML_LOADER = lambda b: tomllib.loads(b.decode("utf-8"))
except ImportError:  # pragma: no cover
    try:
        import tomli  # type: ignore
        _TOML_LOADER = lambda b: tomli.loads(b.decode("utf-8"))
    except ImportError:
        _TOML_LOADER = None


# Metadata entries are kilobytes; cap reads since z.read() unpacks the
# whole entry into memory (a hostile jar could exhaust it).
_MAX_META_BYTES = 1_000_000


def _read_capped(z: zipfile.ZipFile, name: str) -> bytes:
    """Read a zip entry, refusing suspiciously large ones."""
    try:
        if z.getinfo(name).file_size > _MAX_META_BYTES:
            raise ValueError(f"suspiciously large entry: {z.getinfo(name).file_size} bytes")
    except KeyError:
        raise
    data = z.read(name)
    if len(data) > _MAX_META_BYTES:
        raise ValueError(f"suspiciously large entry: {len(data)} bytes")
    return data


def read_jar_metadata(jar_path: Path) -> Optional[Dict[str, Any]]:
    """Extract mod metadata from a .jar, or None when unrecognized."""
    try:
        with zipfile.ZipFile(jar_path) as z:
            names = set(z.namelist())

            if 'fabric.mod.json' in names:
                try:
                    data = json.loads(_read_capped(z, 'fabric.mod.json').decode('utf-8'))
                    return {
                        'mod_id': data.get('id'),
                        'name': data.get('name') or data.get('id'),
                        'authors': normalize_authors(data.get('authors')),
                        'loader': 'fabric',
                    }
                except Exception as e:
                    logger.warning("Failed to parse fabric.mod.json in %s: %s", jar_path, e)

            if 'quilt.mod.json' in names:
                try:
                    data = json.loads(_read_capped(z, 'quilt.mod.json').decode('utf-8'))
                    ql = data.get('quilt_loader', {}) or {}
                    md = ql.get('metadata', {}) or {}
                    return {
                        'mod_id': ql.get('id'),
                        'name': md.get('name') or ql.get('id'),
                        'authors': normalize_authors(md.get('contributors')),
                        'loader': 'quilt',
                    }
                except Exception as e:
                    logger.warning("Failed to parse quilt.mod.json in %s: %s", jar_path, e)

            for toml_path in ('META-INF/neoforge.mods.toml', 'META-INF/mods.toml'):
                if toml_path in names:
                    if _TOML_LOADER is None:
                        logger.warning(
                            "Reading %s needs tomllib (Python 3.11+) or tomli",
                            toml_path,
                        )
                        continue
                    try:
                        data = _TOML_LOADER(_read_capped(z, toml_path))
                        mods = data.get('mods') or []
                        if not mods:
                            continue
                        m = mods[0]
                        loader = 'neoforge' if 'neoforge' in toml_path else 'forge'
                        return {
                            'mod_id': m.get('modId'),
                            'name': m.get('displayName') or m.get('modId'),
                            'authors': normalize_authors(m.get('authors')),
                            'loader': loader,
                        }
                    except Exception as e:
                        logger.warning("Failed to parse %s in %s: %s", toml_path, jar_path, e)

    except zipfile.BadZipFile:
        logger.warning("Not a .jar/.zip file: %s", jar_path)
    except Exception as e:
        logger.warning("Metadata read error %s: %s", jar_path, e)

    return None