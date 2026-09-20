"""High-level mod resolver.

Resolution order: project_id → file hash → jar metadata hints
(mod_id as known_slug first, then human-readable name with known_authors).
Always returns a dict with an explicit status.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

from .api import ModrinthAPI
from .jar_metadata import read_jar_metadata
from .utils import sha1_of_file

logger = logging.getLogger(__name__)


class ModResolver:
    def __init__(self, api: Optional[ModrinthAPI] = None):
        self.api = api or ModrinthAPI()

    def resolve(
        self,
        query: str,
        mc_version: str,
        loader: str,
        jar_path: Optional[Path] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve by project_id, jar file, and/or name query.

        query may be None when project_id or jar_path is given.
        """
        if project_id:
            return self.api.resolve_by_project_id(project_id, mc_version, loader)

        jar_meta = None
        if jar_path and jar_path.exists():
            try:
                file_hash = sha1_of_file(jar_path)
            except Exception as e:
                logger.error("Failed to hash SHA1 for %s: %s", jar_path, e)
                file_hash = None

            if file_hash:
                result = self.api.resolve_by_hash(file_hash, mc_version, loader)
                if result.get('status') == 'found':
                    return result

            jar_meta = read_jar_metadata(jar_path)

        if query or jar_meta:
            slug_hint = jar_meta.get('mod_id') if jar_meta else None
            authors_hint = jar_meta.get('authors') if jar_meta else None
            name_hint = jar_meta.get('name') if jar_meta else None

            # mod_id as slug is more precise than title matching
            search_query = name_hint or query
            if slug_hint:
                result = self.api.resolve_by_query(
                    slug_hint, mc_version, loader,
                    known_authors=authors_hint,
                    known_slug=slug_hint,
                )
                if result.get('status') == 'found':
                    return result

            if search_query:
                return self.api.resolve_by_query(
                    search_query, mc_version, loader,
                    known_authors=authors_hint,
                )

        return {'status': 'not_found'}

    def resolve_from_jar(
        self,
        jar_path: Path,
        mc_version: str,
        loader: str,
    ) -> Dict[str, Any]:
        """Resolve using only a jar file (no query)."""
        return self.resolve(
            query=None,
            mc_version=mc_version,
            loader=loader,
            jar_path=jar_path,
        )