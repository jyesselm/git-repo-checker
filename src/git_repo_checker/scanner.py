"""Filesystem scanning for git repositories."""

import fnmatch
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

MAX_DEPTH = 20  # Prevent infinite loops from symlinks


@dataclass
class ScanWalkResult:
    """Repos found plus directories that could not be scanned."""

    repos: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class _WalkContext:
    """Bundled parameters for recursive walk, avoiding long argument lists."""

    exclude_patterns: list[str]
    exclude_paths: set[Path]
    visited: set[int]


def _walk(root: Path, ctx: _WalkContext, depth: int, result: ScanWalkResult) -> None:
    """Recursively walk a directory and collect repos and errors.

    Args:
        root: Directory to walk.
        ctx: Walk context with exclusion rules and visited inodes.
        depth: Current recursion depth.
        result: Accumulates found repos and errors in-place.
    """
    if depth > MAX_DEPTH:
        return

    try:
        stat_info = root.stat()
    except (PermissionError, OSError) as exc:
        msg = (
            f"Permission denied: {root}"
            if isinstance(exc, PermissionError)
            else f"Cannot scan {root}: {exc}"
        )
        result.errors.append(msg)
        return

    if stat_info.st_ino in ctx.visited:
        return
    ctx.visited.add(stat_info.st_ino)

    if should_exclude(root, ctx.exclude_patterns, ctx.exclude_paths):
        return

    git_dir = root / ".git"
    if git_dir.exists() and git_dir.is_dir():
        result.repos.append(root)
        return

    try:
        entries = list(root.iterdir())
    except (PermissionError, OSError) as exc:
        msg = (
            f"Permission denied: {root}"
            if isinstance(exc, PermissionError)
            else f"Cannot scan {root}: {exc}"
        )
        result.errors.append(msg)
        return

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        _walk(entry, ctx, depth + 1, result)


def walk_git_repos(
    scan_paths: list[Path],
    exclude_patterns: list[str],
    exclude_paths: list[Path],
) -> ScanWalkResult:
    """Find all git repositories in given paths, collecting errors.

    Walks directory trees looking for .git directories.
    Records PermissionError and OSError encountered during traversal.

    Args:
        scan_paths: Root directories to scan.
        exclude_patterns: Glob patterns to exclude (e.g., "**/node_modules").
        exclude_paths: Specific absolute paths to exclude.

    Returns:
        ScanWalkResult with discovered repos and any scan errors.
    """
    result = ScanWalkResult()
    ctx = _WalkContext(
        exclude_patterns=exclude_patterns,
        exclude_paths=set(exclude_paths),
        visited=set(),
    )

    for scan_path in scan_paths:
        if not scan_path.exists():
            continue
        if not scan_path.is_dir():
            continue
        _walk(scan_path, ctx, depth=0, result=result)

    return result


def find_git_repos(
    scan_paths: list[Path],
    exclude_patterns: list[str],
    exclude_paths: list[Path],
) -> Iterator[Path]:
    """Find all git repositories in the given paths.

    Thin wrapper around walk_git_repos that drops errors.
    Walks directory trees looking for .git directories.
    Stops descending once a .git directory is found.

    Args:
        scan_paths: Root directories to scan.
        exclude_patterns: Glob patterns to exclude (e.g., "**/node_modules").
        exclude_paths: Specific absolute paths to exclude.

    Yields:
        Path to each repository root (parent of .git).
    """
    walk_result = walk_git_repos(scan_paths, exclude_patterns, exclude_paths)
    yield from walk_result.repos


def scan_directory(
    root: Path,
    exclude_patterns: list[str],
    exclude_paths: set[Path],
    visited: set[int],
    depth: int,
) -> Iterator[Path]:
    """Recursively scan a directory for git repos.

    Args:
        root: Directory to scan.
        exclude_patterns: Patterns to exclude.
        exclude_paths: Paths to exclude.
        visited: Set of visited inode numbers to prevent loops.
        depth: Current recursion depth.

    Yields:
        Path to each repository root found.
    """
    ctx = _WalkContext(
        exclude_patterns=exclude_patterns,
        exclude_paths=exclude_paths,
        visited=visited,
    )
    sub_result = ScanWalkResult()
    _walk(root, ctx, depth, sub_result)
    yield from sub_result.repos


def should_exclude(
    path: Path,
    exclude_patterns: list[str],
    exclude_paths: set[Path],
) -> bool:
    """Check if a path should be excluded from scanning.

    Args:
        path: Path to check.
        exclude_patterns: Glob patterns to match against.
        exclude_paths: Explicit paths to exclude.

    Returns:
        True if path should be excluded.
    """
    if path in exclude_paths:
        return True

    return matches_any_pattern(path, exclude_patterns)


def matches_any_pattern(path: Path, patterns: list[str]) -> bool:
    """Check if path matches any of the glob patterns.

    Supports patterns like "**/node_modules" and "vendor/*".

    Args:
        path: Path to check.
        patterns: List of glob patterns.

    Returns:
        True if path matches any pattern.
    """
    path_str = str(path)
    path_parts = path.parts

    for pattern in patterns:
        if "**" in pattern:
            # For ** patterns, check if any part of path matches
            pattern_name = pattern.replace("**/", "").replace("**", "")
            if fnmatch.fnmatch(path.name, pattern_name):
                return True
            if fnmatch.fnmatch(path_str, pattern):
                return True
        elif fnmatch.fnmatch(path.name, pattern):
            return True
        elif fnmatch.fnmatch(path_str, pattern):
            return True
        # Check if any path component matches
        for part in path_parts:
            if fnmatch.fnmatch(part, pattern.replace("**/", "")):
                return True

    return False


def get_relative_path(path: Path, base_paths: list[Path]) -> str:
    """Get a short display path relative to scan roots.

    Args:
        path: Absolute path to shorten.
        base_paths: List of base paths to try making relative to.

    Returns:
        Shortest relative path string, or absolute if not under any base.
    """
    for base in base_paths:
        try:
            rel = path.relative_to(base)
            return str(rel)
        except ValueError:
            continue

    # Fall back to home-relative or absolute
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)
