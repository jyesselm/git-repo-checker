"""Data models for git-repo-checker."""

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class RepoStatus(str, Enum):
    """Status of a git repository."""

    CLEAN = "clean"
    DIRTY = "dirty"
    UNTRACKED = "untracked"
    AHEAD = "ahead"
    BEHIND = "behind"
    DIVERGED = "diverged"
    NO_REMOTE = "no_remote"
    ERROR = "error"


class WarningType(str, Enum):
    """Types of warnings for bad practices."""

    DIRTY_MAIN = "dirty_main"
    NO_REMOTE = "no_remote"
    DETACHED = "detached"


class RepoInfo(BaseModel):
    """Information about a single git repository."""

    path: Path
    branch: str
    status: RepoStatus
    is_main_branch: bool = False
    ahead_count: int = 0
    behind_count: int = 0
    changed_files: int = 0
    untracked_files: int = 0
    warnings: list[WarningType] = Field(default_factory=list)
    error_message: str | None = None

    model_config = {"arbitrary_types_allowed": True}


class PullResult(BaseModel):
    """Result of a git pull operation."""

    path: Path
    success: bool
    message: str
    files_changed: int = 0

    model_config = {"arbitrary_types_allowed": True}


class ScanResult(BaseModel):
    """Result of scanning all repositories."""

    repos: list[RepoInfo] = Field(default_factory=list)
    pull_results: list[PullResult] = Field(default_factory=list)
    total_scanned: int = 0
    scan_errors: list[str] = Field(default_factory=list)


class AutoPullConfig(BaseModel):
    """Configuration for auto-pull behavior."""

    enabled: bool = True
    require_clean: bool = True
    skip_patterns: list[str] = Field(default_factory=list)


class OutputConfig(BaseModel):
    """Configuration for output formatting."""

    show_clean: bool = True
    color: bool = True
    verbosity: str = "normal"


class Config(BaseModel):
    """Application configuration loaded from YAML."""

    scan_paths: list[Path] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    exclude_paths: list[Path] = Field(default_factory=list)
    main_branches: list[str] = Field(default_factory=lambda: ["main", "master"])
    auto_pull: AutoPullConfig = Field(default_factory=AutoPullConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    model_config = {"arbitrary_types_allowed": True}


class TrackedRepo(BaseModel):
    """A repository to track and sync across machines."""

    path: Path
    remote: str
    branch: str = "main"
    ignore: bool = False

    model_config = {"arbitrary_types_allowed": True}


class SyncAction(str, Enum):
    """Action taken during sync."""

    CLONED = "cloned"
    PULLED = "pulled"
    SKIPPED = "skipped"
    ERROR = "error"


class SyncRepoResult(BaseModel):
    """Result of syncing a single repository."""

    repo: TrackedRepo
    action: SyncAction
    message: str

    model_config = {"arbitrary_types_allowed": True}


class SyncResult(BaseModel):
    """Result of syncing all tracked repositories."""

    results: list[SyncRepoResult] = Field(default_factory=list)
    cloned: int = 0
    pulled: int = 0
    skipped: int = 0
    errors: int = 0
