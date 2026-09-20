"""Parallel name-list checking for the Search tab.

Resolving only (no download phase); reuses TransferResult/TransferSummary
so the UI code stays uniform. Blocking — call from a worker thread.
"""

import logging
import threading
from concurrent.futures import CancelledError, as_completed
from dataclasses import dataclass
from typing import Callable, List, Optional

from ..api import (
    ModrinthAPI,
    STATUS_FOUND, STATUS_NO_VERSION, STATUS_AMBIGUOUS,
    STATUS_NOT_FOUND, STATUS_AUTHOR_MISMATCH, STATUS_RATE_LIMITED,
)
from ..resolver import ModResolver
from ..localization import t as _t
from .transfer import (
    TransferResult, TransferProgress, TransferSummary,
    TransferCallbacks, SingleResultStatus, cancelable_pool,
)

logger = logging.getLogger(__name__)


class SearchCheckService:
    """Parallel mod-name checking (blocking)."""

    def __init__(
        self,
        api: ModrinthAPI,
        resolver: ModResolver,
        max_workers: int = 8,
    ):
        self.api = api
        self.resolver = resolver
        self.max_workers = max_workers

    def execute(
        self,
        mod_names: List[str],
        mc_version: str,
        loader: str,
        callbacks: Optional[TransferCallbacks] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> TransferSummary:
        callbacks = callbacks or TransferCallbacks()
        cancel_event = cancel_event or threading.Event()

        summary = TransferSummary(total=len(mod_names))
        if not mod_names:
            if callbacks.on_done:
                callbacks.on_done(summary)
            return summary

        done = 0
        with cancelable_pool(self.max_workers, cancel_event) as ex:
            futures = {
                ex.submit(self._check_one, name, mc_version, loader): name
                for name in mod_names
            }

            for fut in as_completed(futures):
                name = futures[fut]
                if cancel_event.is_set():
                    summary.cancelled = True
                    break

                try:
                    result = fut.result()
                except CancelledError:
                    continue
                except Exception as e:
                    logger.exception("Check error %s: %s", name, e)
                    result = TransferResult(
                        jar_name=name,
                        status=SingleResultStatus.READ_ERROR,
                        error=str(e),
                    )

                done += 1
                summary.add(result)

                if callbacks.on_progress:
                    callbacks.on_progress(TransferProgress(
                        done=done, total=len(mod_names),
                        current_name=name, phase='resolve',
                    ))

        if callbacks.on_done:
            callbacks.on_done(summary)
        return summary

    # -- worker -- #

    def _check_one(
        self,
        name: str,
        mc_version: str,
        loader: str,
    ) -> TransferResult:
        try:
            res = self.resolver.resolve(name, mc_version, loader)
        except Exception as e:
            logger.exception("Resolve error %s", name)
            return TransferResult(
                jar_name=name,
                status=SingleResultStatus.READ_ERROR,
                error=str(e),
            )

        status = res.get('status')
        if status == STATUS_FOUND:
            return TransferResult(jar_name=name, status=SingleResultStatus.OK, mod_info=res)
        if status == STATUS_NO_VERSION:
            return TransferResult(
                jar_name=name, status=SingleResultStatus.NO_VERSION,
                mod_info=res, error=res.get('reason'),
            )
        if status == STATUS_AMBIGUOUS:
            return TransferResult(
                jar_name=name, status=SingleResultStatus.AMBIGUOUS,
                candidates=res.get('candidates') or [],
            )
        if status == STATUS_AUTHOR_MISMATCH:
            return TransferResult(
                jar_name=name, status=SingleResultStatus.AUTHOR_MISMATCH,
                mod_info=res, error=res.get('reason'),
            )
        if status == STATUS_RATE_LIMITED:
            lang = getattr(self.api, 'lang', 'ru')
            return TransferResult(
                jar_name=name, status=SingleResultStatus.RATE_LIMITED,
                error=_t('rate_limited_api_long', lang),
            )
        return TransferResult(jar_name=name, status=SingleResultStatus.NOT_FOUND)