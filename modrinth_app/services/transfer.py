"""Parallel mod transfer service.

Processes N .jar files (resolve, then download) with bounded parallelism,
reporting progress via callbacks. Blocking — call from a worker thread.
Cancellation is cooperative: cancel_event is checked between items, and
the pool drops its queue instead of waiting out in-flight requests.
"""

import contextlib
import logging
import shutil
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Dict, Any

from ..api import (
    ModrinthAPI,
    STATUS_FOUND, STATUS_NO_VERSION, STATUS_AMBIGUOUS,
    STATUS_NOT_FOUND, STATUS_AUTHOR_MISMATCH, STATUS_RATE_LIMITED,
)
from ..resolver import ModResolver
from ..localization import t as _t

logger = logging.getLogger(__name__)


# -- result types -- #

class SingleResultStatus:
    OK = 'ok'
    NO_VERSION = 'no_version'
    AMBIGUOUS = 'ambiguous'
    AUTHOR_MISMATCH = 'author_mismatch'
    NOT_FOUND = 'not_found'
    RATE_LIMITED = 'rate_limited'
    READ_ERROR = 'read_error'
    DOWNLOAD_ERROR = 'download_error'


@dataclass
class TransferResult:
    jar_name: str
    status: str
    mod_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None
    dst_folder: Optional[Path] = None


@dataclass
class TransferProgress:
    done: int
    total: int
    current_name: str = ''
    phase: str = 'resolve'  # 'resolve' | 'download' | 'copy'

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(self.done / self.total, 1.0)


@dataclass
class TransferSummary:
    results: List[TransferResult] = field(default_factory=list)
    total: int = 0
    ok: int = 0
    failed: int = 0
    cancelled: bool = False

    def add(self, r: TransferResult) -> None:
        self.results.append(r)
        if r.status == SingleResultStatus.OK:
            self.ok += 1
        else:
            self.failed += 1


# -- cancelable pool -- #

@contextlib.contextmanager
def cancelable_pool(
    max_workers: int,
    cancel_event: threading.Event,
) -> Iterator[ThreadPoolExecutor]:
    """Pool that does not wait out pending tasks on cancellation.

    A plain `with ThreadPoolExecutor` runs shutdown(wait=True) on exit,
    so after a cancel break it still waits for retry backoffs and queued
    tasks — cancellation hangs for tens of seconds. Here a raised flag
    drops the queue (cancel_futures) and returns at once; in-flight
    requests quietly finish in the background.
    """
    ex = ThreadPoolExecutor(max_workers=max_workers)
    try:
        yield ex
    finally:
        if cancel_event.is_set():
            ex.shutdown(wait=False, cancel_futures=True)
        else:
            ex.shutdown(wait=True)


# -- callbacks -- #

@dataclass
class TransferCallbacks:
    # Fired per processed item (from worker threads); fired once at the end
    # from the thread that called execute().
    on_progress: Optional[Callable[[TransferProgress], None]] = None
    on_done: Optional[Callable[[TransferSummary], None]] = None


# -- service -- #

class TransferService:
    """Parallel .jar transfer from src_folder to dst_folder (blocking)."""

    def __init__(
        self,
        api: ModrinthAPI,
        resolver: ModResolver,
        max_workers: int = 8,
        download_timeout: int = 30,
    ):
        self.api = api
        self.resolver = resolver
        self.max_workers = max_workers
        self.download_timeout = download_timeout

    # -- public API -- #

    def execute(
        self,
        src_folder: Path,
        dst_folder: Path,
        mc_version: str,
        loader: str,
        callbacks: Optional[TransferCallbacks] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> TransferSummary:
        callbacks = callbacks or TransferCallbacks()
        cancel_event = cancel_event or threading.Event()

        jar_files = sorted(src_folder.glob("*.jar"))
        summary = TransferSummary(total=len(jar_files))

        if not jar_files:
            if callbacks.on_done:
                callbacks.on_done(summary)
            return summary

        dst_folder.mkdir(parents=True, exist_ok=True)

        # Phase 1: parallel resolving.
        resolved: List[tuple[Path, Dict[str, Any]]] = []
        done = 0

        with cancelable_pool(self.max_workers, cancel_event) as ex:
            futures = {
                ex.submit(self._resolve_one, jar, mc_version, loader): jar
                for jar in jar_files
            }

            for fut in as_completed(futures):
                jar = futures[fut]
                if cancel_event.is_set():
                    summary.cancelled = True
                    break

                try:
                    result = fut.result()
                except CancelledError:
                    continue  # dropped by fast cancellation, not counted
                except Exception as e:
                    logger.exception("Unhandled resolve error %s: %s", jar.name, e)
                    result = TransferResult(
                        jar_name=jar.name,
                        status=SingleResultStatus.READ_ERROR,
                        error=str(e),
                    )

                done += 1
                if result.status == SingleResultStatus.OK:
                    resolved.append((jar, result.mod_info))
                    summary.add(result)
                else:
                    result.dst_folder = dst_folder
                    summary.add(result)

                if callbacks.on_progress:
                    callbacks.on_progress(TransferProgress(
                        done=done, total=len(jar_files),
                        current_name=jar.name, phase='resolve',
                    ))

        # Phase 2: parallel downloading.
        if resolved and not cancel_event.is_set():
            downloaded = 0
            total_download = len(resolved)

            with cancelable_pool(self.max_workers, cancel_event) as ex:
                futures = {
                    ex.submit(self._download_one, jar, info, dst_folder): (jar, info)
                    for jar, info in resolved
                }

                for fut in as_completed(futures):
                    jar, info = futures[fut]
                    if cancel_event.is_set():
                        summary.cancelled = True
                        break

                    try:
                        ok, err = fut.result()
                    except CancelledError:
                        continue
                    except Exception as e:
                        logger.exception("Unhandled download error %s: %s", jar.name, e)
                        ok, err = False, str(e)

                    downloaded += 1

                    if not ok:
                        # Replace the previously recorded OK with a download error.
                        self._replace_with_download_error(
                            summary, jar.name, err,
                            lang=getattr(self.api, 'lang', 'ru'),
                        )

                    if callbacks.on_progress:
                        callbacks.on_progress(TransferProgress(
                            done=downloaded, total=total_download,
                            current_name=info.get('name') or jar.name,
                            phase='download',
                        ))

        if callbacks.on_done:
            callbacks.on_done(summary)
        return summary

    # -- pool workers -- #

    def _resolve_one(
        self,
        jar: Path,
        mc_version: str,
        loader: str,
    ) -> TransferResult:
        try:
            res = self.resolver.resolve_from_jar(jar, mc_version, loader)
        except Exception as e:
            logger.exception("Resolve error %s", jar.name)
            return TransferResult(
                jar_name=jar.name,
                status=SingleResultStatus.READ_ERROR,
                error=str(e),
            )

        status = res.get('status')

        if status == STATUS_FOUND:
            return TransferResult(
                jar_name=jar.name,
                status=SingleResultStatus.OK,
                mod_info=res,
            )
        if status == STATUS_NO_VERSION:
            return TransferResult(
                jar_name=jar.name,
                status=SingleResultStatus.NO_VERSION,
                mod_info=res,
                error=res.get('reason'),
            )
        if status == STATUS_AMBIGUOUS:
            return TransferResult(
                jar_name=jar.name,
                status=SingleResultStatus.AMBIGUOUS,
                candidates=res.get('candidates') or [],
            )
        if status == STATUS_AUTHOR_MISMATCH:
            return TransferResult(
                jar_name=jar.name,
                status=SingleResultStatus.AUTHOR_MISMATCH,
                mod_info=res,
                error=res.get('reason'),
            )
        if status == STATUS_RATE_LIMITED:
            lang = getattr(self.api, 'lang', 'ru')
            return TransferResult(
                jar_name=jar.name,
                status=SingleResultStatus.RATE_LIMITED,
                error=_t('rate_limited_api', lang),
            )
        return TransferResult(
            jar_name=jar.name,
            status=SingleResultStatus.NOT_FOUND,
        )

    def _download_one(
        self,
        jar: Path,
        info: Dict[str, Any],
        dst_folder: Path,
    ) -> tuple[bool, Optional[str]]:
        from ..utils import sanitize_filename, download_url_to_file
        url = info.get('download_url')
        filename = sanitize_filename(info.get('filename') or jar.name, fallback=jar.name)
        if not url or not filename:
            lang = getattr(self.api, 'lang', 'ru')
            return False, _t('no_url_or_name', lang)

        dest = dst_folder / filename
        # Remember the sanitized name so rollback tracks the real file.
        try:
            info['filename'] = filename
        except Exception:
            pass
        session = getattr(self.api, 'session', None)
        ok, err = download_url_to_file(
            url, dest,
            session=session,
            timeout=self.download_timeout,
            expected_sha1=info.get('file_sha1'),
            expected_size=info.get('file_size'),
        )
        if not ok:
            logger.error("Download of %s failed: %s", filename, err)
        return ok, err

    # -- helpers -- #

    @staticmethod
    def _replace_with_download_error(
        summary: TransferSummary,
        jar_name: str,
        err: Optional[str],
        lang: str = 'ru',
    ) -> None:
        for r in summary.results:
            if r.jar_name == jar_name and r.status == SingleResultStatus.OK:
                r.status = SingleResultStatus.DOWNLOAD_ERROR
                r.error = err or _t('download_error', lang)
                summary.ok -= 1
                summary.failed += 1
                return