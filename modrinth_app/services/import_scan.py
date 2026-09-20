"""Parallel import of mod names from a folder of .jar files.

Strategy per file: SHA1 → version_file lookup → project title; if the
hash is unknown, fall back to in-jar metadata (name/mod_id); otherwise
the file is marked unrecognized. Blocking — call from a worker thread.
"""

import logging
import threading
from concurrent.futures import CancelledError, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from ..api import ModrinthAPI
from ..jar_metadata import read_jar_metadata
from ..utils import sha1_of_file
from .transfer import cancelable_pool

logger = logging.getLogger(__name__)


class ImportItemStatus:
    OK_HASH = 'ok_hash'
    OK_META = 'ok_meta'
    UNKNOWN = 'unknown'
    READ_ERROR = 'read_error'


@dataclass
class ImportItemResult:
    jar_name: str
    status: str
    display_name: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ImportProgress:
    done: int
    total: int
    current_name: str = ''

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(self.done / self.total, 1.0)


@dataclass
class ImportSummary:
    results: List[ImportItemResult] = field(default_factory=list)
    total: int = 0
    ok: int = 0
    unknown: int = 0

    def add(self, r: ImportItemResult) -> None:
        self.results.append(r)
        if r.status in (ImportItemStatus.OK_HASH, ImportItemStatus.OK_META):
            self.ok += 1
        else:
            self.unknown += 1

    def recognized_names(self) -> List[str]:
        """Unique recognized names, sorted."""
        seen = set()
        out = []
        for r in self.results:
            if r.display_name and r.display_name not in seen:
                seen.add(r.display_name)
                out.append(r.display_name)
        out.sort()
        return out


@dataclass
class ImportCallbacks:
    on_progress: Optional[Callable[[ImportProgress], None]] = None
    on_done: Optional[Callable[[ImportSummary], None]] = None


class ImportScanService:
    """Parallel .jar folder scan for name importing (blocking)."""

    def __init__(
        self,
        api: ModrinthAPI,
        max_workers: int = 8,
    ):
        self.api = api
        self.max_workers = max_workers

    def execute(
        self,
        folder: Path,
        callbacks: Optional[ImportCallbacks] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ImportSummary:
        callbacks = callbacks or ImportCallbacks()
        cancel_event = cancel_event or threading.Event()

        jar_files = sorted(folder.glob("*.jar"))
        summary = ImportSummary(total=len(jar_files))
        if not jar_files:
            if callbacks.on_done:
                callbacks.on_done(summary)
            return summary

        done = 0
        with cancelable_pool(self.max_workers, cancel_event) as ex:
            futures = {
                ex.submit(self._scan_one, jar): jar
                for jar in jar_files
            }

            for fut in as_completed(futures):
                jar = futures[fut]
                if cancel_event.is_set():
                    break

                try:
                    result = fut.result()
                except CancelledError:
                    continue
                except Exception as e:
                    logger.exception("Scan error %s: %s", jar.name, e)
                    result = ImportItemResult(
                        jar_name=jar.name,
                        status=ImportItemStatus.READ_ERROR,
                        error=str(e),
                    )

                done += 1
                summary.add(result)

                if callbacks.on_progress:
                    callbacks.on_progress(ImportProgress(
                        done=done, total=len(jar_files),
                        current_name=jar.name,
                    ))

        if callbacks.on_done:
            callbacks.on_done(summary)
        return summary

    # -- worker -- #

    def _scan_one(self, jar: Path) -> ImportItemResult:
        try:
            file_hash = sha1_of_file(jar)
        except Exception as e:
            return ImportItemResult(
                jar_name=jar.name,
                status=ImportItemStatus.READ_ERROR,
                error=str(e),
            )

        version_data = self.api.get_version_by_hash(file_hash)
        if version_data:
            project_id = version_data.get('project_id')
            project = self.api.get_project(project_id) if project_id else None
            if project and project.get('title'):
                return ImportItemResult(
                    jar_name=jar.name,
                    status=ImportItemStatus.OK_HASH,
                    display_name=project['title'],
                )

        meta = read_jar_metadata(jar)
        if meta and meta.get('name'):
            return ImportItemResult(
                jar_name=jar.name,
                status=ImportItemStatus.OK_META,
                display_name=meta['name'],
            )

        return ImportItemResult(
            jar_name=jar.name,
            status=ImportItemStatus.UNKNOWN,
        )