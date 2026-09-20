"""Modrinth API client.

Public methods return status dicts (found | no_version | ambiguous |
not_found | author_mismatch | rate_limited) instead of plain name/url
pairs. Uses one HTTP session with retry on 429/5xx plus an in-memory
project/team cache with TTL.
"""

import logging
import threading
import time
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .localization import t as _t
from ._version import __version__

logger = logging.getLogger(__name__)


# Resolution statuses returned in result dicts.
STATUS_FOUND             = 'found'
STATUS_NO_VERSION        = 'no_version'
STATUS_AMBIGUOUS         = 'ambiguous'
STATUS_NOT_FOUND         = 'not_found'
STATUS_AUTHOR_MISMATCH   = 'author_mismatch'
STATUS_RATE_LIMITED      = 'rate_limited'


class ModrinthAPI:
    """Thread-safe client for the public Modrinth v2 API."""

    BASE_URL = "https://api.modrinth.com/v2"
    # Modrinth requires a descriptive User-Agent with contact, else it throttles.
    APP_NAME = "ModBridge"
    APP_CONTACT = "+https://github.com/WoolfinDev/ModBridge"

    # Cache lives for one app session; refreshed every 10 minutes so long
    # runs never serve indefinitely stale data.
    _CACHE_TTL_SECONDS = 600

    def __init__(self, lang: str = "ru"):
        self.lang = lang if lang in ("ru", "en") else "ru"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'{self.APP_NAME}/{__version__} ({self.APP_CONTACT})',
        })

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.6,  # 0.6s → 1.2s → 2.4s
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
        self.session.mount("https://", adapter)
        # No http:// mount on purpose: Modrinth/CDN must stay on https.

        self._project_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._team_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_lock = threading.Lock()
        self._cache_started_at = time.monotonic()

        self._requests_made = 0
        self._requests_lock = threading.Lock()

    # -- internals -- #

    def set_lang(self, lang: str) -> None:
        if lang in ("ru", "en"):
            self.lang = lang

    def _t(self, key: str, **kwargs) -> str:
        return _t(key, self.lang, **kwargs)

    def _bump_requests(self, n: int = 1) -> None:
        with self._requests_lock:
            self._requests_made += n

    def get_request_count(self) -> int:
        with self._requests_lock:
            return self._requests_made

    def _maybe_reset_cache(self) -> None:
        """Drop caches once they outlive _CACHE_TTL_SECONDS."""
        with self._cache_lock:
            if time.monotonic() - self._cache_started_at > self._CACHE_TTL_SECONDS:
                self._project_cache.clear()
                self._team_cache.clear()
                self._cache_started_at = time.monotonic()

    @staticmethod
    def _is_rate_limited(resp: requests.Response) -> bool:
        return resp.status_code == 429

    # -- low-level requests -- #

    def _get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 10,
    ) -> Optional[Any]:
        """GET with retry. Returns parsed JSON (200), None (404/other
        errors) or the 'rate_limited' marker (429 after retries)."""
        self._bump_requests()
        try:
            resp = self.session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            logger.error("Network error %s: %s", url, e)
            return None

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                logger.error("Invalid JSON from %s", url)
                return None
        if resp.status_code == 404:
            return None
        if self._is_rate_limited(resp):
            retry_after = resp.headers.get("Retry-After", "?")
            logger.warning("429 Too Many Requests from %s (Retry-After: %s)", url, retry_after)
            return 'rate_limited'

        logger.warning("HTTP %s from %s", resp.status_code, url)
        return None

    # -- cached project/team access -- #

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        self._maybe_reset_cache()
        with self._cache_lock:
            if project_id in self._project_cache:
                return self._project_cache[project_id]

        data = self._get_json(f"{self.BASE_URL}/project/{project_id}")
        if data == 'rate_limited':
            return None  # never cache: retry on the next call
        if not isinstance(data, dict):
            data = None

        with self._cache_lock:
            self._project_cache[project_id] = data
        return data

    def get_team_members(self, team_id: str) -> List[Dict[str, Any]]:
        self._maybe_reset_cache()
        with self._cache_lock:
            if team_id in self._team_cache:
                return self._team_cache[team_id]

        data = self._get_json(f"{self.BASE_URL}/team/{team_id}/members")
        if data == 'rate_limited' or not isinstance(data, list):
            data = []

        with self._cache_lock:
            self._team_cache[team_id] = data
        return data

    def get_project_authors(self, project: Dict[str, Any]) -> List[str]:
        """Author names of a project (resolved via its team)."""
        team_id = project.get('team')
        if not team_id:
            return []
        members = self.get_team_members(team_id)
        names: List[str] = []
        for m in members:
            user = m.get('user') or {}
            name = user.get('username') or user.get('name')
            if name:
                names.append(name)
        return names

    def get_version_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Version record for a file SHA1 hash."""
        data = self._get_json(f"{self.BASE_URL}/version_file/{file_hash}")
        if isinstance(data, dict):
            return data
        return None

    def get_versions(self, project_id: str) -> List[Dict[str, Any]]:
        data = self._get_json(f"{self.BASE_URL}/project/{project_id}/version")
        if isinstance(data, list):
            return data
        return []

    def search(
        self,
        query: str,
        mc_version: str,
        loader: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Raw name search; returns hits."""
        params = {
            "query": query,
            "limit": limit,
            "facets": (
                f'[["project_type:mod"], '
                f'["categories:{loader}"], '
                f'["versions:{mc_version}"]]'
            ),
        }
        data = self._get_json(f"{self.BASE_URL}/search", params=params)
        if isinstance(data, dict):
            return data.get('hits', []) or []
        return []

    # -- version picking -- #

    def pick_version_for(
        self,
        project_id: str,
        mc_version: str,
        loader: str,
    ) -> Optional[Dict[str, Any]]:
        """Best project version for (mc_version, loader), or None."""
        versions = self.get_versions(project_id)
        for v in versions:
            if mc_version in v.get('game_versions', []) and loader in v.get('loaders', []):
                files = v.get('files') or []
                if not files:
                    continue
                primary = next((f for f in files if f.get('primary')), files[0])
                hashes = primary.get('hashes') or {}
                return {
                    'version_number': v.get('version_number'),
                    'download_url': primary.get('url'),
                    'filename': primary.get('filename'),
                    'file_size': primary.get('size'),
                    'file_hashes': hashes,
                    'file_sha1': hashes.get('sha1'),
                    'game_versions': v.get('game_versions', []),
                    'loaders': v.get('loaders', []),
                    'version_id': v.get('id'),
                }
        return None

    # -- high-level resolution strategies -- #

    def resolve_by_project_id(
        self,
        project_id: str,
        mc_version: str,
        loader: str,
    ) -> Dict[str, Any]:
        """Most reliable path: the project is known, no mismatch possible."""
        project = self.get_project(project_id)
        if not project:
            return {'status': STATUS_NOT_FOUND}

        version = self.pick_version_for(project_id, mc_version, loader)
        if not version:
            return {
                'status': STATUS_NO_VERSION,
                'project_id': project_id,
                'name': project.get('title'),
                'slug': project.get('slug'),
                'icon_url': project.get('icon_url'),
                'reason': self._t('no_version_for', mc=mc_version, loader=loader),
            }

        return {
            'status': STATUS_FOUND,
            'project_id': project_id,
            'name': project.get('title'),
            'slug': project.get('slug'),
            'icon_url': project.get('icon_url'),
            'authors': self.get_project_authors(project),
            **version,
        }

    def resolve_by_hash(
        self,
        file_hash: str,
        mc_version: str,
        loader: str,
    ) -> Dict[str, Any]:
        """Resolve a mod by its file SHA1 hash."""
        version_data = self.get_version_by_hash(file_hash)
        if not version_data:
            return {'status': STATUS_NOT_FOUND}
        project_id = version_data.get('project_id')
        if not project_id:
            return {'status': STATUS_NOT_FOUND}
        return self.resolve_by_project_id(project_id, mc_version, loader)

    # -- candidate scoring -- #

    @staticmethod
    def _score_hit(hit: Dict[str, Any], query: str) -> float:
        q = (query or '').strip().lower()
        title = (hit.get('title') or '').lower()
        slug = (hit.get('slug') or '').lower()

        if not q:
            return 0.0
        if title == q or slug == q:
            return 1.0

        r_title = SequenceMatcher(None, q, title).ratio()
        r_slug = SequenceMatcher(None, q, slug).ratio()
        base = max(r_title, r_slug)

        downloads = hit.get('downloads') or 0
        bonus = min(downloads / 5_000_000, 0.1)
        return base + bonus

    def resolve_by_query(
        self,
        query: str,
        mc_version: str,
        loader: str,
        known_authors: Optional[List[str]] = None,
        known_slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve by name (last resort). Priority: exact slug match,
        exact title matches filtered by authors, then best scoring
        hit if it clearly leads, otherwise ambiguous."""
        hits = self.search(query, mc_version, loader, limit=10)
        if not hits:
            return {'status': STATUS_NOT_FOUND}

        q = query.strip().lower()

        if known_slug:
            for h in hits:
                if (h.get('slug') or '').lower() == known_slug.lower():
                    return self._finalize_hit(h, mc_version, loader)

        exact = [
            h for h in hits
            if (h.get('title') or '').lower() == q or (h.get('slug') or '').lower() == q
        ]

        if exact:
            if known_authors and len(exact) > 1:
                filtered = []
                for h in exact:
                    proj = self.get_project(h['project_id'])
                    if not proj:
                        continue
                    authors = self.get_project_authors(proj)
                    if set(a.lower() for a in authors) & set(a.lower() for a in known_authors):
                        filtered.append(h)
                if len(filtered) == 1:
                    return self._finalize_hit(filtered[0], mc_version, loader)
                if len(filtered) > 1:
                    return self._ambiguous(filtered, mc_version, loader)

            if len(exact) == 1:
                return self._finalize_hit(exact[0], mc_version, loader)

            return self._ambiguous(exact, mc_version, loader)

        scored = sorted(
            ((self._score_hit(h, query), h) for h in hits),
            key=lambda x: x[0],
            reverse=True,
        )
        best_score, best_hit = scored[0]

        if best_score >= 0.75 and (
            len(scored) == 1 or (best_score - scored[1][0]) >= 0.12
        ):
            if known_authors:
                proj = self.get_project(best_hit['project_id'])
                authors = self.get_project_authors(proj) if proj else []
                if not (set(a.lower() for a in authors) & set(a.lower() for a in known_authors)):
                    return {
                        'status': STATUS_AUTHOR_MISMATCH,
                        'name': best_hit.get('title'),
                        'project_id': best_hit.get('project_id'),
                        'slug': best_hit.get('slug'),
                        'icon_url': best_hit.get('icon_url'),
                        'reason': self._t(
                            'author_mismatch_for',
                            title=best_hit.get('title'),
                            authors=", ".join(known_authors),
                        ),
                    }
            return self._finalize_hit(best_hit, mc_version, loader)

        return self._ambiguous([h for _, h in scored[:5]], mc_version, loader)

    # -- helpers -- #

    def _finalize_hit(
        self,
        hit: Dict[str, Any],
        mc_version: str,
        loader: str,
    ) -> Dict[str, Any]:
        project_id = hit['project_id']
        project = self.get_project(project_id) or {}

        version = self.pick_version_for(project_id, mc_version, loader)
        if not version:
            return {
                'status': STATUS_NO_VERSION,
                'project_id': project_id,
                'name': project.get('title') or hit.get('title'),
                'slug': project.get('slug') or hit.get('slug'),
                'icon_url': project.get('icon_url') or hit.get('icon_url'),
                'reason': self._t('no_version_for', mc=mc_version, loader=loader),
            }

        return {
            'status': STATUS_FOUND,
            'project_id': project_id,
            'name': project.get('title') or hit.get('title'),
            'slug': project.get('slug') or hit.get('slug'),
            'icon_url': project.get('icon_url') or hit.get('icon_url'),
            'authors': self.get_project_authors(project),
            **version,
        }

    def _ambiguous(
        self,
        hits: List[Dict[str, Any]],
        mc_version: str,
        loader: str,
    ) -> Dict[str, Any]:
        candidates = []
        for h in hits:
            proj = self.get_project(h['project_id']) or {}
            candidates.append({
                'project_id': h['project_id'],
                'name': proj.get('title') or h.get('title'),
                'slug': proj.get('slug') or h.get('slug'),
                'icon_url': proj.get('icon_url') or h.get('icon_url'),
                'authors': self.get_project_authors(proj),
                'downloads': h.get('downloads', 0),
            })
        return {
            'status': STATUS_AMBIGUOUS,
            'candidates': candidates,
        }