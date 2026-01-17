# git-repo-checker

A CLI tool to scan, monitor, and sync git repositories across your system.

## Features

- **Scan directories** for git repositories and report their status
- **Auto-pull** clean repos that are behind their remote
- **Sync repositories** across machines from a central repos.yml file
- **GitHub Actions CI status** integration
- **JSON output** for scripting and CI pipelines
- **Stash detection** to warn about forgotten stashed changes

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

```bash
# Initialize a config file
grc init

# Scan all configured directories
grc scan

# Check a single repository
grc check /path/to/repo
```

## Commands

### `grc scan` - Scan Repositories

Scan directories for git repositories and report their status.

```bash
# Basic scan using config file
grc scan

# Scan specific paths
grc scan ~/code ~/projects

# Show only repos with issues
grc scan --warnings-only

# Filter by status
grc scan --status dirty,ahead,behind

# Include GitHub Actions CI status (requires gh CLI)
grc scan --ci

# Output as JSON for scripting
grc scan --json

# Disable auto-pull
grc scan --no-pull

# Combine options
grc scan --json --status dirty --ci
```

**Options:**
| Flag | Description |
|------|-------------|
| `-c, --config PATH` | Path to config file |
| `--no-pull` | Disable auto-pull for repos behind remote |
| `-w, --warnings-only` | Only show repos with warnings |
| `-s, --status STATUS` | Filter by status (comma-separated: dirty,ahead,behind,clean,diverged,no_remote,error,untracked) |
| `--ci` | Check GitHub Actions CI status (requires `gh` CLI) |
| `--json` | Output results as JSON |
| `-v, --verbose` | Verbose output |
| `-q, --quiet` | Minimal output |

### `grc sync` - Sync Repositories

Clone missing repositories and pull updates for existing ones based on a repos.yml file.

```bash
# Create a template repos.yml
grc sync --init

# Sync repositories
grc sync

# Sync from a specific repos file
grc sync -r ~/repos.yml

# Fetch repos.yml from a URL (e.g., GitHub gist)
grc sync --repos-url https://example.com/repos.yml

# Override path prefix for this machine
grc sync --path-prefix /data/projects

# Preview what would happen without making changes
grc sync --dry-run

# Only clone missing repos, don't pull existing
grc sync --no-pull
```

**Options:**
| Flag | Description |
|------|-------------|
| `-r, --repos PATH` | Path to repos.yml file |
| `--repos-url URL` | URL to fetch repos.yml from |
| `-p, --path-prefix PATH` | Override path prefix for this machine |
| `--init` | Create a template repos.yml file |
| `--no-pull` | Only clone missing repos, don't pull |
| `-n, --dry-run` | Show what would be done without executing |
| `-q, --quiet` | Minimal output |

### `grc check` - Check Single Repository

Check the status of a single repository.

```bash
grc check /path/to/repo
grc check . --verbose
```

### `grc init` - Create Config File

Create a default configuration file.

```bash
grc init                          # Creates ./git-repo-checker.yml
grc init ~/.config/git-repo-checker/config.yml
```

## Configuration

### Config File (`git-repo-checker.yml`)

```yaml
# Directories to scan for git repos
scan_paths:
  - ~/code
  - ~/projects

# Patterns to exclude (glob syntax)
exclude_patterns:
  - "**/node_modules"
  - "**/vendor"
  - "**/.cache"

# Explicit paths to exclude
exclude_paths:
  - ~/code/archived

# Branches considered "main" for warnings
main_branches:
  - main
  - master

# Auto-pull settings
auto_pull:
  enabled: true
  require_clean: true  # Only pull if working tree is clean
  skip_patterns:
    - "**/work-in-progress"

# Output settings
output:
  show_clean: true     # Show clean repos in output
  color: true
  verbosity: normal    # quiet, normal, or verbose
```

### Config File Locations

The tool searches for config in this order:
1. Path specified with `-c/--config`
2. `./git-repo-checker.yml` (current directory)
3. `~/.config/git-repo-checker/config.yml`

### Repos File (`repos.yml`)

For syncing repositories across machines:

```yaml
# Default path prefix (can be overridden per-machine)
path_prefix: ~/code

repos:
  # Basic entry - will clone to ~/code/my-project
  - path: my-project
    remote: git@github.com:user/my-project.git

  # Custom branch
  - path: another-project
    remote: git@github.com:user/another-project.git
    branch: develop

  # Absolute path (ignores path_prefix)
  - path: /opt/tools/special-tool
    remote: git@github.com:org/special-tool.git

  # Temporarily ignore a repo
  - path: old-project
    remote: git@github.com:user/old-project.git
    ignore: true
```

### Per-Machine Path Override

Create `~/.config/git-repo-checker/local.yml` to override the path prefix:

```yaml
# On your laptop
path_prefix: ~/code
```

```yaml
# On a cluster/server
path_prefix: /data/users/myname/projects
```

This allows the same repos.yml to work across different machines with different directory structures.

## Output Examples

### Table Output (default)

```
Scanned 15 repositories
  12 clean, 2 dirty, 1 with warnings

                              Repositories
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Path                   ┃ Branch  ┃ Status  ┃ Changes ┃ Ahead/Behind ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ ~/code/project-a       │ main    │ clean   │ -       │ -            │
│ ~/code/project-b       │ feature │ dirty   │ 3M 2?   │ +2           │
│ ~/code/project-c       │ main    │ behind  │ -       │ -5           │
└────────────────────────┴─────────┴─────────┴─────────┴──────────────┘
```

### With CI Status (`--ci`)

```
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Path                   ┃ Branch  ┃ Status  ┃ Changes ┃ Ahead/Behind ┃ CI      ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ ~/code/project-a       │ main    │ clean   │ -       │ -            │ passing │
│ ~/code/project-b       │ main    │ dirty   │ 3M      │ -            │ failing │
│ ~/code/project-c       │ main    │ clean   │ -       │ -            │ pending │
└────────────────────────┴─────────┴─────────┴─────────┴──────────────┴─────────┘
```

### JSON Output (`--json`)

```json
{
  "total_scanned": 2,
  "repos": [
    {
      "path": "/Users/me/code/project-a",
      "branch": "main",
      "status": "clean",
      "is_main_branch": true,
      "ahead_count": 0,
      "behind_count": 0,
      "changed_files": 0,
      "untracked_files": 0,
      "has_stash": false,
      "ci_status": "passing",
      "warnings": [],
      "error_message": null
    }
  ],
  "pull_results": [],
  "scan_errors": []
}
```

## Status Values

| Status | Description |
|--------|-------------|
| `clean` | Working tree is clean, in sync with remote |
| `dirty` | Has uncommitted changes |
| `untracked` | Has untracked files only |
| `ahead` | Local commits not pushed to remote |
| `behind` | Remote has commits not pulled locally |
| `diverged` | Both ahead and behind remote |
| `no_remote` | No upstream remote configured |
| `error` | Error checking repository status |

## CI Status Values

| Status | Description |
|--------|-------------|
| `passing` | Latest workflow run succeeded |
| `failing` | Latest workflow run failed |
| `pending` | Workflow is running or queued |
| `none` | No GitHub Actions workflows configured |
| `?` | Unable to determine (not a GitHub repo or `gh` not installed) |

## Warnings

The tool warns about:
- **dirty_main**: Uncommitted changes on main/master branch
- **no_remote**: No upstream remote configured
- **detached**: HEAD is in detached state
- **has_stash**: Repository has stashed changes

## Requirements

- Python 3.11+
- Git
- `gh` CLI (optional, for GitHub Actions status)

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=git_repo_checker --cov-fail-under=90

# Lint
ruff check src tests

# Type check
mypy src
```

## License

MIT
