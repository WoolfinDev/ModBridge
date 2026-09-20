"""One-click rollback backups for profile transfers.

Snapshots exactly what a transfer may overwrite in the target profile.
Policies: name intersection for mods/resourcepacks/shaderpacks/screenshots
(and anything unknown), full copy for config/schematics/xaero/options.txt,
skip for saves. Layout: <root>/<profile>_<timestamp>/{manifest.json,files/}.
"""

import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..utils import get_modrinth_profiles_path

logger = logging.getLogger(__name__)


def _safe_join(base: Path, rel: str) -> Optional[Path]:
    """Join base with a relative path, refusing escapes via ../..

    A tampered manifest must not delete/overwrite files outside the
    target profile or the backup folder.
    """
    try:
        target = (base / rel).resolve()
        if target.is_relative_to(base.resolve()):
            return target
    except Exception as e:
        logger.debug("Bad relative path %r: %s", rel, e)
        return None
    logger.warning("Rejected out-of-base path: %r", rel)
    return None


# Backup policies: whole item, name intersection, or skip.
BACKUP_FULL = "full"
BACKUP_INTERSECTION = "intersection"
BACKUP_SKIP = "skip"


DEFAULT_POLICY: Dict[str, str] = {
    "mods": BACKUP_INTERSECTION,
    "resourcepacks": BACKUP_INTERSECTION,
    "shaderpacks": BACKUP_INTERSECTION,
    "screenshots": BACKUP_INTERSECTION,
    "config": BACKUP_FULL,
    "schematics": BACKUP_FULL,
    "xaero": BACKUP_FULL,
    "options.txt": BACKUP_FULL,
    "saves": BACKUP_SKIP,
}


# How many recent backups to keep (older ones are pruned automatically).
MAX_BACKUPS_TO_KEEP = 5


def _get_default_backup_root() -> Path:
    """Backup root: <app>/.transfer_backups if writable, else the OS data dir."""
    if getattr(sys, 'frozen', False):
        app_path = Path(sys.executable).parent
    else:
        app_path = Path(__file__).parent.parent.parent  # modrinth_app/services/backup.py -> project root

    candidate = app_path / ".transfer_backups"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        test_file = candidate / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return candidate
    except Exception as e:
        logger.debug("App dir not writable for backups (%s), using fallback", e)

    if sys.platform == 'win32':
        base = Path(os.getenv('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.getenv('XDG_DATA_HOME', Path.home() / '.local' / 'share'))

    fallback = base / 'ModBridge' / 'backups'
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


@dataclass
class BackupItem:
    name: str
    policy: str
    backed_up: List[str] = field(default_factory=list)
    new_files: List[str] = field(default_factory=list)


@dataclass
class BackupManifest:
    timestamp: str
    source_profile: str
    target_profile: str
    target_profile_path: str
    mc_version: str
    loader: str
    items: Dict[str, BackupItem] = field(default_factory=dict)


class BackupManager:
    """Creates backups (prepare) and rolls them back (restore)."""

    def __init__(self, backup_root: Optional[Path] = None):
        self.backup_root = backup_root or _get_default_backup_root()
        self.backup_root.mkdir(parents=True, exist_ok=True)

    # -- backup creation -- #

    def prepare(
        self,
        src_profile_path: Path,
        src_profile_name: str,
        target_profile_path: Path,
        target_profile_name: str,
        items_to_transfer: List[str],
        mc_version: str,
        loader: str,
    ) -> Path:
        """Back up the target profile; return the backup dir path."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_dir = self.backup_root / f"{target_profile_name}_{timestamp}"
        files_dir = backup_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        manifest = BackupManifest(
            timestamp=timestamp,
            source_profile=src_profile_name,
            target_profile=target_profile_name,
            target_profile_path=str(target_profile_path),
            mc_version=mc_version,
            loader=loader,
        )

        for item_name in items_to_transfer:
            policy = DEFAULT_POLICY.get(item_name, BACKUP_INTERSECTION)
            if policy == BACKUP_SKIP:
                logger.info("Backup: %s skipped (policy=skip)", item_name)
                continue

            item = BackupItem(name=item_name, policy=policy)
            manifest.items[item_name] = item

            src_item = src_profile_path / item_name
            dst_item = target_profile_path / item_name

            if not dst_item.exists():
                # Nothing to back up; rollback will just delete added files.
                logger.info("Backup: %s absent in target profile, skipping", item_name)
                continue

            if policy == BACKUP_FULL:
                self._backup_full(dst_item, files_dir, item_name, item)
            else:
                self._backup_intersection(src_item, dst_item, files_dir, item_name, item)

        (backup_dir / "manifest.json").write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._prune_old_backups()

        logger.info("Backup created: %s", backup_dir)
        return backup_dir

    # -- internals -- #

    def _backup_full(
        self,
        dst_item: Path,
        files_dir: Path,
        item_name: str,
        item: BackupItem,
    ) -> None:
        """Back up a folder/file in full."""
        dest = files_dir / item_name
        try:
            if dst_item.is_dir():
                shutil.copytree(dst_item, dest, dirs_exist_ok=True)
                for p in dest.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(files_dir).as_posix()
                        item.backed_up.append(rel)
            elif dst_item.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst_item, dest)
                item.backed_up.append(item_name)
            logger.info("Backup: %s (full) → %s", item_name, dest)
        except Exception as e:
            logger.error("Backup error %s (full): %s", item_name, e)

    def _backup_intersection(
        self,
        src_item: Path,
        dst_item: Path,
        files_dir: Path,
        item_name: str,
        item: BackupItem,
    ) -> None:
        """Back up only target files shadowed by same-name source files."""
        if not dst_item.is_dir() or not src_item.is_dir():
            if dst_item.is_file():
                dest = files_dir / item_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst_item, dest)
                item.backed_up.append(item_name)
            return

        src_files = set()
        try:
            for p in src_item.rglob("*"):
                if p.is_file():
                    src_files.add(p.relative_to(src_item).as_posix())
        except Exception as e:
            logger.error("Walk error %s: %s", src_item, e)
            return

        for p in dst_item.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(dst_item).as_posix()
            except ValueError:
                continue
            if rel in src_files:
                dest = files_dir / item_name / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(p, dest)
                    item.backed_up.append(f"{item_name}/{rel}")
                except Exception as e:
                    logger.error("Copy error %s: %s", p, e)

        logger.info(
            "Backup: %s (intersection) — %d files saved",
            item_name, len(item.backed_up),
        )

    # -- restore -- #

    @staticmethod
    def _locate_moved_profile(data: Dict, stored: Path) -> Optional[Path]:
        """Find the target profile by name if the manifest path is gone."""
        name = data.get("target_profile") or ""
        if not name:
            return None
        try:
            profiles_root = get_modrinth_profiles_path()
        except Exception as e:
            logger.debug("Failed to locate profiles dir: %s", e)
            return None
        if not profiles_root:
            return None
        candidate = profiles_root / name
        if candidate.exists():
            logger.info(
                "Profile %r not found at manifest path (%s), using: %s",
                name, stored, candidate,
            )
            return candidate
        return None

    def restore(self, backup_dir: Path) -> bool:
        """Restore the target profile from a backup; True on success."""
        manifest_path = backup_dir / "manifest.json"
        if not manifest_path.exists():
            logger.error("Manifest not found: %s", manifest_path)
            return False

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Cannot read manifest: %s", e)
            return False

        stored_path = data.get("target_profile_path") or ""
        target_profile = Path(stored_path)
        files_dir = backup_dir / "files"

        if not stored_path or not target_profile.exists():
            # The profile may have moved (another PC): look it up by name.
            target_profile = self._locate_moved_profile(data, target_profile)
            if target_profile is None:
                logger.error("Target profile not found: %s", stored_path or "<?>")
                return False

        logger.info("Rollback: %s → %s", backup_dir.name, target_profile)

        # 1. Remove everything the transfer added.
        for item_name, item_data in data.get("items", {}).items():
            for rel in item_data.get("new_files", []):
                target = _safe_join(target_profile, rel)
                if target is None:
                    continue
                try:
                    if target.is_file():
                        target.unlink()
                        logger.info("Removed: %s", rel)
                    elif target.is_dir():
                        shutil.rmtree(target)
                        logger.info("Removed dir: %s", rel)
                except Exception as e:
                    logger.error("Failed to remove %s: %s", rel, e)

        # 2. Restore overwritten files from the backup.
        for item_name, item_data in data.get("items", {}).items():
            for rel in item_data.get("backed_up", []):
                src = _safe_join(files_dir, rel)
                dst = _safe_join(target_profile, rel)
                if src is None or dst is None:
                    continue
                if not src.exists():
                    logger.warning("Missing in backup: %s", rel)
                    continue
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                    logger.info("Restored: %s", rel)
                except Exception as e:
                    logger.error("Failed to restore %s: %s", rel, e)

        logger.info("Rollback done: %s", backup_dir.name)
        return True

    # -- old backup rotation -- #

    def _prune_old_backups(self) -> None:
        """Keep only the MAX_BACKUPS_TO_KEEP newest backups."""
        try:
            dirs = sorted(
                [d for d in self.backup_root.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            for old in dirs[MAX_BACKUPS_TO_KEEP:]:
                try:
                    shutil.rmtree(old)
                    logger.info("Pruned old backup: %s", old.name)
                except Exception as e:
                    logger.error("Failed to remove %s: %s", old, e)
        except Exception as e:
            logger.error("Backup cleanup error: %s", e)

    def list_backups(self) -> List[Path]:
        """Backups sorted by time (newest first)."""
        try:
            return sorted(
                [d for d in self.backup_root.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return []