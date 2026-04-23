#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_SYSTEM_ROOTS: tuple[Path, ...] = (
    Path("/Library"),
    Path("/private/var/tmp"),
    Path("/private/var/db/receipts"),
    Path("/tmp"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def human_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TiB"


def expand_path(value: str | Path, home: Path) -> Path:
    text = str(value)
    if text.startswith("~"):
        return Path(text.replace("~", str(home), 1)).expanduser().resolve()
    return Path(text).expanduser().resolve()


def expand_patterns(values: Iterable[str | Path], home: Path) -> tuple[Path, ...]:
    out: list[Path] = []
    seen: set[str] = set()
    for raw in values:
        expanded = str(raw).replace("~", str(home), 1) if str(raw).startswith("~") else str(raw)
        matches = glob.glob(expanded)
        if matches:
            for match in matches:
                resolved = Path(match).expanduser().resolve()
                key = str(resolved)
                if key not in seen:
                    out.append(resolved)
                    seen.add(key)
        else:
            resolved = Path(expanded).expanduser().resolve()
            key = str(resolved)
            if key not in seen:
                out.append(resolved)
                seen.add(key)
    return tuple(out)


def walk_files(root: Path) -> Iterable[tuple[Path, os.stat_result]]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            if current.is_symlink():
                continue
            if current.is_file():
                yield current, current.stat()
                continue
            if current.is_dir():
                try:
                    with os.scandir(current) as entries:
                        for entry in entries:
                            stack.append(Path(entry.path))
                except PermissionError:
                    continue
        except FileNotFoundError:
            continue
        except PermissionError:
            continue


def file_older_than(stat_result: os.stat_result, cutoff_ts: float | None) -> bool:
    if cutoff_ts is None:
        return True
    return float(stat_result.st_mtime) <= cutoff_ts


def unique_trash_path(trash_root: Path, source: Path) -> Path:
    trash_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    token = uuid.uuid4().hex[:8]
    base = source.name or "item"
    candidate = trash_root / f"{base}.{stamp}.{token}"
    index = 1
    while candidate.exists():
        candidate = trash_root / f"{base}.{stamp}.{token}.{index}"
        index += 1
    return candidate


def move_to_trash(source: Path, home: Path) -> Path:
    trash_root = home / ".Trash"
    destination = unique_trash_path(trash_root, source)
    shutil.move(str(source), str(destination))
    return destination


def remove_path(source: Path) -> None:
    if source.is_dir() and not source.is_symlink():
        shutil.rmtree(source)
    else:
        source.unlink(missing_ok=True)


def tree_stats(root: Path, *, cutoff_ts: float | None) -> dict[str, Any]:
    total_bytes = 0
    eligible_bytes = 0
    total_files = 0
    eligible_files = 0
    newest_mtime: float | None = None
    oldest_mtime: float | None = None
    existing_paths: list[str] = []

    if not root.exists():
        return {
            "exists": False,
            "existing_paths": [],
            "total_bytes": 0,
            "eligible_bytes": 0,
            "total_files": 0,
            "eligible_files": 0,
            "newest_mtime": None,
            "oldest_mtime": None,
        }

    existing_paths.append(str(root))

    if root.is_file() or root.is_symlink():
        try:
            st = root.stat()
        except FileNotFoundError:
            return {
                "exists": False,
                "existing_paths": [],
                "total_bytes": 0,
                "eligible_bytes": 0,
                "total_files": 0,
                "eligible_files": 0,
                "newest_mtime": None,
                "oldest_mtime": None,
            }
        total_bytes += int(st.st_size)
        total_files += 1
        eligible_bytes += int(st.st_size) if file_older_than(st, cutoff_ts) else 0
        eligible_files += 1 if file_older_than(st, cutoff_ts) else 0
        newest_mtime = float(st.st_mtime)
        oldest_mtime = float(st.st_mtime)
    else:
        for file_path, st in walk_files(root):
            total_files += 1
            size = int(st.st_size)
            total_bytes += size
            newest_mtime = float(st.st_mtime) if newest_mtime is None else max(newest_mtime, float(st.st_mtime))
            oldest_mtime = float(st.st_mtime) if oldest_mtime is None else min(oldest_mtime, float(st.st_mtime))
            if file_older_than(st, cutoff_ts):
                eligible_files += 1
                eligible_bytes += size

    return {
        "exists": True,
        "existing_paths": existing_paths,
        "total_bytes": total_bytes,
        "eligible_bytes": eligible_bytes,
        "total_files": total_files,
        "eligible_files": eligible_files,
        "newest_mtime": newest_mtime,
        "oldest_mtime": oldest_mtime,
    }


def _matches_name(value: str, needles: Sequence[str]) -> bool:
    lower = value.lower()
    return any(needle and needle.lower() in lower for needle in needles)


def _read_bundle_id(app_path: Path) -> str:
    info = app_path / "Contents" / "Info.plist"
    if not info.exists():
        return ""
    try:
        with info.open("rb") as fh:
            data = plistlib.load(fh)
        return str(data.get("CFBundleIdentifier", "") or "")
    except Exception:
        return ""


def _shallow_children(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    try:
        return [Path(child.path) for child in os.scandir(root)]
    except PermissionError:
        return []


def _find_matching_children(root: Path, needles: Sequence[str]) -> list[Path]:
    matches: list[Path] = []
    if not root.exists():
        return matches
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                candidate = Path(entry.path)
                if _matches_name(candidate.name, needles):
                    matches.append(candidate)
    except PermissionError:
        pass
    return matches


def _cleanup_tree(
    roots: Sequence[Path],
    *,
    cutoff_ts: float,
    home: Path,
    dry_run: bool,
    trash: bool,
    move_whole_paths: bool,
) -> tuple[int, list[str]]:
    reclaimed = 0
    changed: list[str] = []

    def record(path: Path) -> None:
        changed.append(str(path))

    for root in roots:
        if not root.exists():
            continue

        if root.is_file() or root.is_symlink():
            try:
                stat_result = root.stat()
            except FileNotFoundError:
                continue
            if file_older_than(stat_result, cutoff_ts):
                if not dry_run:
                    reclaimed += int(stat_result.st_size)
                record(root)
                if not dry_run:
                    if trash:
                        move_to_trash(root, home)
                    else:
                        remove_path(root)
            continue

        if trash and move_whole_paths:
            # App leftovers are safest when moved as a unit if the whole tree is stale.
            tree = list(walk_files(root))
            if tree and all(file_older_than(stat_result, cutoff_ts) for _path, stat_result in tree):
                tree_reclaimed = sum(int(stat_result.st_size) for _path, stat_result in tree)
                reclaimed += tree_reclaimed
                record(root)
                if not dry_run:
                    move_to_trash(root, home)
                continue

        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            current_dir = Path(dirpath)
            for filename in filenames:
                candidate = current_dir / filename
                try:
                    stat_result = candidate.stat()
                except FileNotFoundError:
                    continue
                if not file_older_than(stat_result, cutoff_ts):
                    continue
                if not dry_run:
                    reclaimed += int(stat_result.st_size)
                record(candidate)
                if not dry_run:
                    if trash:
                        move_to_trash(candidate, home)
                    else:
                        remove_path(candidate)
            if current_dir == root:
                continue
            try:
                if not any(current_dir.iterdir()):
                    record(current_dir)
                    if not dry_run:
                        if trash:
                            move_to_trash(current_dir, home)
                        else:
                            remove_path(current_dir)
            except FileNotFoundError:
                continue
            except PermissionError:
                continue

    return reclaimed, changed


@dataclass(frozen=True)
class StorageContext:
    home: Path
    root: Path
    days_to_keep: int = 7
    dry_run: bool = True
    apply: bool = False
    yes: bool = False
    include_system: bool = False
    confirm_targets: frozenset[str] = frozenset()
    flutter_search_root: Path | None = None
    app_path: Path | None = None
    system_roots: tuple[Path, ...] = field(default_factory=lambda: DEFAULT_SYSTEM_ROOTS)


@dataclass(frozen=True)
class CleanupTarget:
    target_id: str
    name: str
    category: str
    kind: str
    paths: tuple[Path, ...] = ()
    risk: str = "low"
    recoverable: bool = True
    requires_confirmation: bool = False
    required_tools: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    dry_run_command: tuple[str, ...] = ()
    cwd: Path | None = None
    min_age_days: int = 7
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetScan:
    target: CleanupTarget
    exists: bool
    total_bytes: int
    eligible_bytes: int
    total_files: int
    eligible_files: int
    newest_mtime: float | None
    oldest_mtime: float | None
    existing_paths: tuple[str, ...] = ()
    missing_paths: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass
class PlanItem:
    target_id: str
    name: str
    category: str
    kind: str
    risk: str
    status: str
    reason: str
    estimated_bytes: int
    actual_bytes: int = 0
    paths: tuple[str, ...] = ()
    command_output: str = ""
    requires_confirmation: bool = False
    recoverable: bool = True


@dataclass
class StorageReport:
    created_at: str
    mode: str
    home: str
    root: str
    days_to_keep: int
    dry_run: bool
    apply_requested: bool
    before_free_bytes: int
    after_free_bytes: int
    before_total_bytes: int
    after_total_bytes: int
    estimated_reclaimed_bytes: int
    actual_reclaimed_bytes: int
    top_consumers: list[dict[str, Any]]
    plan_items: list[PlanItem]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "mode": self.mode,
            "home": self.home,
            "root": self.root,
            "days_to_keep": self.days_to_keep,
            "dry_run": self.dry_run,
            "apply_requested": self.apply_requested,
            "before_free_bytes": self.before_free_bytes,
            "after_free_bytes": self.after_free_bytes,
            "before_total_bytes": self.before_total_bytes,
            "after_total_bytes": self.after_total_bytes,
            "estimated_reclaimed_bytes": self.estimated_reclaimed_bytes,
            "actual_reclaimed_bytes": self.actual_reclaimed_bytes,
            "top_consumers": self.top_consumers,
            "plan_items": [plan_item_to_dict(item) for item in self.plan_items],
            "notes": list(self.notes),
        }


def plan_item_to_dict(item: PlanItem) -> dict[str, Any]:
    return {
        "target_id": item.target_id,
        "name": item.name,
        "category": item.category,
        "kind": item.kind,
        "risk": item.risk,
        "status": item.status,
        "reason": item.reason,
        "estimated_bytes": item.estimated_bytes,
        "actual_bytes": item.actual_bytes,
        "paths": list(item.paths),
        "command_output": item.command_output,
        "requires_confirmation": item.requires_confirmation,
        "recoverable": item.recoverable,
    }


class CommandRunner:
    def which(self, name: str) -> str | None:  # pragma: no cover - overridden by fake runner in tests
        return shutil.which(name)

    def run(self, args, *, capture_output=True, text=True, check=False, cwd=None):  # noqa: ANN001
        return subprocess.run(
            list(args),
            capture_output=capture_output,
            text=text,
            check=check,
            cwd=cwd,
        )


class ScanCache:
    def __init__(self) -> None:
        self._records: dict[str, TargetScan] = {}

    def get(self, target_id: str) -> TargetScan | None:
        return self._records.get(target_id)

    def store(self, scan: TargetScan) -> None:
        self._records[scan.target.target_id] = scan

    def invalidate(self, target_ids: Iterable[str]) -> None:
        for target_id in target_ids:
            self._records.pop(target_id, None)


class StorageManager:
    def __init__(self, context: StorageContext, runner: CommandRunner | None = None) -> None:
        self.context = context
        self.runner = runner or CommandRunner()
        self.cache = ScanCache()
        self._validate_static_context()

    def _validate_static_context(self) -> None:
        if self.context.days_to_keep < 0:
            raise ValueError("days_to_keep must be >= 0")

    def _validate_runtime_context(self) -> None:
        if not self.context.root.exists():
            raise FileNotFoundError(f"root not found: {self.context.root}")
        if not self.context.root.is_dir():
            raise FileNotFoundError(f"root is not a directory: {self.context.root}")
        if not self.context.home.exists():
            raise FileNotFoundError(f"home not found: {self.context.home}")

    def discover_targets(self) -> list[CleanupTarget]:
        self._validate_runtime_context()
        targets: list[CleanupTarget] = []
        home = self.context.home
        keep_days = self.context.days_to_keep

        def add(
            target_id: str,
            name: str,
            category: str,
            kind: str,
            raw_paths: Iterable[str | Path],
            *,
            risk: str = "low",
            recoverable: bool = True,
            requires_confirmation: bool = False,
            required_tools: tuple[str, ...] = (),
            command: tuple[str, ...] = (),
            dry_run_command: tuple[str, ...] = (),
            cwd: Path | None = None,
            min_age_days: int = keep_days,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            paths = expand_patterns(raw_paths, home)
            targets.append(
                CleanupTarget(
                    target_id=target_id,
                    name=name,
                    category=category,
                    kind=kind,
                    paths=paths,
                    risk=risk,
                    recoverable=recoverable,
                    requires_confirmation=requires_confirmation,
                    required_tools=required_tools,
                    command=command,
                    dry_run_command=dry_run_command,
                    cwd=cwd,
                    min_age_days=min_age_days,
                    metadata=metadata or {},
                )
            )

        add(
            "home-caches",
            "Home caches",
            "cache",
            "purge_tree",
            [home / "Library" / "Caches"],
        )
        add(
            "home-logs",
            "Home logs",
            "logs",
            "purge_tree",
            [home / "Library" / "Logs"],
        )
        add(
            "xcode-derived-data",
            "Xcode DerivedData",
            "xcode",
            "purge_tree",
            [home / "Library" / "Developer" / "Xcode" / "DerivedData"],
        )
        add(
            "xcode-archives",
            "Xcode Archives",
            "xcode",
            "purge_tree",
            [home / "Library" / "Developer" / "Xcode" / "Archives"],
        )
        add(
            "xcode-device-support",
            "Xcode Device Support",
            "xcode",
            "purge_tree",
            [home / "Library" / "Developer" / "Xcode" / "iOS DeviceSupport"],
        )
        add(
            "simctl-delete-unavailable",
            "CoreSimulator devices",
            "xcode",
            "command",
            [home / "Library" / "Developer" / "CoreSimulator" / "Devices"],
            required_tools=("xcrun",),
            command=("xcrun", "simctl", "delete", "unavailable"),
            dry_run_command=("xcrun", "simctl", "list", "devices"),
            metadata={"command_label": "xcrun simctl delete unavailable"},
        )
        add(
            "playwright-cache",
            "Playwright cache",
            "browser-cache",
            "purge_tree",
            [home / "Library" / "Caches" / "ms-playwright"],
        )
        add(
            "npm-cache",
            "npm cache",
            "package-cache",
            "purge_tree",
            [home / ".npm" / "_cacache"],
        )
        add(
            "pnpm-store",
            "pnpm store",
            "package-cache",
            "purge_tree",
            [home / ".pnpm-store"],
        )
        add(
            "pip-cache",
            "pip cache",
            "package-cache",
            "purge_tree",
            [home / "Library" / "Caches" / "pip"],
        )
        add(
            "gradle-cache",
            "Gradle cache",
            "android",
            "purge_tree",
            [home / ".gradle" / "caches", home / ".gradle" / "daemon"],
        )
        add(
            "cocoapods-cache",
            "CocoaPods cache",
            "ios",
            "purge_tree",
            [home / ".cocoapods" / "repos", home / "Library" / "Caches" / "CocoaPods"],
        )
        add(
            "vscode-cache",
            "VS Code cache",
            "ide",
            "purge_tree",
            [
                home / "Library" / "Application Support" / "Code" / "Cache",
                home / "Library" / "Application Support" / "Code" / "CachedData",
                home / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage",
            ],
        )
        add(
            "jetbrains-cache",
            "JetBrains cache",
            "ide",
            "purge_tree",
            [home / "Library" / "Caches" / "JetBrains"],
        )
        add(
            "homebrew-cache",
            "Homebrew cache",
            "homebrew",
            "purge_tree",
            [home / "Library" / "Caches" / "Homebrew", home / "Library" / "Caches" / "Homebrew" / "downloads"],
        )
        add(
            "brew-cleanup",
            "Homebrew cleanup",
            "homebrew",
            "command",
            [home / "Library" / "Caches" / "Homebrew"],
            required_tools=("brew",),
            command=("brew", "cleanup", "--prune", str(self.context.days_to_keep)),
            dry_run_command=("brew", "cleanup", "--dry-run", "--prune", str(self.context.days_to_keep)),
            metadata={"command_label": "brew cleanup"},
        )
        add(
            "docker-prune",
            "Docker prune",
            "docker",
            "command",
            [home / "Library" / "Containers" / "com.docker.docker", home / "Library" / "Group Containers" / "group.com.docker"],
            risk="high",
            recoverable=False,
            requires_confirmation=True,
            required_tools=("docker",),
            command=("docker", "system", "prune", "-f"),
            dry_run_command=("docker", "system", "df"),
            metadata={"command_label": "docker system prune -f"},
        )
        add(
            "trash",
            "Trash",
            "user-files",
            "trash_tree",
            [home / ".Trash"],
            risk="medium",
            requires_confirmation=True,
        )
        add(
            "downloads",
            "Downloads",
            "user-files",
            "trash_tree",
            [home / "Downloads"],
            risk="high",
            requires_confirmation=True,
        )
        add(
            "flutter-cleanup-root",
            "Flutter cache cleanup",
            "flutter",
            "command",
            [],
            required_tools=("flutter",),
            command=("flutter", "clean"),
            dry_run_command=("flutter", "--version"),
            metadata={"command_label": "flutter clean"},
        )

        if self.context.include_system:
            add(
                "system-caches",
                "System caches",
                "system",
                "purge_tree",
                [self.context.system_roots[0]],
                risk="high",
                recoverable=False,
                requires_confirmation=True,
            )
            add(
                "system-logs",
                "System logs",
                "system",
                "purge_tree",
                [self.context.system_roots[1]],
                risk="high",
                recoverable=False,
                requires_confirmation=True,
            )
            add(
                "system-tmp",
                "System temp",
                "system",
                "purge_tree",
                [self.context.system_roots[2], self.context.system_roots[3]],
                risk="high",
                recoverable=False,
                requires_confirmation=True,
            )

        targets.extend(self._discover_flutter_targets())
        targets.extend(self._discover_app_leftovers_targets())

        return targets

    def _discover_flutter_targets(self) -> list[CleanupTarget]:
        root = self.context.flutter_search_root or self.context.root
        if not root.exists():
            return []

        targets: list[CleanupTarget] = []
        seen: set[str] = set()
        for pubspec in sorted(root.rglob("pubspec.yaml")):
            parts = set(pubspec.parts)
            if ".git" in parts or "node_modules" in parts:
                continue
            project_root = pubspec.parent
            target_id = f"flutter-cleanup:{project_root.name}"
            if target_id in seen:
                continue
            seen.add(target_id)
            paths = (
                project_root / "build",
                project_root / ".dart_tool",
                project_root / ".packages",
                project_root / "pubspec.lock",
                project_root / ".fvm",
                project_root / ".fvmrc",
                project_root / "android" / "build",
                project_root / "android" / ".gradle",
                project_root / "android" / "app" / "build",
                project_root / "ios" / "Pods",
                project_root / "ios" / "Podfile.lock",
                project_root / "ios" / ".symlinks",
                project_root / "ios" / "Flutter" / "Flutter.framework",
                project_root / "ios" / "Flutter" / "Flutter.podspec",
            )
            targets.append(
                CleanupTarget(
                    target_id=target_id,
                    name=f"Flutter cleanup ({project_root.name})",
                    category="flutter",
                    kind="flutter_project",
                    paths=tuple(path.resolve() for path in paths),
                    risk="low",
                    recoverable=True,
                    requires_confirmation=False,
                    required_tools=("flutter",),
                    command=("flutter", "clean"),
                    dry_run_command=("flutter", "--version"),
                    cwd=project_root,
                    min_age_days=self.context.days_to_keep,
                    metadata={"project_root": str(project_root)},
                )
            )
        return targets

    def _discover_app_leftovers_targets(self) -> list[CleanupTarget]:
        app_path = self.context.app_path
        if not app_path:
            return []
        app_path = app_path.resolve()
        bundle_id = _read_bundle_id(app_path)
        app_name = app_path.stem.removesuffix(".app") or app_path.stem
        needles = [app_name, bundle_id] if bundle_id else [app_name]
        search_roots = [
            self.context.home / "Library" / "Application Scripts",
            self.context.home / "Library" / "Application Support",
            self.context.home / "Library" / "Containers",
            self.context.home / "Library" / "Group Containers",
            self.context.home / "Library" / "Caches",
            self.context.home / "Library" / "HTTPStorages",
            self.context.home / "Library" / "Preferences",
            self.context.home / "Library" / "Preferences" / "ByHost",
            self.context.home / "Library" / "Saved Application State",
            self.context.home / "Library" / "WebKit",
            *self.context.system_roots,
        ]

        matches: list[Path] = [app_path]
        for root in search_roots:
            if not root.exists():
                continue
            if root.name == "receipts":
                try:
                    for entry in root.iterdir():
                        if _matches_name(entry.name, needles):
                            matches.append(entry.resolve())
                except PermissionError:
                    continue
                continue
            matches.extend(_find_matching_children(root, needles))

        unique_matches: list[Path] = []
        seen: set[str] = set()
        for path in matches:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique_matches.append(path)

        if len(unique_matches) <= 1:
            return []

        return [
            CleanupTarget(
                target_id=f"app-leftovers:{app_name}",
                name=f"App leftovers ({app_name})",
                category="app-leftovers",
                kind="trash_tree",
                paths=tuple(unique_matches),
                risk="high",
                recoverable=True,
                requires_confirmation=True,
                metadata={
                    "bundle_id": bundle_id,
                    "app_name": app_name,
                    "move_whole_paths": True,
                },
            )
        ]

    def scan_targets(self, targets: Sequence[CleanupTarget]) -> list[TargetScan]:
        out: list[TargetScan] = []
        cutoff_ts = time.time() - max(0, self.context.days_to_keep) * 24 * 60 * 60
        for target in targets:
            cached = self.cache.get(target.target_id)
            if cached is not None:
                out.append(cached)
                continue
            existing_paths: list[str] = []
            missing_paths: list[str] = []
            total_bytes = 0
            eligible_bytes = 0
            total_files = 0
            eligible_files = 0
            newest_mtime: float | None = None
            oldest_mtime: float | None = None
            exists = False

            for path in target.paths:
                if not path.exists():
                    missing_paths.append(str(path))
                    continue
                exists = True
                existing_paths.append(str(path))
                stats = tree_stats(path, cutoff_ts=cutoff_ts if target.kind != "command" else None)
                total_bytes += int(stats["total_bytes"])
                eligible_bytes += int(stats["eligible_bytes"])
                total_files += int(stats["total_files"])
                eligible_files += int(stats["eligible_files"])
                if stats["newest_mtime"] is not None:
                    newest_mtime = float(stats["newest_mtime"]) if newest_mtime is None else max(newest_mtime, float(stats["newest_mtime"]))
                if stats["oldest_mtime"] is not None:
                    oldest_mtime = float(stats["oldest_mtime"]) if oldest_mtime is None else min(oldest_mtime, float(stats["oldest_mtime"]))

            scan = TargetScan(
                target=target,
                exists=exists,
                total_bytes=total_bytes,
                eligible_bytes=eligible_bytes if target.kind != "command" else total_bytes,
                total_files=total_files,
                eligible_files=eligible_files if target.kind != "command" else total_files,
                newest_mtime=newest_mtime,
                oldest_mtime=oldest_mtime,
                existing_paths=tuple(existing_paths),
                missing_paths=tuple(missing_paths),
            )
            self.cache.store(scan)
            out.append(scan)
        return out

    def plan_targets(self, scans: Sequence[TargetScan]) -> list[PlanItem]:
        out: list[PlanItem] = []
        for scan in scans:
            target = scan.target
            reason = ""
            status = "planned"
            estimated = scan.eligible_bytes

            if not scan.exists:
                status = "skipped"
                reason = "target path missing"
            elif target.required_tools and any(self.runner.which(tool) is None for tool in target.required_tools):
                status = "skipped"
                reason = f"missing tool: {', '.join(tool for tool in target.required_tools if self.runner.which(tool) is None)}"
            elif target.target_id == "docker-prune" and not self._docker_context_is_local():
                status = "skipped"
                reason = "docker context is remote"
            elif target.requires_confirmation and not self._is_confirmed(target):
                status = "blocked"
                reason = "explicit confirmation required"
            elif estimated <= 0 and target.kind != "command":
                status = "empty"
                reason = "nothing eligible to clean"
            elif self.context.dry_run or not self.context.apply:
                status = "planned"
                reason = "dry-run"
            else:
                status = "ready"
                reason = "eligible for cleanup"

            out.append(
                PlanItem(
                    target_id=target.target_id,
                    name=target.name,
                    category=target.category,
                    kind=target.kind,
                    risk=target.risk,
                    status=status,
                    reason=reason,
                    estimated_bytes=estimated,
                    paths=scan.existing_paths,
                    requires_confirmation=target.requires_confirmation,
                    recoverable=target.recoverable,
                )
            )
        return out

    def _is_confirmed(self, target: CleanupTarget) -> bool:
        if self.context.yes:
            return True
        return target.target_id in self.context.confirm_targets or target.category in self.context.confirm_targets

    def _docker_context_is_local(self) -> bool:
        if self.runner.which("docker") is None:
            return False
        show = self.runner.run(["docker", "context", "show"])
        if show.returncode != 0:
            return False
        context_name = (show.stdout or "").strip()
        if not context_name:
            return False
        inspect = self.runner.run(["docker", "context", "inspect", context_name, "--format", "{{.Endpoints.docker.Host}}"])
        if inspect.returncode != 0:
            return False
        host = (inspect.stdout or "").strip()
        return host.startswith("unix://") or host.startswith("npipe://")

    def _execute_command(self, target: CleanupTarget) -> tuple[int, str]:
        if self.context.dry_run or not self.context.apply:
            cmd = target.dry_run_command or target.command
            if not cmd:
                return 0, ""
            return 0, "dry-run"
        cmd = target.command
        if not cmd:
            return 0, ""
        proc = self.runner.run(list(cmd), cwd=str(target.cwd) if target.cwd else None)
        output = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return 0, output or f"command failed ({proc.returncode})"
        return 0, output

    def _execute_filesystem_target(self, target: CleanupTarget) -> tuple[int, list[str]]:
        cutoff_ts = time.time() - max(0, self.context.days_to_keep) * 24 * 60 * 60
        trash = target.kind == "trash_tree"
        move_whole_paths = bool(target.metadata.get("move_whole_paths"))
        return _cleanup_tree(
            target.paths,
            cutoff_ts=cutoff_ts,
            home=self.context.home,
            dry_run=self.context.dry_run or not self.context.apply,
            trash=trash,
            move_whole_paths=move_whole_paths,
        )

    def execute(self, scans: Sequence[TargetScan], plan_items: list[PlanItem]) -> tuple[list[PlanItem], int]:
        actual_reclaimed = 0
        items_by_id = {item.target_id: item for item in plan_items}
        changed_targets: set[str] = set()
        should_apply = not (self.context.dry_run or not self.context.apply)

        for scan in scans:
            target = scan.target
            item = items_by_id[target.target_id]
            if item.status not in {"ready", "planned"}:
                continue

            if target.kind == "command":
                reclaimed, output = self._execute_command(target)
                item.command_output = output
                if not should_apply:
                    item.status = "planned"
                    item.reason = "dry-run"
                else:
                    if target.target_id == "docker-prune" and not self._docker_context_is_local():
                        item.status = "skipped"
                        item.reason = "docker context is remote"
                    elif target.required_tools and any(self.runner.which(tool) is None for tool in target.required_tools):
                        item.status = "skipped"
                        item.reason = "missing required tool"
                    elif output.startswith("command failed"):
                        item.status = "failed"
                        item.reason = output
                    else:
                        item.status = "cleaned"
                        item.reason = "command completed"
                if should_apply:
                    actual_reclaimed += reclaimed
                    changed_targets.add(target.target_id)
                continue

            if target.kind == "flutter_project":
                if self.runner.which("flutter") is None:
                    item.status = "skipped"
                    item.reason = "missing tool: flutter"
                    continue
                if should_apply:
                    proc = self.runner.run(list(target.command), cwd=str(target.cwd) if target.cwd else None)
                    item.command_output = (proc.stdout or "").strip()
                    if proc.returncode != 0:
                        item.reason = f"flutter clean failed ({proc.returncode})"
                        item.status = "failed"
                reclaimed, changed = self._execute_filesystem_target(
                    CleanupTarget(
                        target_id=target.target_id,
                        name=target.name,
                        category=target.category,
                        kind="purge_tree",
                        paths=target.paths,
                        risk=target.risk,
                        recoverable=target.recoverable,
                        requires_confirmation=target.requires_confirmation,
                        metadata=target.metadata,
                        min_age_days=target.min_age_days,
                    )
                )
                actual_reclaimed += reclaimed
                if should_apply:
                    changed_targets.add(target.target_id)
                if item.status not in {"failed"}:
                    item.status = "cleaned" if should_apply else "planned"
                    item.reason = "flutter project cleaned" if should_apply else "dry-run"
                continue

            reclaimed, changed = self._execute_filesystem_target(target)
            actual_reclaimed += reclaimed
            if should_apply and changed:
                changed_targets.add(target.target_id)
            if not should_apply:
                item.status = "planned"
                item.reason = "dry-run"
            else:
                item.status = "cleaned" if reclaimed > 0 or target.paths else "cleaned"
                item.reason = "cleaned"

        self.cache.invalidate(changed_targets)
        return plan_items, actual_reclaimed

    def _build_top_consumers(self, scans: Sequence[TargetScan]) -> list[dict[str, Any]]:
        ordered = sorted(scans, key=lambda scan: (scan.eligible_bytes, scan.total_bytes), reverse=True)
        out: list[dict[str, Any]] = []
        for scan in ordered:
            out.append(
                {
                    "target_id": scan.target.target_id,
                    "name": scan.target.name,
                    "category": scan.target.category,
                    "kind": scan.target.kind,
                    "risk": scan.target.risk,
                    "status": "missing" if not scan.exists else "present",
                    "total_bytes": scan.total_bytes,
                    "eligible_bytes": scan.eligible_bytes,
                    "paths": list(scan.existing_paths),
                    "notes": list(scan.notes),
                }
            )
        return out

    def _make_report(
        self,
        *,
        mode: str,
        before_scans: Sequence[TargetScan],
        after_scans: Sequence[TargetScan],
        plan_items: list[PlanItem],
        actual_reclaimed_bytes: int,
        before_free_bytes: int,
        after_free_bytes: int,
        notes: list[str],
    ) -> StorageReport:
        before_total_bytes = sum(scan.total_bytes for scan in before_scans)
        after_total_bytes = sum(scan.total_bytes for scan in after_scans)
        estimated_reclaimed_bytes = sum(item.estimated_bytes for item in plan_items if item.status in {"planned", "ready", "cleaned"})
        return StorageReport(
            created_at=now_iso(),
            mode=mode,
            home=str(self.context.home),
            root=str(self.context.root),
            days_to_keep=self.context.days_to_keep,
            dry_run=self.context.dry_run or not self.context.apply,
            apply_requested=self.context.apply,
            before_free_bytes=before_free_bytes,
            after_free_bytes=after_free_bytes,
            before_total_bytes=before_total_bytes,
            after_total_bytes=after_total_bytes,
            estimated_reclaimed_bytes=estimated_reclaimed_bytes,
            actual_reclaimed_bytes=actual_reclaimed_bytes,
            top_consumers=self._build_top_consumers(before_scans),
            plan_items=plan_items,
            notes=notes,
        )

    def audit(self) -> StorageReport:
        targets = self.discover_targets()
        before_scans = self.scan_targets(targets)
        plan_items = self.plan_targets(before_scans)
        free_bytes = shutil.disk_usage(self.context.root).free
        return self._make_report(
            mode="audit",
            before_scans=before_scans,
            after_scans=before_scans,
            plan_items=plan_items,
            actual_reclaimed_bytes=0,
            before_free_bytes=free_bytes,
            after_free_bytes=free_bytes,
            notes=self._collect_notes(plan_items, before_scans),
        )

    def plan(self) -> StorageReport:
        return self.audit()

    def clean(self) -> StorageReport:
        targets = self.discover_targets()
        before_scans = self.scan_targets(targets)
        plan_items = self.plan_targets(before_scans)
        before_free = shutil.disk_usage(self.context.root).free
        plan_items, reclaimed = self.execute(before_scans, plan_items)
        after_scans = self.scan_targets(targets)
        after_free = shutil.disk_usage(self.context.root).free
        return self._make_report(
            mode="clean",
            before_scans=before_scans,
            after_scans=after_scans,
            plan_items=plan_items,
            actual_reclaimed_bytes=reclaimed,
            before_free_bytes=before_free,
            after_free_bytes=after_free,
            notes=self._collect_notes(plan_items, after_scans),
        )

    def _collect_notes(self, plan_items: Sequence[PlanItem], scans: Sequence[TargetScan]) -> list[str]:
        notes: list[str] = []
        for item in plan_items:
            if item.status == "skipped":
                notes.append(f"{item.target_id}: {item.reason}")
            elif item.status == "blocked":
                notes.append(f"{item.target_id}: {item.reason}")
            elif item.status == "failed":
                notes.append(f"{item.target_id}: {item.reason}")
        for scan in scans:
            if not scan.exists:
                notes.append(f"{scan.target.target_id}: target path missing")
        return notes


def render_markdown(report: StorageReport) -> str:
    lines = [
        "# macOS Storage Report",
        "",
        "## Summary",
        f"- Mode: {report.mode}",
        f"- Free before: {human_bytes(report.before_free_bytes)}",
        f"- Free after: {human_bytes(report.after_free_bytes)}",
        f"- Estimated reclaimed: {human_bytes(report.estimated_reclaimed_bytes)}",
        f"- Actual reclaimed: {human_bytes(report.actual_reclaimed_bytes)}",
        "",
        "## Top Consumers",
    ]
    for index, item in enumerate(report.top_consumers[:5], start=1):
        lines.append(
            f"{index}. {item['name']} ({item['target_id']}) - {human_bytes(int(item['eligible_bytes']))} reclaimable"
        )
    if not report.top_consumers:
        lines.append("1. None")
    lines.extend(
        [
            "",
            "## Cleaned / Planned",
        ]
    )
    for item in report.plan_items:
        lines.append(f"- `{item.target_id}` [{item.status}] {item.reason}")
    lines.extend(
        [
            "",
            "## Remaining Hotspots",
        ]
    )
    remaining = [item for item in report.top_consumers if int(item["eligible_bytes"]) > 0]
    if remaining:
        for item in remaining[:5]:
            lines.append(f"- {item['name']}: {human_bytes(int(item['eligible_bytes']))}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Next Step Options",
            "1. Re-run with `--apply --yes` after reviewing blocked targets.",
            "2. Narrow the scan with `--flutter-search-root` or `--app-path` for focused cleanup.",
        ]
    )
    return "\n".join(lines)


def render_text(report: StorageReport) -> str:
    lines = [
        f"Root conclusion: {human_bytes(report.actual_reclaimed_bytes)} reclaimed, {human_bytes(report.estimated_reclaimed_bytes)} estimated.",
        f"Actions taken: {sum(1 for item in report.plan_items if item.status == 'cleaned')} cleaned, {sum(1 for item in report.plan_items if item.status == 'blocked')} blocked, {sum(1 for item in report.plan_items if item.status == 'skipped')} skipped.",
        f"Verification status: {'dry-run' if report.dry_run else 'applied'}.",
        f"Free space: {human_bytes(report.before_free_bytes)} -> {human_bytes(report.after_free_bytes)}.",
        "Next safe step: inspect remaining hotspots or re-run with explicit confirmation for risky targets.",
    ]
    return "\n".join(lines)


def _parse_csv(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return frozenset(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit and clean macOS storage safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--home", default=str(Path.home()))
        p.add_argument("--root", default="")
        p.add_argument("--days-to-keep", type=int, default=7)
        p.add_argument("--confirm-targets", default="")
        p.add_argument("--flutter-search-root", default="")
        p.add_argument("--app-path", default="")
        p.add_argument("--include-system", action="store_true")
        p.add_argument("--json", action="store_true")
        p.add_argument("--markdown", action="store_true")

    audit = sub.add_parser("audit", help="Scan and report without changing files")
    add_common(audit)
    audit.add_argument("--topk", type=int, default=5)

    plan = sub.add_parser("plan", help="Build a cleanup plan without changing files")
    add_common(plan)
    plan.add_argument("--topk", type=int, default=5)

    clean = sub.add_parser("clean", help="Run the plan and clean eligible targets")
    add_common(clean)
    clean.add_argument("--apply", action="store_true")
    clean.add_argument("--yes", action="store_true")
    clean.add_argument("--dry-run", action="store_true")
    clean.add_argument("--topk", type=int, default=5)
    return parser


def _context_from_args(args: argparse.Namespace) -> StorageContext:
    home = Path(args.home).expanduser().resolve()
    root = Path(args.root).expanduser().resolve() if args.root else home
    flutter_root = Path(args.flutter_search_root).expanduser().resolve() if args.flutter_search_root else None
    app_path = Path(args.app_path).expanduser().resolve() if args.app_path else None
    return StorageContext(
        home=home,
        root=root,
        days_to_keep=int(args.days_to_keep),
        dry_run=bool(getattr(args, "dry_run", False) or args.command in {"audit", "plan"}),
        apply=bool(getattr(args, "apply", False)),
        yes=bool(getattr(args, "yes", False)),
        include_system=bool(args.include_system),
        confirm_targets=_parse_csv(args.confirm_targets),
        flutter_search_root=flutter_root,
        app_path=app_path,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = _context_from_args(args)
    manager = StorageManager(ctx)

    if args.command == "audit":
        report = manager.audit()
    elif args.command == "plan":
        report = manager.plan()
    else:
        report = manager.clean() if ctx.apply and not ctx.dry_run else manager.audit()

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif getattr(args, "markdown", False):
        print(render_markdown(report))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
