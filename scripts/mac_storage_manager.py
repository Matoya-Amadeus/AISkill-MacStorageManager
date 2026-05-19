#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import plistlib
import re
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

DEFAULT_PUBLIC_ROOTS: tuple[Path, ...] = (
    Path("/Applications"),
    Path("/Library"),
    Path("/System"),
    Path("/private/var/db/receipts"),
    Path("/private/var/tmp"),
    Path("/tmp"),
)

SOURCE_LAYERS = {
    "active_trigger",
    "runtime_artifact",
    "repo_reference",
    "historical_index",
    "user_data",
    "protected_session",
}
PROTECTIONS = {"normal", "exact_confirm", "approved_plan", "blocked"}
ROLLBACK_STRATEGIES = {"none", "trash", "backup_manifest", "copy_backup"}
HIGH_RISK_VALUES = {"medium", "high"}
TEXT_BACKUP_SUFFIXES = {
    ".bash",
    ".command",
    ".conf",
    ".csv",
    ".ini",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".plist",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}
TRACE_TEXT_SUFFIXES = TEXT_BACKUP_SUFFIXES | {".xml", ".env", ".profile"}
TRACE_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
    "dist",
    "out",
}
SMALL_TEXT_BACKUP_BYTES = 256 * 1024
MAX_HASH_BYTES = 64 * 1024 * 1024
TRACE_MAX_FILE_BYTES = 1024 * 1024


def cleanup_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def public_display_path(path: Path, *, home: Path, root: Path, public_roots: Sequence[Path]) -> str:
    resolved = path.expanduser().resolve()
    home_resolved = home.expanduser().resolve()
    root_resolved = root.expanduser().resolve()
    public_root_paths = tuple(public_root.expanduser().resolve() for public_root in public_roots)
    if root_resolved != home_resolved and resolved == root_resolved:
        return "<root>"
    if root_resolved != home_resolved and _is_relative_to(resolved, root_resolved):
        rel = resolved.relative_to(root_resolved)
        return "<root>" if str(rel) == "." else f"<root>/{rel.as_posix()}"
    if resolved == home_resolved:
        return "~"
    if _is_relative_to(resolved, home_resolved):
        rel = resolved.relative_to(home_resolved)
        return "~" if str(rel) == "." else f"~/{rel.as_posix()}"
    for public_root in public_root_paths:
        if resolved == public_root or _is_relative_to(resolved, public_root):
            return resolved.as_posix()
    return f"<external>/{resolved.name}" if resolved.name else "<external>"


def public_text(text: str, *, home: Path, root: Path, public_roots: Sequence[Path]) -> str:
    value = str(text)
    path_candidates = sorted(
        {home.expanduser().resolve(), root.expanduser().resolve()},
        key=lambda item: len(item.as_posix()),
        reverse=True,
    )
    for candidate in path_candidates:
        raw = candidate.as_posix()
        if raw and raw in value:
            value = value.replace(raw, public_display_path(candidate, home=home, root=root, public_roots=public_roots))
    # Redact common private absolute home paths that were not equal to this test home.
    value = re.sub(r"/Users/[^\s:'\"]+", "~", value)
    # Redact remaining non-public absolute path tokens while preserving public macOS roots.
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        try:
            candidate = Path(token).expanduser().resolve()
        except Exception:
            return "<external>"
        public = public_display_path(candidate, home=home, root=root, public_roots=public_roots)
        if public.startswith("<external>"):
            return public
        return public
    return re.sub(r"(?<![A-Za-z0-9._-])/(?:[A-Za-z0-9._~.-]+(?:/[A-Za-z0-9._~.-]+)*)", repl, value)


def public_note(note: str, *, home: Path | None = None, root: Path | None = None, public_roots: Sequence[Path] = DEFAULT_PUBLIC_ROOTS) -> str:
    if note.startswith("container_bundle_id="):
        return "container_bundle_id=<redacted>"
    if note.startswith("non_owner_path="):
        return "non_owner_path=<redacted>"
    if home is not None and root is not None:
        return public_text(note, home=home, root=root, public_roots=public_roots)
    return note


def report_public_roots(context: "StorageContext") -> tuple[Path, ...]:
    seen: set[str] = set()
    roots: list[Path] = []
    for raw_root in (*DEFAULT_PUBLIC_ROOTS, *context.system_roots):
        resolved = raw_root.expanduser().resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return tuple(roots)


def _validated_choice(value: str, allowed: set[str], fallback: str) -> str:
    return value if value in allowed else fallback


def _validate_materialized_output_path(path: Path | None, label: str) -> None:
    if path is None:
        return
    text = str(path)
    if "$(" in text or "`" in text:
        raise ValueError(f"{label} must be a materialized path, not a literal shell substitution: {text}")


def _safe_relpath(path: Path, roots: Sequence[Path]) -> str:
    for root in roots:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except Exception:
            continue
    return re.sub(r"[^A-Za-z0-9._/-]+", "_", str(path.resolve()).lstrip("/"))


def _is_probably_text_file(path: Path, limit: int = 4096) -> bool:
    if path.suffix.lower() in TEXT_BACKUP_SUFFIXES:
        return True
    try:
        sample = path.read_bytes()[:limit]
    except Exception:
        return False
    return b"\0" not in sample


def _sha256_for_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _protected_session_reason(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    lower = path.as_posix().lower()
    auth_markers = {
        "cookies.sqlite",
        "logins.json",
        "key4.db",
        "sessionstore-backups",
        "session storage",
        "local storage",
        "login data",
        "cookies",
        "storage/default",
    }
    if ".ssh" in parts:
        return "ssh identity material is protected"
    if "keychains" in parts or "keychain" in lower:
        return "keychain material is protected"
    if "firefox" in parts and any(marker in lower for marker in auth_markers):
        return "Firefox browser identity/session data is protected"
    if any(browser in lower for browser in ("google/chrome", "brave browser", "microsoft edge", "safari")):
        if any(marker in lower for marker in auth_markers) and ("openai" in lower or "chatgpt" in lower):
            return "browser OpenAI/ChatGPT session data is protected"
    if ("openai" in lower or "chatgpt" in lower) and any(marker in lower for marker in auth_markers):
        return "OpenAI/ChatGPT session data is protected"
    if "application support" in lower and ("token" in lower or "session" in lower) and ("openai" in lower or "chatgpt" in lower):
        return "application token/session data is protected"
    return ""


def _first_protected_session_path(root: Path, limit: int = 500) -> tuple[Path, str] | None:
    direct_reason = _protected_session_reason(root)
    if direct_reason:
        return root, direct_reason
    if not root.exists() or root.is_file() or root.is_symlink():
        return None
    checked = 0
    for child, _st in walk_files(root):
        checked += 1
        reason = _protected_session_reason(child)
        if reason:
            return child, reason
        if checked >= limit:
            break
    return None


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


def _read_container_bundle_id(container_path: Path) -> str:
    metadata = container_path / ".com.apple.containermanagerd.metadata.plist"
    if not metadata.exists():
        return ""
    try:
        with metadata.open("rb") as fh:
            data = plistlib.load(fh)
        return str(data.get("MCMMetadataIdentifier", "") or "")
    except Exception:
        return ""


def _allocated_bytes(path: Path) -> int:
    total = 0
    try:
        if path.is_file():
            st = path.stat()
            return int(getattr(st, "st_blocks", 0) * 512) or int(st.st_size)
        for file_path, st in walk_files(path):
            total += int(getattr(st, "st_blocks", 0) * 512) or int(st.st_size)
    except Exception:
        return 0
    return total


def _find_non_owner_paths(root: Path, owner_uid: int, limit: int = 10) -> list[str]:
    mismatches: list[str] = []
    try:
        for current, st in walk_files(root):
            if int(st.st_uid) != owner_uid:
                mismatches.append(str(current))
                if len(mismatches) >= limit:
                    break
    except Exception:
        return mismatches
    return mismatches


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
                if not dry_run and not trash:
                    reclaimed += int(stat_result.st_size)
                record(root)
                if not dry_run:
                    if trash:
                        move_to_trash(root, home)
                    else:
                        remove_path(root)
            continue

        if trash and move_whole_paths:
            # High-risk approved paths are safest when moved as a whole unit.
            tree = list(walk_files(root))
            if tree or root.exists():
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
                if not dry_run and not trash:
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


def _trace_needles(target_path: Path, keyword: str) -> tuple[str, ...]:
    values = [
        keyword,
        target_path.name,
        target_path.as_posix(),
        str(target_path),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip().lower()
        if len(text) < 2 or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return tuple(out)


def _normalize_trace_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _compact_trace_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _match_text(text: str, needles: Sequence[str]) -> str:
    lower = text.lower()
    normalized = _normalize_trace_text(text)
    compact = _compact_trace_text(text)
    for needle in needles:
        if not needle:
            continue
        if needle in lower:
            return needle
        needle_norm = _normalize_trace_text(needle)
        if needle_norm and needle_norm in normalized:
            return needle
        needle_compact = _compact_trace_text(needle)
        if needle_compact and needle_compact in compact:
            return needle
    return ""


def _read_match(path: Path, needles: Sequence[str]) -> tuple[str, str] | None:
    if not path.exists() or path.is_dir():
        return None
    try:
        if path.stat().st_size > TRACE_MAX_FILE_BYTES:
            return None
    except OSError:
        return None
    if path.suffix.lower() not in TRACE_TEXT_SUFFIXES and path.name not in {"Dockerfile", ".zshrc", ".zprofile", ".bashrc", ".bash_profile", ".profile"}:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    matched = _match_text(path.name, needles) or _match_text(text, needles)
    if not matched:
        return None
    for line in text.splitlines():
        if matched in line.lower():
            return matched, line.strip()[:240]
    return matched, path.name


def _iter_trace_files(root: Path, max_files: int = 2000) -> Iterable[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    if root.is_file():
        return [root]
    count = 0
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in TRACE_SKIP_DIRS and not name.startswith(".git")]
        for filename in filenames:
            path = Path(current) / filename
            files.append(path)
            count += 1
            if count >= max_files:
                return files
    return files


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
    approved_targets: frozenset[str] = frozenset()
    include_hidden_home: bool = False
    flutter_search_root: Path | None = None
    app_path: Path | None = None
    receipt_dir: Path | None = None
    backup_dir: Path | None = None
    require_zero_hit: tuple[str, ...] = ()
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
    source_layer: str = "runtime_artifact"
    protection: str = "normal"
    rollback_strategy: str = "none"
    validation_patterns: tuple[str, ...] = ()
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
    scope_status: str = "in_scope"
    source_layer: str = "runtime_artifact"
    protection: str = "normal"
    rollback_strategy: str = "none"
    validation_patterns: tuple[str, ...] = ()


@dataclass
class TraceFinding:
    source_layer: str
    source: str
    path: str
    matched: str
    evidence: str
    reason: str
    target_id: str = ""


@dataclass
class TraceReport:
    created_at: str
    mode: str
    home: str
    root: str
    target_path: str
    keyword: str
    findings: list[TraceFinding]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "mode": self.mode,
            "home": self.home,
            "root": self.root,
            "target_path": self.target_path,
            "keyword": self.keyword,
            "findings": [finding.__dict__ for finding in self.findings],
            "summary": self.summary,
        }


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
    approved_targets: tuple[str, ...] = ()
    backup_manifest: dict[str, Any] = field(default_factory=dict)
    residual_validation: list[dict[str, Any]] = field(default_factory=list)
    receipt: dict[str, Any] = field(default_factory=dict)

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
            "approved_targets": list(self.approved_targets),
            "backup_manifest": self.backup_manifest,
            "residual_validation": self.residual_validation,
            "receipt": self.receipt,
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
        "scope_status": item.scope_status,
        "source_layer": item.source_layer,
        "protection": item.protection,
        "rollback_strategy": item.rollback_strategy,
        "validation_patterns": list(item.validation_patterns),
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
        _validate_materialized_output_path(self.context.receipt_dir, "receipt_dir")
        _validate_materialized_output_path(self.context.backup_dir, "backup_dir")

    def _validate_runtime_context(self) -> None:
        if not self.context.root.exists():
            raise FileNotFoundError(f"root not found: {self.context.root}")
        if not self.context.root.is_dir():
            raise FileNotFoundError(f"root is not a directory: {self.context.root}")
        if not self.context.home.exists():
            raise FileNotFoundError(f"home not found: {self.context.home}")

    def trace(self, target_path: Path, keyword: str) -> TraceReport:
        self._validate_runtime_context()
        resolved_target = target_path.expanduser().resolve()
        needles = _trace_needles(resolved_target, keyword)
        findings: list[TraceFinding] = []
        seen: set[tuple[str, str, str, str]] = set()

        def add_finding(
            source_layer: str,
            source: str,
            path: Path,
            matched: str,
            evidence: str,
            reason: str,
            *,
            target_id: str = "",
        ) -> None:
            key = (source_layer, source, str(path), evidence)
            if key in seen:
                return
            seen.add(key)
            findings.append(
                TraceFinding(
                    source_layer=source_layer,
                    source=source,
                    path=str(path),
                    matched=matched,
                    evidence=evidence[:240],
                    reason=reason,
                    target_id=target_id,
                )
            )

        def scan_tree(root: Path, source_layer: str, source: str, reason: str, *, target_prefix: str = "") -> None:
            if not root.exists():
                return
            for candidate in _iter_trace_files(root):
                if candidate.suffix.lower() not in TRACE_TEXT_SUFFIXES and candidate.name not in {
                    "Dockerfile",
                    "Dockerfile.dev",
                    "Dockerfile.local",
                    ".zshrc",
                    ".zprofile",
                    ".bashrc",
                    ".bash_profile",
                    ".profile",
                    "storage.json",
                    "workspace.xml",
                    "recentProjects.xml",
                }:
                    continue
                match = _read_match(candidate, needles)
                if not match:
                    continue
                matched, evidence = match
                target_id = target_prefix or _safe_relpath(candidate, (self.context.home, self.context.root))
                add_finding(source_layer, source, candidate, matched, evidence, reason, target_id=target_id)

        def scan_text_paths(paths: Sequence[Path], source_layer: str, source: str, reason: str) -> None:
            for path in paths:
                if not path.exists():
                    continue
                match = _read_match(path, needles)
                if not match:
                    continue
                matched, evidence = match
                add_finding(source_layer, source, path, matched, evidence, reason, target_id=_safe_relpath(path, (self.context.home, self.context.root)))

        for launch_root in (
            self.context.home / "Library" / "LaunchAgents",
            Path("/Library/LaunchAgents"),
            Path("/Library/LaunchDaemons"),
        ):
            scan_tree(
                launch_root,
                "active_trigger",
                "launch-agent",
                "launch agent or daemon can regenerate this target",
            )
        scan_text_paths(
            [
                self.context.home / ".zshrc",
                self.context.home / ".zprofile",
                self.context.home / ".zlogin",
                self.context.home / ".bashrc",
                self.context.home / ".bash_profile",
                self.context.home / ".profile",
                self.context.home / ".config" / "fish" / "config.fish",
            ],
            "active_trigger",
            "shell-startup",
            "shell startup file can re-create the target",
        )
        if self.runner.which("docker") is not None:
            proc = self.runner.run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Command}}"])
            if proc.returncode == 0:
                for line in (proc.stdout or "").splitlines():
                    matched = _match_text(line, needles)
                    if not matched:
                        continue
                    add_finding(
                        "active_trigger",
                        "docker-container",
                        self.context.root,
                        matched,
                        line.strip()[:240],
                        "docker container history can regenerate the target",
                        target_id="docker:ps",
                    )
            compose_roots = [self.context.root, self.context.home]
            for root in compose_roots:
                if not root.exists():
                    continue
                for pattern in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", "Dockerfile"):
                    for candidate in root.rglob(pattern):
                        match = _read_match(candidate, needles)
                        if not match:
                            continue
                        matched, evidence = match
                        add_finding(
                            "repo_reference",
                            "docker-compose",
                            candidate,
                            matched,
                            evidence,
                            "docker compose or Dockerfile reference can restart the target",
                            target_id=_safe_relpath(candidate, (self.context.home, self.context.root)),
                        )
                        break
        for historical_root in (
            self.context.root / "manifests",
            self.context.root / "reports",
            self.context.root / "graph",
            self.context.root / "knowledge",
            self.context.root / "config",
            self.context.root / "references",
            self.context.root / "templates",
            self.context.root / "tests",
        ):
            scan_tree(
                historical_root,
                "historical_index",
                "repo-history",
                "historical index or generated snapshot can preserve the target",
            )
        for repo_ref_root in (
            self.context.root / "scripts",
            self.context.root / "config",
            self.context.root / "references",
            self.context.root / "templates",
            self.context.root / "tests",
            self.context.root / ".idea",
            self.context.root / ".vscode",
        ):
            scan_tree(
                repo_ref_root,
                "repo_reference",
                "repo-reference",
                "repo scripts, configs, or skill docs can reintroduce the target",
            )
        scan_text_paths(
            [
                self.context.root / "SKILL.md",
                self.context.root / "README.md",
                self.context.root / "agents" / "openai.yaml",
                self.context.root / "references" / "README.md",
                self.context.root / "templates" / "report.md",
                self.context.root / "tests" / "test_mac_storage_manager.py",
            ],
            "repo_reference",
            "repo-reference",
            "repo docs or route config can reintroduce the target",
        )

        layer_counts: dict[str, int] = {}
        for finding in findings:
            layer_counts[finding.source_layer] = layer_counts.get(finding.source_layer, 0) + 1

        public_roots = report_public_roots(self.context)
        public_findings = [
            TraceFinding(
                source_layer=finding.source_layer,
                source=finding.source,
                path=public_display_path(Path(finding.path), home=self.context.home, root=self.context.root, public_roots=public_roots),
                matched=public_text(finding.matched, home=self.context.home, root=self.context.root, public_roots=public_roots),
                evidence=public_text(finding.evidence, home=self.context.home, root=self.context.root, public_roots=public_roots),
                reason=finding.reason,
                target_id=finding.target_id,
            )
            for finding in findings
        ]
        summary = {
            "finding_count": len(findings),
            "layer_counts": dict(sorted(layer_counts.items())),
            "matched_needles": [
                public_text(needle, home=self.context.home, root=self.context.root, public_roots=public_roots)
                for needle in needles
            ],
        }
        return TraceReport(
            created_at=now_iso(),
            mode="trace",
            home=public_display_path(self.context.home, home=self.context.home, root=self.context.root, public_roots=public_roots),
            root=public_display_path(self.context.root, home=self.context.home, root=self.context.root, public_roots=public_roots),
            target_path=public_display_path(resolved_target, home=self.context.home, root=self.context.root, public_roots=public_roots),
            keyword=keyword,
            findings=public_findings,
            summary=summary,
        )

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
            source_layer: str = "runtime_artifact",
            protection: str = "",
            rollback_strategy: str = "",
            validation_patterns: tuple[str, ...] = (),
            metadata: dict[str, Any] | None = None,
        ) -> None:
            paths = expand_patterns(raw_paths, home)
            effective_metadata = metadata or {}
            effective_protection = protection
            if not effective_protection:
                if effective_metadata.get("cleanup_requires_approved_plan"):
                    effective_protection = "approved_plan"
                elif requires_confirmation:
                    effective_protection = "exact_confirm"
                else:
                    effective_protection = "normal"
            effective_rollback = rollback_strategy
            if not effective_rollback:
                effective_rollback = "trash" if kind == "trash_tree" else "none"
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
                    source_layer=_validated_choice(source_layer, SOURCE_LAYERS, "runtime_artifact"),
                    protection=_validated_choice(effective_protection, PROTECTIONS, "normal"),
                    rollback_strategy=_validated_choice(effective_rollback, ROLLBACK_STRATEGIES, "none"),
                    validation_patterns=validation_patterns,
                    metadata=effective_metadata,
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
            source_layer="user_data",
            rollback_strategy="trash",
            validation_patterns=("~/.Trash",),
        )
        add(
            "downloads",
            "Downloads",
            "user-files",
            "trash_tree",
            [home / "Downloads"],
            risk="high",
            requires_confirmation=True,
            source_layer="user_data",
            rollback_strategy="trash",
            validation_patterns=("~/Downloads",),
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

        if self.context.include_hidden_home:
            add(
                "home-dot-git",
                "Home directory git metadata",
                "hidden-home",
                "trash_tree",
                [home / ".git"],
                risk="high",
                requires_confirmation=True,
                source_layer="repo_reference",
                protection="approved_plan",
                rollback_strategy="trash",
                validation_patterns=(".git",),
                metadata={"cleanup_requires_approved_plan": True, "move_whole_paths": True},
            )
            add(
                "home-npm-cache",
                "Home npm cache",
                "hidden-home",
                "purge_tree",
                [home / ".npm" / "_cacache", home / ".npm" / "_npx"],
                risk="low",
                metadata={"cleanup_requires_approved_plan": True},
            )
            add(
                "home-precommit-cache",
                "Home pre-commit cache",
                "hidden-home",
                "purge_tree",
                [home / ".cache" / "pre-commit"],
                risk="low",
                metadata={"cleanup_requires_approved_plan": True},
            )
            for child in sorted(home.iterdir(), key=lambda item: item.name.lower()):
                if not child.name.startswith(".") or child.name in {".", "..", ".Trash"}:
                    continue
                if child in {home / ".git", home / ".npm", home / ".cache"}:
                    continue
                if child.name in {".ssh", ".config"}:
                    continue
                target_id = f"hidden-home:{child.name.lstrip('.') or 'dot'}"
                metadata = {
                    "cleanup_requires_approved_plan": True,
                    "hidden_home_path": str(child),
                    "move_whole_paths": True,
                }
                add(
                    target_id,
                    f"Hidden home item ({child.name})",
                    "hidden-home",
                    "trash_tree",
                    [child],
                    risk="high",
                    requires_confirmation=True,
                    source_layer="user_data",
                    protection="approved_plan",
                    rollback_strategy="trash",
                    validation_patterns=(child.name,),
                    metadata=metadata,
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
                protection="approved_plan",
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
                protection="approved_plan",
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
                protection="approved_plan",
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
                source_layer="runtime_artifact",
                protection="approved_plan",
                rollback_strategy="trash",
                validation_patterns=(app_name, bundle_id) if bundle_id else (app_name,),
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
        owner_uid = os.getuid()
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

            notes: list[str] = []
            for path in target.paths:
                if not path.exists():
                    continue
                protected = _first_protected_session_path(path)
                if protected:
                    protected_path, protected_reason = protected
                    notes.append(f"protected_session={protected_reason}")
                    notes.append(f"protected_path={protected_path}")
                if path.name == "Docker.raw":
                    allocated = _allocated_bytes(path)
                    if allocated and allocated != total_bytes:
                        notes.append(f"allocated_bytes={allocated}")
                if path.name == ".git" and path.resolve() == (self.context.home / ".git").resolve():
                    notes.append("home directory appears to be a git worktree root")
                if "Containers" in path.parts and path.parent.name == "Containers":
                    bundle_id = _read_container_bundle_id(path)
                    if bundle_id:
                        notes.append(f"container_bundle_id={bundle_id}")
                if "_cacache" in path.parts:
                    non_owner_paths = _find_non_owner_paths(path, owner_uid)
                    if non_owner_paths:
                        notes.append(f"non_owner_entries={len(non_owner_paths)}")
                        notes.extend(f"non_owner_path={item}" for item in non_owner_paths[:3])

            scan = TargetScan(
                target=target,
                exists=exists,
                total_bytes=total_bytes,
                eligible_bytes=(
                    total_bytes
                    if target.kind == "command" or target.metadata.get("move_whole_paths")
                    else eligible_bytes
                ),
                total_files=total_files,
                eligible_files=(
                    total_files
                    if target.kind == "command" or target.metadata.get("move_whole_paths")
                    else eligible_files
                ),
                newest_mtime=newest_mtime,
                oldest_mtime=oldest_mtime,
                existing_paths=tuple(existing_paths),
                missing_paths=tuple(missing_paths),
                notes=tuple(notes),
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
            scope_status = "in_scope"
            source_layer = target.source_layer
            protection = target.protection
            protected_notes = [note for note in scan.notes if note.startswith("protected_session=")]
            requires_approved_plan = bool(
                target.metadata.get("cleanup_requires_approved_plan")
                or target.risk in HIGH_RISK_VALUES
                or target.protection == "approved_plan"
            )

            if protected_notes:
                status = "blocked"
                reason = protected_notes[0].split("=", 1)[1] or "protected session data"
                scope_status = "protected_session"
                source_layer = "protected_session"
                protection = "blocked"
            elif target.kind != "command" and not scan.exists:
                status = "skipped"
                reason = "target path missing"
            elif target.required_tools and any(self.runner.which(tool) is None for tool in target.required_tools):
                status = "skipped"
                reason = f"missing tool: {', '.join(tool for tool in target.required_tools if self.runner.which(tool) is None)}"
            elif target.target_id == "docker-prune" and not self._docker_context_is_local():
                status = "skipped"
                reason = "docker context is remote"
            elif requires_approved_plan and not self.context.approved_targets:
                status = "blocked"
                reason = "approved cleanup plan required before medium/high-risk cleanup"
                scope_status = "outside_approved_plan"
                protection = "approved_plan"
            elif requires_approved_plan and target.target_id not in self.context.approved_targets:
                status = "blocked"
                reason = "outside approved cleanup plan"
                scope_status = "outside_approved_plan"
                protection = "approved_plan"
            elif any(note.startswith("non_owner_entries=") for note in scan.notes):
                status = "blocked"
                reason = "ownership mismatch; fix owner before cleanup"
            elif target.requires_confirmation and not self._is_confirmed(target):
                status = "blocked"
                reason = "explicit confirmation required"
                protection = "exact_confirm"
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
                    scope_status=scope_status,
                    source_layer=source_layer,
                    protection=_validated_choice(protection, PROTECTIONS, "normal"),
                    rollback_strategy=target.rollback_strategy,
                    validation_patterns=target.validation_patterns,
                )
            )
        return out

    def _is_confirmed(self, target: CleanupTarget) -> bool:
        if target.target_id in self.context.confirm_targets:
            return True
        if target.category in self.context.confirm_targets and target.risk == "low":
            return True
        if self.context.yes and target.risk == "low":
            return True
        return False

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

    def _default_receipt_dir(self) -> Path:
        return self.context.receipt_dir or (self.context.home / ".mac-storage-manager" / "receipts")

    def _default_backup_dir(self) -> Path:
        return self.context.backup_dir or (self.context.home / ".mac-storage-manager" / "backups" / f"backup-{cleanup_stamp()}")

    def _should_back_up(self, target: CleanupTarget) -> bool:
        if target.risk in HIGH_RISK_VALUES:
            return True
        if target.source_layer in {"repo_reference", "historical_index"}:
            return True
        if target.target_id == "app-leftovers:" + target.metadata.get("app_name", ""):
            return True
        return False

    def _iter_backup_sources(self, path: Path) -> Iterable[Path]:
        if not path.exists():
            return []
        if path.is_file() or path.is_symlink():
            return [path]
        files: list[Path] = []
        for current, _st in walk_files(path):
            files.append(current)
        return files

    def _build_backup_manifest(self, scans: Sequence[TargetScan], plan_items: Sequence[PlanItem]) -> dict[str, Any]:
        if self.context.dry_run or not self.context.apply:
            return {"enabled": False, "backup_dir": "", "candidate_count": 0, "copied_count": 0, "paths": []}
        targets_by_id = {item.target_id: item for item in plan_items}
        candidate_scans = [
            scan
            for scan in scans
            if targets_by_id.get(scan.target.target_id) and targets_by_id[scan.target.target_id].status in {"ready", "planned"}
            and self._should_back_up(scan.target)
        ]
        if not candidate_scans:
            return {"enabled": False, "backup_dir": "", "candidate_count": 0, "copied_count": 0, "paths": []}

        backup_dir = self._default_backup_dir().resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        touched_lines: list[str] = []
        sha_lines: list[str] = []
        copied_files: list[str] = []
        hashed_files = 0
        for scan in candidate_scans:
            for rel_path in scan.existing_paths:
                source = Path(rel_path)
                if not source.exists():
                    continue
                for item in self._iter_backup_sources(source):
                    try:
                        stat_result = item.stat()
                    except Exception:
                        continue
                    rel = _safe_relpath(item, (self.context.home, self.context.root))
                    touched_lines.append(rel)
                    if stat_result.st_size <= MAX_HASH_BYTES:
                        try:
                            digest = _sha256_for_file(item)
                        except Exception:
                            digest = "sha256-error"
                    else:
                        digest = "sha256-skipped-large-file"
                    sha_lines.append(f"{digest}  {rel}")
                    hashed_files += 1
                    if stat_result.st_size <= SMALL_TEXT_BACKUP_BYTES and _is_probably_text_file(item):
                        destination = backup_dir / rel
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, destination)
                        copied_files.append(str(destination))

        touched_manifest = backup_dir / "touched-files.txt"
        sha_manifest = backup_dir / "sha256.txt"
        metadata_path = backup_dir / "manifest.json"
        touched_manifest.write_text("\n".join(touched_lines) + ("\n" if touched_lines else ""), encoding="utf-8")
        sha_manifest.write_text("\n".join(sha_lines) + ("\n" if sha_lines else ""), encoding="utf-8")
        manifest = {
            "enabled": True,
            "backup_dir": str(backup_dir),
            "candidate_count": len(candidate_scans),
            "copied_count": len(copied_files),
            "hashed_count": hashed_files,
            "touched_manifest": str(touched_manifest),
            "sha256_manifest": str(sha_manifest),
            "paths": copied_files,
            "targets": [scan.target.target_id for scan in candidate_scans],
        }
        metadata_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["manifest_json"] = str(metadata_path)
        return manifest

    def _run_residual_validation(self, plan_items: Sequence[PlanItem]) -> list[dict[str, Any]]:
        patterns: list[str] = []
        patterns.extend(self.context.require_zero_hit)
        for item in plan_items:
            if item.status != "cleaned":
                continue
            if item.source_layer in {"historical_index", "repo_reference"}:
                patterns.extend(item.validation_patterns)
        if not patterns:
            return []

        search_roots = [self.context.root]
        if self.context.home != self.context.root:
            search_roots.append(self.context.home)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_pattern in patterns:
            pattern = str(raw_pattern or "").strip()
            if not pattern or pattern in seen:
                continue
            seen.add(pattern)
            matches: list[str] = []
            for root in search_roots:
                if not root.exists():
                    continue
                for candidate in _iter_trace_files(root):
                    if len(matches) >= 20:
                        break
                    if candidate.is_dir():
                        continue
                    try:
                        if candidate.stat().st_size > TRACE_MAX_FILE_BYTES:
                            continue
                    except OSError:
                        continue
                    try:
                        text = candidate.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue
                    if pattern.lower() in candidate.as_posix().lower():
                        matches.append(candidate.as_posix())
                        continue
                    for line in text.splitlines():
                        if pattern.lower() in line.lower():
                            matches.append(f"{candidate.as_posix()}: {line.strip()[:160]}")
                            break
                if len(matches) >= 20:
                    break
            results.append(
                {
                    "pattern": pattern,
                    "status": "pass" if not matches else "fail",
                    "hit_count": len(matches),
                    "sample_hits": matches[:5],
                    "command": f"rg -n -S {pattern}",
                }
            )
        return results

    def _write_receipt(self, report: StorageReport) -> dict[str, Any]:
        receipt_dir = self._default_receipt_dir().resolve()
        receipt_dir.mkdir(parents=True, exist_ok=True)
        stamp = cleanup_stamp()
        md_path = receipt_dir / f"cleanup-receipt-{stamp}.md"
        json_path = receipt_dir / f"cleanup-receipt-{stamp}.json"
        receipt = {
            "receipt_dir": str(receipt_dir),
            "markdown": str(md_path),
            "json": str(json_path),
            "backup_dir": report.backup_manifest.get("backup_dir", ""),
            "validation_count": len(report.residual_validation),
        }
        report.receipt = {
            "receipt_dir": self._public_path(receipt_dir),
            "markdown": self._public_path(md_path),
            "json": self._public_path(json_path),
            "backup_dir": report.backup_manifest.get("backup_dir", ""),
            "validation_count": len(report.residual_validation),
        }
        md_path.write_text(render_markdown(report), encoding="utf-8")
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report.receipt

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
                item.actual_bytes = reclaimed
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
                item.actual_bytes = reclaimed
                actual_reclaimed += reclaimed
                if should_apply:
                    changed_targets.add(target.target_id)
                if item.status not in {"failed"}:
                    item.status = "cleaned" if should_apply else "planned"
                    item.reason = "flutter project cleaned" if should_apply else "dry-run"
                continue

            reclaimed, changed = self._execute_filesystem_target(target)
            item.actual_bytes = reclaimed
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

    def _public_roots(self) -> tuple[Path, ...]:
        return report_public_roots(self.context)

    def _public_path(self, path: str | Path) -> str:
        return public_display_path(Path(path), home=self.context.home, root=self.context.root, public_roots=self._public_roots())

    def _public_text(self, text: str) -> str:
        return public_text(text, home=self.context.home, root=self.context.root, public_roots=self._public_roots())

    def _public_note(self, note: str) -> str:
        return public_note(note, home=self.context.home, root=self.context.root, public_roots=self._public_roots())

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
                    "source_layer": scan.target.source_layer,
                    "protection": scan.target.protection,
                    "rollback_strategy": scan.target.rollback_strategy,
                    "validation_patterns": list(scan.target.validation_patterns),
                    "status": "missing" if not scan.exists else "present",
                    "total_bytes": scan.total_bytes,
                    "eligible_bytes": scan.eligible_bytes,
                    "paths": [self._public_path(path) for path in scan.existing_paths],
                    "notes": [self._public_note(note) for note in scan.notes],
                }
            )
        return out

    def _public_plan_item(self, item: PlanItem) -> PlanItem:
        return PlanItem(
            target_id=item.target_id,
            name=item.name,
            category=item.category,
            kind=item.kind,
            risk=item.risk,
            status=item.status,
            reason=self._public_note(item.reason),
            estimated_bytes=item.estimated_bytes,
            actual_bytes=item.actual_bytes,
            paths=tuple(self._public_path(path) for path in item.paths),
            command_output=self._public_text(item.command_output),
            requires_confirmation=item.requires_confirmation,
            recoverable=item.recoverable,
            scope_status=item.scope_status,
            source_layer=item.source_layer,
            protection=item.protection,
            rollback_strategy=item.rollback_strategy,
            validation_patterns=item.validation_patterns,
        )

    def _public_backup_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        if not manifest:
            return {}
        public = dict(manifest)
        for key in ("backup_dir", "touched_manifest", "sha256_manifest", "manifest_json"):
            if public.get(key):
                public[key] = self._public_path(str(public[key]))
        if isinstance(public.get("paths"), list):
            public["paths"] = [self._public_path(str(path)) for path in public["paths"]]
        return public

    def _public_residual_validation(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        public_rows: list[dict[str, Any]] = []
        for row in rows:
            public = dict(row)
            if isinstance(public.get("sample_hits"), list):
                public["sample_hits"] = [self._public_text(str(hit)) for hit in public["sample_hits"]]
            if public.get("command"):
                public["command"] = self._public_text(str(public["command"]))
            public_rows.append(public)
        return public_rows

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
        backup_manifest: dict[str, Any] | None = None,
        residual_validation: list[dict[str, Any]] | None = None,
    ) -> StorageReport:
        before_total_bytes = sum(scan.total_bytes for scan in before_scans)
        after_total_bytes = sum(scan.total_bytes for scan in after_scans)
        estimated_reclaimed_bytes = sum(item.estimated_bytes for item in plan_items if item.status in {"planned", "ready", "cleaned"})
        public_roots = self._public_roots()
        return StorageReport(
            created_at=now_iso(),
            mode=mode,
            home=public_display_path(self.context.home, home=self.context.home, root=self.context.root, public_roots=public_roots),
            root=public_display_path(self.context.root, home=self.context.home, root=self.context.root, public_roots=public_roots),
            days_to_keep=self.context.days_to_keep,
            dry_run=self.context.dry_run or not self.context.apply,
            apply_requested=self.context.apply,
            before_free_bytes=before_free_bytes,
            after_free_bytes=after_free_bytes,
            before_total_bytes=before_total_bytes,
            after_total_bytes=after_total_bytes,
            estimated_reclaimed_bytes=estimated_reclaimed_bytes,
            actual_reclaimed_bytes=actual_reclaimed_bytes,
            top_consumers=self._build_top_consumers(after_scans if mode == "clean" else before_scans),
            plan_items=[self._public_plan_item(item) for item in plan_items],
            notes=[self._public_note(note) for note in notes],
            approved_targets=tuple(sorted(self.context.approved_targets)),
            backup_manifest=self._public_backup_manifest(backup_manifest or {}),
            residual_validation=self._public_residual_validation(residual_validation or []),
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
            backup_manifest={},
            residual_validation=[],
        )

    def plan(self) -> StorageReport:
        return self.audit()

    def clean(self) -> StorageReport:
        targets = self.discover_targets()
        before_scans = self.scan_targets(targets)
        plan_items = self.plan_targets(before_scans)
        before_free = shutil.disk_usage(self.context.root).free
        backup_manifest = self._build_backup_manifest(before_scans, plan_items)
        plan_items, reclaimed = self.execute(before_scans, plan_items)
        after_scans = self.scan_targets(targets)
        after_free = shutil.disk_usage(self.context.root).free
        report = self._make_report(
            mode="clean",
            before_scans=before_scans,
            after_scans=after_scans,
            plan_items=plan_items,
            actual_reclaimed_bytes=reclaimed,
            before_free_bytes=before_free,
            after_free_bytes=after_free,
            notes=self._collect_notes(plan_items, after_scans),
            backup_manifest=backup_manifest,
            residual_validation=self._run_residual_validation(plan_items),
        )
        if self.context.apply and not self.context.dry_run:
            report.receipt = self._write_receipt(report)
        return report

    def _collect_notes(self, plan_items: Sequence[PlanItem], scans: Sequence[TargetScan]) -> list[str]:
        notes: list[str] = []
        if self.context.approved_targets:
            notes.append(f"approved targets: {', '.join(sorted(self.context.approved_targets))}")
        notes.append("cleanup rule: list exact targets first, confirm, then clean only within approved scope")
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
        f"- Approved targets: {', '.join(report.approved_targets) if report.approved_targets else 'none'}",
        "",
        "## Top Consumers",
    ]
    for index, item in enumerate(report.top_consumers[:5], start=1):
        lines.append(
            f"{index}. {item['name']} ({item['target_id']}) - {human_bytes(int(item['eligible_bytes']))} reclaimable "
            f"[layer={item.get('source_layer', 'runtime_artifact')} protection={item.get('protection', 'normal')}]"
        )
    if not report.top_consumers:
        lines.append("1. None")
    lines.extend(
        [
            "",
            "## Cleanup Boundary",
            "- Review the exact target list first.",
            "- Confirm exact targets before apply.",
            "- Cleanup must stay inside the approved target list and explicit confirmations.",
            "",
            "## Cleaned / Planned",
        ]
    )
    for item in report.plan_items:
        lines.append(
            f"- `{item.target_id}` [{item.status}] [{item.scope_status}] "
            f"layer={item.source_layer} protection={item.protection} rollback={item.rollback_strategy} - {item.reason}"
        )
    lines.extend(["", "## Backup / Receipt"])
    backup = report.backup_manifest or {}
    if backup.get("enabled"):
        lines.append(f"- Backup dir: {backup.get('backup_dir', '')}")
        lines.append(f"- Touched manifest: {backup.get('touched_manifest', '')}")
        lines.append(f"- SHA256 manifest: {backup.get('sha256_manifest', '')}")
        lines.append(f"- Copied small text files: {backup.get('copied_count', 0)}")
    else:
        lines.append("- Backup manifest: not required for this plan")
    if report.receipt:
        lines.append(f"- Receipt markdown: {report.receipt.get('markdown', '')}")
        lines.append(f"- Receipt json: {report.receipt.get('json', '')}")
    else:
        lines.append("- Receipt: not written in dry-run/audit mode")
    lines.extend(["", "## Residual Validation"])
    if report.residual_validation:
        for row in report.residual_validation:
            lines.append(
                f"- `{row.get('pattern', '')}` [{row.get('status', '')}] "
                f"hits={row.get('hit_count', 0)} command=`{row.get('command', '')}`"
            )
    else:
        lines.append("- No zero-hit validation patterns requested")
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
            "1. Re-run `plan` or `audit` to review the exact list before any cleanup.",
            "2. Re-run with `--approved-targets <exact-target-ids>` and any required `--confirm-targets <exact-target-id>` after reviewing blocked targets.",
            "3. Narrow the scan with `--flutter-search-root`, `--app-path`, or `--include-hidden-home` for focused cleanup.",
        ]
    )
    return "\n".join(lines)


def render_trace_markdown(report: TraceReport) -> str:
    lines = [
        "# macOS Reappearing Target Trace",
        "",
        "## Summary",
        f"- Target path: `{report.target_path}`",
        f"- Keyword: `{report.keyword}`",
        f"- Findings: {report.summary.get('finding_count', 0)}",
        f"- Layer counts: {json.dumps(report.summary.get('layer_counts', {}), ensure_ascii=False)}",
        "",
        "## Findings",
    ]
    if not report.findings:
        lines.append("- None")
    for finding in report.findings:
        lines.append(
            f"- `{finding.source_layer}` / `{finding.source}` / `{finding.target_id or finding.path}`: "
            f"matched `{finding.matched}` — {finding.reason}; evidence: {finding.evidence}"
        )
    lines.extend(
        [
            "",
            "## Next Step Options",
            "1. Remove active triggers first; deleting the folder alone is not sufficient.",
            "2. Then clean runtime artifacts and repo references inside the explicit target list.",
            "3. Finish with scoped residual search and receipt evidence.",
        ]
    )
    return "\n".join(lines)


def render_trace_text(report: TraceReport) -> str:
    layers = ", ".join(f"{key}={value}" for key, value in report.summary.get("layer_counts", {}).items()) or "none"
    return (
        f"Trace findings: {report.summary.get('finding_count', 0)} for {report.keyword}. "
        f"Layers: {layers}. Next: remove active triggers before deleting runtime artifacts."
    )


def render_text(report: StorageReport) -> str:
    lines = [
        f"Root conclusion: {human_bytes(report.actual_reclaimed_bytes)} reclaimed, {human_bytes(report.estimated_reclaimed_bytes)} estimated.",
        f"Actions taken: {sum(1 for item in report.plan_items if item.status == 'cleaned')} cleaned, {sum(1 for item in report.plan_items if item.status == 'blocked')} blocked, {sum(1 for item in report.plan_items if item.status == 'skipped')} skipped.",
        f"Verification status: {'dry-run' if report.dry_run else 'applied'}.",
        f"Free space: {human_bytes(report.before_free_bytes)} -> {human_bytes(report.after_free_bytes)}.",
        f"Approved scope: {', '.join(report.approved_targets) if report.approved_targets else 'none'}.",
        f"Receipt: {report.receipt.get('markdown', 'not written') if report.receipt else 'not written'}.",
        "Next safe step: inspect the exact list first, then re-run with approved targets and explicit confirmations only.",
    ]
    return "\n".join(lines)


def _parse_csv(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return frozenset(parts)


def _parse_path_csv(value: str | None) -> tuple[Path, ...]:
    if not value:
        return ()
    return tuple(Path(part.strip()).expanduser().resolve() for part in value.split(",") if part.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit and clean macOS storage safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--home", default=str(Path.home()))
        p.add_argument("--root", default="")
        p.add_argument("--days-to-keep", type=int, default=7)
        p.add_argument("--confirm-targets", default="")
        p.add_argument("--approved-targets", default="")
        p.add_argument("--require-zero-hit", action="append", default=[])
        p.add_argument("--receipt-dir", default="")
        p.add_argument("--backup-dir", default="")
        p.add_argument("--flutter-search-root", default="")
        p.add_argument("--app-path", default="")
        p.add_argument("--include-system", action="store_true")
        p.add_argument("--system-roots", default="")
        p.add_argument("--include-hidden-home", action="store_true")
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

    trace = sub.add_parser("trace", help="Trace repeated regeneration sources for a target")
    add_common(trace)
    trace.add_argument("--path", required=True)
    trace.add_argument("--keyword", required=True)
    trace.add_argument("--topk", type=int, default=20)
    return parser


def _context_from_args(args: argparse.Namespace) -> StorageContext:
    home = Path(args.home).expanduser().resolve()
    root = Path(args.root).expanduser().resolve() if args.root else home
    flutter_root = Path(args.flutter_search_root).expanduser().resolve() if args.flutter_search_root else None
    app_path = Path(args.app_path).expanduser().resolve() if args.app_path else None
    receipt_dir = Path(args.receipt_dir).expanduser().resolve() if args.receipt_dir else None
    backup_dir = Path(args.backup_dir).expanduser().resolve() if args.backup_dir else None
    require_zero_hit = tuple(
        part.strip()
        for value in getattr(args, "require_zero_hit", [])
        for part in str(value).split(",")
        if part.strip()
    )
    system_roots = _parse_path_csv(getattr(args, "system_roots", "") or os.environ.get("MAC_STORAGE_SYSTEM_ROOTS"))
    return StorageContext(
        home=home,
        root=root,
        days_to_keep=int(args.days_to_keep),
        dry_run=bool(getattr(args, "dry_run", False) or args.command in {"audit", "plan", "trace"}),
        apply=bool(getattr(args, "apply", False)),
        yes=bool(getattr(args, "yes", False)),
        include_system=bool(args.include_system),
        confirm_targets=_parse_csv(args.confirm_targets),
        approved_targets=_parse_csv(getattr(args, "approved_targets", "")),
        require_zero_hit=require_zero_hit,
        include_hidden_home=bool(getattr(args, "include_hidden_home", False)),
        flutter_search_root=flutter_root,
        app_path=app_path,
        receipt_dir=receipt_dir,
        backup_dir=backup_dir,
        system_roots=system_roots or DEFAULT_SYSTEM_ROOTS,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = _context_from_args(args)
    manager = StorageManager(ctx)

    if args.command == "trace":
        trace_report = manager.trace(Path(args.path), str(args.keyword))
        if getattr(args, "json", False):
            print(json.dumps(trace_report.to_dict(), ensure_ascii=False, indent=2))
        elif getattr(args, "markdown", False):
            print(render_trace_markdown(trace_report))
        else:
            print(render_trace_text(trace_report))
        return 0

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
