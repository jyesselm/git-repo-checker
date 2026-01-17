"""Filesystem scanning for git repositories."""

import fnmatch
from collections.abc import Iterator
from pathlib import Path

MAX_DEPTH = 20  # Prevent infinite loops from symlinks


def find_git_repos(
    scan_paths: list[Path],
    exclude_patterns: list[str],
    exclude_paths: list[Path],
) -> Iterator[Path]:
    """Find all git repositories in the given paths.

    Walks directory trees looking for .git directories.
    Stops descending once a .git directory is found.

    Args:
        scan_paths: Root directories to scan.
        exclude_patterns: Glob patterns to exclude (e.g., "**/node_modules").
        exclude_paths: Specific absolute paths to exclude.

    Yields:
        Path to each repository root (parent of .git).
    """
    visited: set[int] = set()

    for scan_path in scan_paths:
        if not scan_path.exists():
            continue
        if not scan_path.is_dir():
            continue

        yield from scan_directory(
            root=scan_path,
            exclude_patterns=exclude_patterns,
            exclude_paths=set(exclude_paths),
            visited=visited,
            depth=0,
        )


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
    if depth > MAX_DEPTH:
        return

    try:
        stat_info = root.stat()
    except (PermissionError, OSError):
        return

    if stat_info.st_ino in visited:
        return
    visited.add(stat_info.st_ino)

    if should_exclude(root, exclude_patterns, exclude_paths):
        return

    git_dir = root / ".git"
    if git_dir.exists() and git_dir.is_dir():
        yield root
        return  # Don't descend into git repos

    try:
        entries = list(root.iterdir())
    except (PermissionError, OSError):
        return

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue

        yield from scan_directory(
            root=entry,
            exclude_patterns=exclude_patterns,
            exclude_paths=exclude_paths,
            visited=visited,
            depth=depth + 1,
        )


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
